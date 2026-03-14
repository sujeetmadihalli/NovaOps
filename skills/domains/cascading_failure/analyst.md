# Cascading Failure Analyst Playbook

## Key Questions to Answer
1. Are multiple services failing simultaneously?
2. Which service failed FIRST? (root vs symptom)
3. Are connection pools exhausted?
4. Are circuit breakers tripped?
5. Is there a dependency chain visible?

## Investigation Steps

### Step 1: Identify the Root Service
- Check timestamps — which service's errors started first?
- That's likely the root cause, others are cascading symptoms

### Step 2: Check Connection Pools
- Connection pool exhausted → upstream service is slow/down
- Thread pool exhausted → too many waiting requests

### Step 3: Map the Dependency Chain
- Service A → Service B → Service C
- If C is down, B times out, A gets errors
- Fix C, not A

### Step 4: Check Logs Across Services
- Look for: circuit breaker, downstream timeout, connection pool
- Correlate timestamps across services

## Critical Distinction
- **Fix the ROOT service**, not the symptoms
- **Don't restart downstream services** — they'll crash again
- **Escalate if root service is external**
