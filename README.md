# routebox-route-optimizer

Python worker. Consumes route-calculation requests from SQS, computes optimal multi-stop routes using ortools, writes results back to Postgres.

Single-purpose service. No HTTP surface beyond `/healthz`. Just a long-running consumer loop.

> Read [`routebox-platform-docs`](https://github.com/312school/routebox-platform-docs) first if you haven't.

## What this service does

1. Polls the `route-calc-requests` SQS queue
2. For each message, fetches the relevant shipments and constraints from Postgres
3. Runs ortools' VRP solver
4. Writes results to the `route_calculations` table
5. Posts a completion event back to SNS

That's it.

## Repo layout

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
├── pyproject.toml
└── README.md
```

## Running locally

```
docker compose up
```

This spins up Postgres, a LocalStack instance for SQS, and the worker. It seeds a few test messages on startup. The compose file works as of last check, though the LocalStack version is pinned and may need updating eventually.

## Deploys

Standard `Jenkinsfile` using the [`routebox-jenkins`](https://github.com/312school/routebox-jenkins) shared library — `buildAndPushImage` + `deployToEcs`. Runs as an ECS service with a single task in dev/staging and 3 tasks in prod.

## The memory leak

This service has a memory leak. We've never found it.

The pod's memory grows linearly across about a week of runtime, eventually getting OOM-killed by ECS if left alone. Rather than fix the leak, we have a Jenkins job (`route-optimizer-weekly-restart`) that runs every Sunday at 02:00 UTC and forces an ECS service redeploy, which cycles the tasks. This has been in place for years. It works.

The leak is *probably* in ortools' Python bindings — we noticed it correlates with how many large solves happen — but we never proved it. Attempts to attribute it via `tracemalloc` and `objgraph` came up inconclusive. The Sunday restart became the path of least resistance.

**Don't disable the weekly restart job.** Don't remove it from the schedule. If you ever fix the actual leak, *then* remove the job.

## Database

Reads from many tables owned by other services. Writes only to `route_calculations`. See [`routebox-db-migrations/docs/schema-ownership.md`](https://github.com/312school/routebox-db-migrations) for the social contract.

## Configuration

Environment variables, in `src/config.py`. The interesting ones:

- `DATABASE_URL` — Postgres connection string, from Secrets Manager
- `SQS_QUEUE_URL` — input queue
- `SNS_TOPIC_ARN` — output topic
- `SOLVER_TIME_LIMIT_SECONDS` — default 30, sometimes tuned per-tenant via DB lookup
- `MAX_CONCURRENT_SOLVES` — default 4 in prod, 1 in dev

## Known issues

- The memory leak (above)
- Solver time limit is a per-process default but some large enterprise tenants need longer. Today this is hardcoded as a tenant-ID list in `src/solver.py`. It should be in the database. It isn't.
- Local LocalStack version is pinned to an old release because the consumer's signature-validation logic broke against newer LocalStack.
- `requirements.txt` has a couple of pins that conflict with newer Python versions. We're on 3.10 in prod. Moving to 3.12 means resolving them.

For broader context, read [`routebox-platform-docs/notes/handover.md`](https://github.com/312school/routebox-platform-docs/blob/main/notes/handover.md).
