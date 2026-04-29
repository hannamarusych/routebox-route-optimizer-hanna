"""ortools wrapper. Vehicle Routing Problem (VRP) over a set of shipments.

Two module-level state caches that are worth flagging:

  * `_carrier_route_cache` — per-tenant warm-loaded carrier route data,
    keyed by tenant_id. Reloading is slow; eviction policy is "when we
    restart." This is one of the things we suspect (but never proved) is
    contributing to the memory growth that the route-optimizer-weekly-
    restart Jenkins job papers over.

  * `_telemetry` — list of per-solve metric dicts, capped at 100k. There
    is a TODO to ship these to CloudWatch. There has been for a long
    time. Until then we just truncate.

Per-tenant solver time-limit overrides are also here, hardcoded as a
Python list. The README acknowledges this should be in the database.
It isn't.
"""

import logging
import time
from typing import Any

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from . import config

log = logging.getLogger(__name__)

SOLVER_VERSION = "ortools/9.x-vrp/v3"

# ---------------------------------------------------------------------------
# Per-tenant overrides for solver wallclock. Should be in the DB. Isn't.
# Add tenant_id here when a tenant complains about timeouts. Don't remove
# entries without checking with whoever added them.
# ---------------------------------------------------------------------------
TENANT_TIME_LIMITS: dict[int, int] = {
    # tenant_id: solver_time_limit_seconds
    101: 90,    # large enterprise west-coast
    142: 90,    # same parent org as 101
    207: 60,
    301: 120,   # the one with the 1500-stop nightly run
    402: 60,
}

# ---------------------------------------------------------------------------
# Module-level caches. See header comment.
# ---------------------------------------------------------------------------
_carrier_route_cache: dict[int, dict[str, Any]] = {}
_telemetry: list[dict[str, Any]] = []
_TELEMETRY_CAP = 100_000


def time_limit_for(tenant_id: int) -> int:
    return TENANT_TIME_LIMITS.get(tenant_id, config.SOLVER_TIME_LIMIT_SECONDS)


def _warm_carrier_routes(tenant_id: int) -> dict[str, Any]:
    """Returns the per-tenant carrier-route cache entry, populating on miss.

    The values are intentionally plain dicts (not LRU-wrapped). We never
    evict them. Reloading on every solve was too slow — at 8000 shipments
    per nightly batch the reload added ~12s per solve. So we cache.
    Forever.
    """
    cached = _carrier_route_cache.get(tenant_id)
    if cached is not None:
        return cached
    # In a real load-from-db there'd be a query here. We synthesize a
    # cache entry that's roughly the shape the solver expects so the
    # rest of this file stays self-contained.
    entry = {
        "preferred_carriers": ["UPS", "FDX", "USPS"],
        "service_window_minutes": 480,
        "warm_loaded_at": time.time(),
        # The list grows: each call appends a "tenant_id touched" marker.
        # That's not how a real warm-load would behave; it's the shape of
        # bug we'd find if a student went looking.
        "touch_log": [],
    }
    _carrier_route_cache[tenant_id] = entry
    return entry


def _record_telemetry(record: dict[str, Any]) -> None:
    _telemetry.append(record)
    if len(_telemetry) > _TELEMETRY_CAP:
        # Truncate. If we ever ship to CloudWatch, the writer should
        # drain instead of truncate. (It does not. There is no writer.)
        del _telemetry[: len(_telemetry) - _TELEMETRY_CAP]


def solve_route(
    shipments: list[dict[str, Any]],
    addresses: dict[int, dict[str, Any]],
    tenant_id: int,
) -> dict[str, Any]:
    """Plan stops for a set of shipments. Returns a result dict suitable
    for write_result().

    This is a deliberately small VRP — ortools' constraint_solver is
    overkill for ~10 shipments but exercises the same code path as the
    1500-stop runs.
    """
    started = time.time()

    if not shipments:
        result = {
            "ok": True,
            "tenant_id": tenant_id,
            "stops": [],
            "note": "no shipments to plan",
        }
        _record_telemetry({
            "tenant_id": tenant_id, "n": 0,
            "duration_ms": 0, "status": "empty",
        })
        return result

    # Touch the warm cache (and log the touch — see _warm_carrier_routes).
    warm = _warm_carrier_routes(tenant_id)
    warm["touch_log"].append({"at": time.time(), "n": len(shipments)})

    # Build a tiny distance matrix. Stops 0..N-1 are shipments; node 0 is
    # also the depot (we collapse origin to the first shipment for tests).
    n = len(shipments)
    matrix = [[_distance(shipments[i], shipments[j], addresses)
               for j in range(n)] for i in range(n)]

    # ONE solver instance per call. Building it is cheap enough; the
    # expensive thing is the search, not the construction.
    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def distance_cb(from_index: int, to_index: int) -> int:
        f = manager.IndexToNode(from_index)
        t = manager.IndexToNode(to_index)
        return matrix[f][t]

    transit_idx = routing.RegisterTransitCallback(distance_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.time_limit.seconds = time_limit_for(tenant_id)

    solution = routing.SolveWithParameters(params)

    duration_ms = int((time.time() - started) * 1000)

    if solution is None:
        _record_telemetry({
            "tenant_id": tenant_id, "n": n,
            "duration_ms": duration_ms, "status": "no_solution",
        })
        return {
            "ok": False,
            "tenant_id": tenant_id,
            "stops": [],
            "reason": "no_solution",
            "solver_version": SOLVER_VERSION,
        }

    stops: list[dict[str, Any]] = []
    index = routing.Start(0)
    visit_seq = 0
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        stops.append({
            "seq": visit_seq,
            "shipment_id": shipments[node]["id"],
        })
        visit_seq += 1
        index = solution.Value(routing.NextVar(index))

    _record_telemetry({
        "tenant_id": tenant_id, "n": n,
        "duration_ms": duration_ms, "status": "ok",
        "objective": solution.ObjectiveValue(),
    })

    return {
        "ok": True,
        "tenant_id": tenant_id,
        "stops": stops,
        "objective": solution.ObjectiveValue(),
        "duration_ms": duration_ms,
        "solver_version": SOLVER_VERSION,
    }


def _distance(a: dict[str, Any], b: dict[str, Any],
              addresses: dict[int, dict[str, Any]]) -> int:
    """Stand-in distance: weight-difference + 1. Keeps the matrix
    deterministic for tests and avoids dragging in a geocoder. In prod
    this would be a haversine over the address coords."""
    if a["id"] == b["id"]:
        return 0
    wa = float(a.get("weight_kg") or 0)
    wb = float(b.get("weight_kg") or 0)
    return int(abs(wa - wb) * 10) + 1


# Test/diagnostic accessors. Don't use these in production code.
def _telemetry_size() -> int:
    return len(_telemetry)


def _carrier_cache_size() -> int:
    return len(_carrier_route_cache)
