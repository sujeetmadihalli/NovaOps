# Docker Fixes (Major)

Updated: 2026-03-13

## Summary

This file captures the Docker-specific fixes applied so incident reports and live telemetry work consistently on new machines.

## What Was Already There (No New Creation Needed)

1. API service already existed.
- `novaops-api` (FastAPI) was already defined in `docker-compose.yml`.
- No new API service had to be created.

2. LocalStack service already existed.
- `localstack` was already present and configured for S3 + DynamoDB.

## What Was Fixed

1. Startup sequencing and readiness
- Added LocalStack healthcheck.
- Made `novaops-api` wait for healthy LocalStack (`depends_on.condition: service_healthy`).
- Why: avoids API booting before LocalStack resources are ready.

2. Incident history persistence in Docker
- Added LocalStack credentials for API container:
  - `AWS_ACCESS_KEY_ID=test`
  - `AWS_SECRET_ACCESS_KEY=test`
- Why: DynamoDB writes/reads were failing (`Unable to locate credentials`), so incidents were not appearing reliably.

3. Log persistence for live telemetry
- Replaced fragile host file bind with named volume:
  - from `./novaops.log:/app/novaops.log`
  - to `novaops-logs:/var/log/novaops`
- Why: removes host pre-create file requirement and keeps logs stable across restarts.

4. API file logger alignment
- Added explicit file logging in `api/server.py` when `NOVAOPS_LOG_PATH` is set.
- Why: dashboard `/api/logs` reads a file; API logs must always be written to that same file path.

5. Evaluation harness log path alignment
- Updated `evaluation_harness/multi_scenario_test.py` to use `NOVAOPS_LOG_PATH` (fallback: `novaops.log`) instead of hardcoded `novaops.log`.
- Why: running harness in container now streams into dashboard live terminal source.

6. Container testability fixes
- `.dockerignore` no longer excludes `tests/` and `evaluation_harness/`.
- Added `tests/__init__.py` so `python -m unittest discover -s tests -v` works in Python 3.10 container.

## Commands

### Docker (Run + Test)

```powershell
cd G:\NovaOps\Music\NovaOps-v2
docker compose up -d --build
docker compose exec -e PYTHONPATH=. -e NOVAOPS_USE_MOCK=1 novaops-api python evaluation_harness/multi_scenario_test.py
```

### Web / Local Python (Run Harness on Host)

```powershell
cd G:\NovaOps\Music\NovaOps-v2
$env:PYTHONPATH = "."
$env:NOVAOPS_USE_MOCK = "1"
python evaluation_harness/multi_scenario_test.py
```

## Important Note

If Docker is running and you want incident reports + live telemetry inside the Docker dashboard, run the harness inside container (`docker compose exec ...`), not on host Python.
