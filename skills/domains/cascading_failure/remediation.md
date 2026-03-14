# Cascading Failure Remediation Playbook

## Decision Tree

```
Identified the root service?
  |
  Yes ──> Is it an internal service we can fix?
  |         |
  |         Yes ──> Apply domain-specific fix to ROOT service
  |         No  ──> ESCALATE (noop_require_human)
  |
  No ──> ESCALATE — cascade root unclear
```

## Key Principle
Fix the ROOT cause service. Downstream services will recover automatically.

## Tool Parameters
- Use domain-specific tool for the root service (rollback, restart, scale)
- Use noop_require_human if root is external

## Post-Remediation Verification
1. Check root service recovers
2. Check downstream services stop erroring
3. Check connection pools drain
4. If downstream still failing → restart downstream (restart_pods)
