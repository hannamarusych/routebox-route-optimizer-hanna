# RouteBox Route Optimizer

## Overview

RouteBox Route Optimizer is the platform's route-calculation worker. It consumes route-calculation requests from a queue, solves multi-stop vehicle routing problems using Google OR-Tools, and writes the optimized results back to the shared database. It exists so route optimization runs as an isolated, horizontally-scalable background process instead of blocking any customer-facing request path.

---

## RouteBox Platform

This repository is one component of the RouteBox platform.

Related repositories:
- [routebox-infra-tf-hanna](https://github.com/hannamarusych/routebox-infra-tf-hanna)
- [routebox-shipments-api-hanna](https://github.com/hannamarusych/routebox-shipments-api-hanna)
- [routebox-tracking-events-hanna](https://github.com/hannamarusych/routebox-tracking-events-hanna)
- routebox-route-optimizer-hanna (this repository)
- routebox-ops-console-hanna

---

## Key Highlights

- Real-world infrastructure patterns
- Asynchronous, queue-driven worker (no customer-facing HTTP surface)
- Constraint-based vehicle routing with Google OR-Tools
- Horizontally scalable ECS worker fleet
- Platform engineering practices
- Operational tradeoffs documented rather than hidden

---

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full design, and the [diagrams](./diagrams) folder for visuals as they are added.

---

## Technology Stack

- Python 3.10
- Google OR-Tools (vehicle routing solver)
- psycopg2 (PostgreSQL driver)
- boto3 / botocore (AWS SDK for Python)
- structlog
- AWS SQS and SNS
- Docker, Jenkins (CI/CD)
- Deployed on AWS ECS

---

## Role in the Platform

This service turns shipment and constraint data into optimized multi-stop routes. It is a pure background worker: no other service or client calls it directly, and it does not expose a public API beyond a `/healthz` check. Its only job is to pull work off a queue, solve it, and persist the result, so the rest of the platform can treat route optimization as an asynchronous capability rather than a synchronous dependency.

## How It Interacts With the Infrastructure

The service runs as an ECS worker fleet defined in `routebox-infra-tf-hanna` — one task in dev and staging, three tasks in production. It reads its database connection string and other configuration from Secrets Manager, polls an SQS queue for work, and publishes completion events to an SNS topic. Deploys go through the shared Jenkins pipeline, using the same `routebox-jenkins` shared library as the platform's other services.

## Communication With Other RouteBox Services

This service does not call other RouteBox services directly. It receives work asynchronously: route-calculation requests arrive via SQS (published upstream, ultimately triggered by shipment activity in `routebox-shipments-api-hanna`), and results are written to the `route_calculations` table and announced via an SNS completion event. `routebox-ops-console-hanna` reads route data for operational dashboards. This asynchronous, event-driven pattern mirrors how `routebox-tracking-events-hanna` decouples ingestion from the services that depend on it.

## Deployment

Deployed via the standard Jenkins pipeline (`buildAndPushImage` + `deployToEcs`) defined in the Jenkinsfile. One notable operational detail: a scheduled Jenkins job (`route-optimizer-weekly-restart`) forces a redeploy every Sunday to cycle ECS tasks, as a mitigation for a known memory growth issue — see [docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md). See [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) for the full flow.

## Monitoring

Health is tracked through queue depth, solve latency, and task memory usage over time (relevant given the known memory growth pattern). The `/healthz` endpoint supports ECS task health checks. Known operational gaps are documented in [docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md).

## Where This Fits in the Overall Architecture

RouteBox Route Optimizer sits downstream of shipment creation and upstream of operational reporting: it consumes work triggered by shipment activity and produces route data that `routebox-ops-console-hanna` surfaces to operators. It is intentionally isolated from the request/response path of the platform's customer-facing services, so a slow or backed-up solver never affects shipment creation or tracking.

---

## What This Service Does

- Polls the `route-calc-requests` SQS queue
- For each message, fetches the relevant shipments and constraints from PostgreSQL
- Runs the OR-Tools vehicle routing problem (VRP) solver
- Writes results to the `route_calculations` table
- Publishes a completion event to SNS

## Repository Layout

```
.
├── src/
│   ├── consumer.py
│   ├── solver.py
│   ├── db.py
│   ├── config.py
│   └── main.py
├── tests/
├── Dockerfile
├── docker-compose.yml
├── Jenkinsfile
├── requirements.txt
└── pyproject.toml
```

## Configuration

Environment variables (see `src/config.py`):

- `DATABASE_URL` — PostgreSQL connection string, from Secrets Manager
- `SQS_QUEUE_URL` — input queue
- `SNS_TOPIC_ARN` — output topic
- `SOLVER_TIME_LIMIT_SECONDS` — default 30, sometimes tuned per tenant
- `MAX_CONCURRENT_SOLVES` — default 4 in production, 1 in development

## Running Locally

```
docker compose up
```

This starts PostgreSQL, a LocalStack instance for SQS, and the worker, and seeds a few test messages on startup. The LocalStack version is intentionally pinned — see [docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md).

## Known Issues

- A long-standing memory growth issue is mitigated with a scheduled weekly restart rather than a root-cause fix (see Troubleshooting)
- Per-tenant solver time limits are hardcoded as a tenant-ID list in `src/solver.py` instead of being stored in the database
- The pinned LocalStack version limits local testing against newer LocalStack releases
- Some dependency pins conflict with Python versions newer than 3.10, which blocks an upgrade path

For more, see [docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md).
