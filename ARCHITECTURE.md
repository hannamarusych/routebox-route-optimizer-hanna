# Architecture

## Overview

RouteBox Route Optimizer is a single-purpose background worker. It has no customer-facing HTTP surface beyond a health check, and its entire job is to turn queued route-calculation requests into optimized routes stored in the shared database.

## Internal Design

- **Consumer** (`src/consumer.py`): long-running loop that polls the `route-calc-requests` SQS queue.
- **Solver** (`src/solver.py`): wraps Google OR-Tools' vehicle routing problem (VRP) solver, applying per-tenant time limits and constraints.
- **Database access** (`src/db.py`): fetches shipments and constraints for a given request, and writes results to `route_calculations`.
- **Configuration** (`src/config.py`): centralizes environment-driven configuration, including queue URLs, topic ARNs, and solver tuning parameters.
- **Entry point** (`src/main.py`): wires the above together into the worker process.

The design is intentionally simple: one message in, one solve, one row written, one event published. There is no internal queuing, batching, or retry logic beyond what SQS provides natively.

## Fit Within the RouteBox Platform

This service consumes work rather than serving requests. Route-calculation requests are triggered upstream by shipment activity in `routebox-shipments-api-hanna` and delivered via SQS. Once a route is computed, this service writes to `route_calculations` and publishes a completion event to SNS, which `routebox-ops-console-hanna` and other interested consumers can act on. `routebox-infra-tf-hanna` provisions the ECS worker fleet, queue, topic, and database this service depends on.

This mirrors the asynchronous, event-driven pattern used by `routebox-tracking-events-hanna`: producers and consumers communicate through durable infrastructure (queues, topics, tables) rather than direct calls, so no single service's slowdown cascades into another's.

## Deployment Architecture

Runs as an ECS worker fleet — one task in dev and staging, three tasks in production — built and deployed through the shared Jenkins pipeline (`buildAndPushImage` + `deployToEcs`). See [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) for the full flow, including the scheduled weekly restart job.

## Observability

Health today is tracked primarily through SQS queue depth, solve latency, and ECS task memory usage, the last of which matters because of a known memory growth pattern (see [docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md)). The `/healthz` endpoint supports ECS health checks but is not a rich observability surface on its own.

## Security Considerations

- Database credentials, queue URLs, and topic ARNs are sourced from Secrets Manager and environment configuration rather than hardcoded.
- The service only writes to `route_calculations`; it reads from tables owned by other services under an established schema-ownership agreement (see `routebox-db-migrations`).
- Per-tenant solver time limit overrides are currently hardcoded in application code rather than stored in the database — a known gap, not a security issue, but worth fixing for maintainability.

## Future Improvements

- Root-cause and fix the long-standing memory growth issue so the weekly restart job can be retired.
- Move per-tenant solver time limit overrides into the database instead of a hardcoded list.
- Resolve dependency pins blocking a move to newer Python versions.
- Revisit the pinned LocalStack version to restore full local-development parity.
