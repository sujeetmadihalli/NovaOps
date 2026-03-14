# Traffic Surge Remediation Playbook

## Decision Tree

```
Is CPU > 90% across all pods?
  |
  Yes ──> Was there a recent deployment?
  |         |
  |         Yes ──> Did deploy reduce capacity? ──> ROLLBACK
  |         No  ──> SCALE UP (scale_deployment, +50% replicas)
  |
  No ──> Single pod issue? ──> RESTART (restart_pods)
```

## Tool Parameters

### scale_deployment
```json
{"service_name": "<affected_service>", "target_replicas": <current * 1.5>}
```
Use when: organic traffic surge overwhelming current capacity

### rollback_deployment
Use when: recent deploy reduced throughput/capacity

## Post-Remediation Verification
1. Check CPU drops below 80%
2. Check 5xx error rate normalizes
3. Check latency returns to baseline
