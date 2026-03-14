# Config Drift Remediation Playbook

## Decision Tree

```
Was there a recent deployment?
  |
  Yes ──> Did deploy change config/env vars?
  |         |
  |         Yes ──> ROLLBACK (rollback_deployment)
  |         No  ──> Check secret rotation
  |
  No ──> Was a ConfigMap/Secret updated?
           |
           Yes ──> ESCALATE (noop_require_human) — need manual config fix
           No  ──> ESCALATE — unknown config source
```

## Tool Parameters

### rollback_deployment
```json
{"service_name": "<affected_service>"}
```
Use when: bad config was deployed

### noop_require_human
Use when: config change was external (secret rotation, manual edit)

## Post-Remediation Verification
1. Check pods start successfully (no CrashLoopBackOff)
2. Check service responds to health checks
3. Check logs clear of config errors
