# State Management

## Overview

This service is a stateless worker at the application layer. It holds no state in memory between messages; all persistent state lives in PostgreSQL.

## What State Exists

- **route_calculations**: the single table this service writes to. Stores the computed route, the shipments and constraints it covers, and metadata about the solve.
- No in-memory caching of shipment or constraint data between messages.
- No session state; each SQS message is processed independently.

## Reads From Other Services' Tables

This service reads shipment and constraint data from tables owned by other RouteBox services under an established schema-ownership agreement (documented in `routebox-db-migrations/docs/schema-ownership.md`). It writes only to `route_calculations`. This division keeps ownership boundaries clear even though the service reads broadly.

## Message Processing as State Management

Because this is a queue-driven worker, message visibility and acknowledgement are effectively part of its state model:

- A message is only removed from the queue after a successful solve and database write.
- If processing fails partway through, SQS redelivers the message according to the queue's configured visibility timeout and retry policy.
- The solver itself is idempotent per request: re-running the same route-calculation request produces an equivalent result, so redelivery does not corrupt state.

## Local State

Local development uses `docker compose up`, which starts PostgreSQL and a LocalStack instance for SQS and seeds a few test messages. See [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) for the known limitation around the pinned LocalStack version.
