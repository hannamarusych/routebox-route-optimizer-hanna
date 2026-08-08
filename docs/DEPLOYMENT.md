# Deployment Guide

## Overview

This service deploys to AWS ECS via the shared Jenkins pipeline used across the RouteBox platform, defined in the `routebox-jenkins` shared library.

## Pipeline

The `Jenkinsfile` in this repository imports the shared library and calls `buildAndPushImage` followed by `deployToEcs` for the `route-optimizer` service.

## Deployment Steps

1. A merge to `main` triggers the Jenkins pipeline.
2. The pipeline builds the Docker image from the repository `Dockerfile`.
3. The image is pushed to the container registry.
4. `deployToEcs` updates the ECS service definition and triggers a rolling deployment.
5. New tasks pull configuration and secrets from Secrets Manager, including the database connection string, SQS queue URL, and SNS topic ARN.

## Environments

One ECS task runs in development and staging; three tasks run in production to handle solve volume and provide headroom for the periodic restarts described below.

## Scheduled Weekly Restart

A separate Jenkins job, `route-optimizer-weekly-restart`, runs every Sunday at 02:00 UTC and forces an ECS service redeploy to cycle running tasks. This exists to mitigate a known memory growth issue rather than to ship new code — see [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) for the full background. Do not disable or remove this job without first addressing the underlying memory issue.

## Rollback

Roll back by redeploying the previous known-good image tag through the same Jenkins pipeline.
