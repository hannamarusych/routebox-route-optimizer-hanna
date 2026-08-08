# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added
- Standardized documentation set: ARCHITECTURE.md, ROADMAP.md, CONTRIBUTING.md, LICENSE, and docs/ (DEPLOYMENT, STATE_MANAGEMENT, TROUBLESHOOTING).
- RouteBox platform cross-reference section in README.

### Changed
- README rewritten to the RouteBox platform documentation standard, framing this service's role within the broader platform.

## [0.1.0] - Initial Service

- Python SQS consumer for route-calculation requests.
- OR-Tools-based vehicle routing solver with per-tenant tuning.
- Jenkins-based CI/CD pipeline and Dockerfile for containerized deployment.
- Scheduled weekly restart job to mitigate a known memory growth issue.
