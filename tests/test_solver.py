"""Unit tests for solver.solve_route. Synthetic inputs only — no DB."""

from src import solver


def _ship(i, w):
    return {"id": i, "weight_kg": w, "origin_address_id": None,
            "destination_address_id": None}


def test_empty_shipments_returns_ok_no_stops():
    res = solver.solve_route([], {}, tenant_id=1)
    assert res["ok"] is True
    assert res["stops"] == []


def test_single_shipment_yields_single_stop():
    res = solver.solve_route([_ship(101, 1.0)], {}, tenant_id=1)
    assert res["ok"] is True
    assert len(res["stops"]) == 1
    assert res["stops"][0]["shipment_id"] == 101


def test_multiple_shipments_visited_each_exactly_once():
    ships = [_ship(1, 1.0), _ship(2, 5.0), _ship(3, 3.0), _ship(4, 9.0)]
    res = solver.solve_route(ships, {}, tenant_id=1)
    assert res["ok"] is True
    visited = sorted(s["shipment_id"] for s in res["stops"])
    assert visited == [1, 2, 3, 4]


def test_tenant_time_limit_overrides_default():
    assert solver.time_limit_for(101) == 90  # listed
    # Unlisted falls back to config.SOLVER_TIME_LIMIT_SECONDS (default 30).
    assert solver.time_limit_for(99999) == 30


def test_warm_cache_growth_is_observable():
    """The carrier-route cache grows per-tenant and is never evicted —
    that's the leak shape this codebase is famous for. Confirm it grows."""
    assert solver._carrier_cache_size() == 0
    solver.solve_route([_ship(1, 1.0)], {}, tenant_id=10)
    solver.solve_route([_ship(2, 2.0)], {}, tenant_id=20)
    solver.solve_route([_ship(3, 3.0)], {}, tenant_id=30)
    assert solver._carrier_cache_size() == 3
    # Same tenant doesn't add a new entry.
    solver.solve_route([_ship(4, 4.0)], {}, tenant_id=10)
    assert solver._carrier_cache_size() == 3


def test_telemetry_records_each_solve():
    assert solver._telemetry_size() == 0
    solver.solve_route([_ship(1, 1.0)], {}, tenant_id=1)
    solver.solve_route([], {}, tenant_id=1)
    assert solver._telemetry_size() == 2
