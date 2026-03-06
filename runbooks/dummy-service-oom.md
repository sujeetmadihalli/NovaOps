# Dummy Service Out Of Memory Runbook

## Description
The `dummy-service` is highly prone to synthetic memory leaks triggered during demonstration events, leading to OOMKilled pods and severe PagerDuty alerts.

## Symptoms
- Prometheus alerts firing for `DummyServiceMemorySaturation`.
- Container memory usage exceeding 500MB limit.
- Kubernetes events showing `OOMKilling` for `dummy-service`.

## Root Cause
The `/memory-leak` endpoint was invoked, appending garbage data to the `memory_hog` array until the container hits its cgroup limits.

## Mitigation Action
There are two ways to mitigate this:
1. **Restart the Pods**: A rolling restart will kill the bloated container and start a fresh one with an empty array.
2. **Rollback**: To prevent the endpoint from being hit again, rollback to the previous stable state.

**Action Recommended**: If an OOM event is detected and metrics confirm >90% memory saturation, invoke the `restart_pods` tool specifically for `dummy-service` in the `default` namespace.
