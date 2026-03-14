# Dependency Failure Remediation Playbook

## Decision Tree

```
Is the dependency external?
  |
  Yes ──> ESCALATE (noop_require_human)
  |       We cannot fix external outages
  |
  No ──> Is it an internal service?
           |
           Yes ──> Investigate that service as new incident
           No  ──> DNS/infrastructure? ──> ESCALATE
```

## Tool Parameters

### noop_require_human
Use when: external dependency is down (we can't restart their service)

## Post-Remediation
- Monitor dependency status page
- Enable circuit breaker if available
- Consider fallback/degraded mode
