# Roadmap

## Current State (Sprint 5)

- Core queue-driven route optimization pipeline is in production, consuming from SQS and writing to `route_calculations`.
- Runs as a horizontally scalable ECS worker fleet (1 task in dev/staging, 3 in production).
- Documentation brought up to the RouteBox platform standard: architecture, deployment, state management, and troubleshooting guides added.

## In Progress

- Investigating the root cause of the long-standing memory growth issue mitigated today by a weekly scheduled restart.
- Evaluating how to move per-tenant solver time limit overrides out of application code and into the database.

## Planned

- Resolve dependency pins that block moving off Python 3.10.
- Revisit the pinned LocalStack version so local development can track newer releases.
- Add clearer solver-level metrics (solve time distribution, constraint violations) beyond basic queue and memory monitoring.

## Longer Term

- Retire the weekly restart job once the memory issue is fixed at its root.
- Explore splitting very large solves across multiple workers if solve time becomes a bottleneck at scale.
- Contribute this service's context to the future `routebox-platform` documentation repository, including its role in the platform's service catalog and architecture decision records.
