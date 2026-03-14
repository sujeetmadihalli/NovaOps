# Deadlock Analyst Playbook

## Key Questions to Answer
1. Is CPU near 0% despite the service being "running"?
2. Are readiness probes failing while liveness probes pass?
3. Is the service accepting connections but not responding?
4. Are thread dumps showing threads in BLOCKED/WAITING state?
5. Is this affecting all pods or just some?

## Investigation Steps

### Step 1: Check CPU Pattern
- Near-zero CPU with running pods = classic deadlock signal
- Normal CPU = probably not a deadlock

### Step 2: Check Probe Status
- Readiness failing + liveness passing = app frozen but process alive
- Both failing = app crashed, not deadlocked

### Step 3: Check Logs
- Look for: "Deadlock detected", "Thread waiting", "lock held by"
- Check for connection pool exhaustion

### Step 4: Check if Partial
- Some pods healthy, others frozen = partial deadlock
- All pods frozen = systemic deadlock

## Critical Distinction
- **Deadlock** → restart_pods (scaling creates more deadlocked pods)
- **Resource starvation** → may need scaling instead
- **Partial deadlock** → restart affected pods only
