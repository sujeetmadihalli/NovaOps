# OOM Analyst Playbook

## Key Questions to Answer
1. When did memory start climbing? (gradual leak vs sudden spike)
2. Was there a recent deployment? (check commits in last 24h)
3. Is the OOM happening on all pods or just some?
4. What is the memory limit vs actual usage?
5. Are there specific error patterns in logs? (heap space, GC overhead, cgroup)

## Investigation Steps

### Step 1: Check Memory Timeline
- Query metrics for memory_usage_mb over last 1h
- Look for: sudden spike (deployment issue) vs gradual climb (leak/bloat)

### Step 2: Correlate with Deployments
- Check GitHub commits in last 24h
- If recent commit exists AND memory spiked after it → deployment-caused
- If NO recent commit → organic issue (cache bloat, leak in old code)

### Step 3: Check K8s Events
- Look for OOMKilling events
- Check pod restart count
- Check if CrashLoopBackOff is present

### Step 4: Analyze Logs
- Search for: OutOfMemoryError, heap space, GC overhead limit
- Check if errors started before or after last deployment

## Critical Distinction
- **Recent deploy + OOM** → likely rollback candidate
- **No recent deploy + OOM** → likely restart candidate (flush cache/heap)
- **Gradual memory climb over days** → memory leak, needs code fix (escalate)
