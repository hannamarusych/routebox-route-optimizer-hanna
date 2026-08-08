# Contributing

Thanks for taking an interest in RouteBox Route Optimizer.

## Workflow

1. Create a feature branch from `main`.
2. Make your changes, including tests where applicable.
3. Open a pull request describing what changed and why.
4. Ensure the Jenkins pipeline passes before requesting review.

## Code Standards

- Follow standard Python formatting conventions before committing.
- Keep solver logic in `src/solver.py` isolated from queue-handling logic in `src/consumer.py`.
- Prefer small, focused pull requests over large ones.

## Tests

- Add or update tests for any change to solver behavior, constraint handling, or database writes.
- Run the test suite locally before opening a pull request (`testcontainers` and `moto` are used to simulate Postgres, SQS, and SNS).

## Reporting Issues

If you find a bug or a gap in documentation, please open an issue describing the behavior you observed and what you expected instead. For anything security-related, please avoid filing a public issue and reach out directly instead.
