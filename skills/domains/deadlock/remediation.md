# Deadlock Remediation Playbook

## Decision Tree

```
Is CPU near 0% with running pods?
  |
  Yes ──> RESTART (restart_pods)
  |       NEVER scale — creates more deadlocked pods
  |
  No  ──> Probably not a deadlock, re-evaluate domain
```

## Tool Parameters

### restart_pods
```json
{"service_name": "<affected_service>"}
```
Use when: confirmed deadlock (near-zero CPU, unresponsive)

## Post-Remediation Verification
1. Check CPU returns to normal levels
2. Check readiness probes pass
3. Check service responds to health checks
4. If deadlock recurs within minutes → escalate (code bug)
