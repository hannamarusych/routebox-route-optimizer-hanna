# Troubleshooting

## The Memory Leak

This service has a known memory growth issue that has never been root-caused. Task memory grows roughly linearly over about a week of runtime and would eventually be OOM-killed by ECS if left unaddressed.

**Current mitigation:** a scheduled Jenkins job, `route-optimizer-weekly-restart`, runs every Sunday at 02:00 UTC and forces an ECS service redeploy, cycling the tasks before memory growth becomes a problem. This has been in place for a long time and is stable.

**What's known:** the growth correlates with the volume of large solves processed, which points toward OR-Tools' Python bindings as the likely source. Investigation using `tracemalloc` and `objgraph` was inconclusive. The weekly restart became the pragmatic path forward rather than a proven fix.

**Guidance:**
- Do not disable or remove the weekly restart job unless the underlying leak has actually been fixed.
- If you investigate this further and make progress, document findings — this is a good candidate for a real fix given enough dedicated time.

## Hardcoded Per-Tenant Solver Limits

`SOLVER_TIME_LIMIT_SECONDS` defaults to 30, but some large enterprise tenants need more time to solve. Today, tenant-specific overrides are hardcoded as a tenant-ID list in `src/solver.py` rather than being stored in the database. This works but is not easily discoverable or self-service; see [ROADMAP.md](../ROADMAP.md) for the plan to move this into the database.

## Pinned LocalStack Version

The LocalStack version used in local development is pinned to an older release because the consumer's signature-validation logic broke against newer LocalStack versions. This limits how representative local testing is of the latest LocalStack behavior. Upgrading requires revisiting the signature-validation logic first.

## Python Version Constraints

Production runs on Python 3.10. Some entries in `requirements.txt` (notably `numpy` and `ortools`) are pinned in ways that conflict with newer Python versions, particularly 3.12 and later. Moving to a newer Python version requires resolving these pins and re-validating solver output, which has not yet been prioritized.

## Database Reads Across Service Boundaries

This service reads from several tables it does not own, under an established schema-ownership agreement documented in `routebox-db-migrations/docs/schema-ownership.md`. If a solve is failing due to missing or unexpected shipment/constraint data, check the owning service's schema and recent migrations first.
