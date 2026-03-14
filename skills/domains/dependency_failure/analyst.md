# Dependency Failure Analyst Playbook

## Key Questions to Answer
1. Is an external API/service unreachable?
2. Are DNS lookups failing?
3. Is this affecting all pods equally?
4. Did the dependency go down, or did we lose connectivity?
5. Is there a circuit breaker tripped?

## Investigation Steps

### Step 1: Check Error Patterns
- UnknownHostException → DNS failure
- Connection refused → service down
- Timeout → service degraded or network issue

### Step 2: Check if Internal or External
- External dependency → we can't fix it, escalate
- Internal dependency → investigate that service

### Step 3: Check Impact Scope
- All pods affected → dependency is actually down
- Some pods affected → possible network partition

### Step 4: Check Logs
- Look for: timeout, connection refused, UnknownHostException
- Check for retry exhaustion patterns

## Critical Distinction
- **External dependency down** → noop_require_human (can't fix)
- **Internal dependency** → investigate root service instead
- **DNS failure** → check DNS infrastructure (escalate)
