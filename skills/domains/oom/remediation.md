# OOM Remediation Playbook

## Decision Tree

```
Was there a deployment in last 24h?
  |
  Yes ──> Did memory spike correlate with deploy time?
  |         |
  |         Yes ──> ROLLBACK (rollback_deployment)
  |         No  ──> Likely coincidence, treat as organic
  |
  No ──> Is memory at 100% limit?
           |
           Yes ──> RESTART (restart_pods) to flush heap/cache
           No  ──> Monitor, may self-recover
```

## Tool Parameters

### rollback_deployment
```json
{"service_name": "<affected_service>"}
```
Use when: bad deployment caused the OOM

### restart_pods
```json
{"service_name": "<affected_service>"}
```
Use when: organic cache bloat or heap accumulation, no bad deploy

## Post-Remediation Verification
1. After tool execution, wait 30 seconds
2. Check: are pods healthy? (no CrashLoopBackOff)
3. Check: is memory usage dropping?
4. If still failing → escalate to human
