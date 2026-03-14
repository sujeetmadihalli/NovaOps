# Traffic Surge Analyst Playbook

## Key Questions to Answer
1. Is CPU saturated? (>90% indicates overload)
2. Are thread pools exhausted? (check logs for ThreadPoolExecutor)
3. Are liveness/readiness probes failing?
4. Is this organic traffic growth or a sudden spike?
5. Was there a recent deployment that reduced capacity?

## Investigation Steps

### Step 1: Check CPU and Request Metrics
- Query CPU utilization — is it >90%?
- Check error rate — are 5xx errors spiking?
- Check latency — has P99 latency degraded?

### Step 2: Check Pod Health
- Are pods being evicted or restarted?
- Are liveness probes failing?
- How many replicas are currently running?

### Step 3: Correlate with Deployments
- Was there a recent deploy that may have reduced throughput?
- Did someone reduce replica count?

### Step 4: Check Logs
- Look for: ThreadPoolExecutor exhausted, Rejecting requests, timeout
- Check if errors are uniform across pods

## Critical Distinction
- **Organic traffic surge** → scale up
- **Deploy reduced capacity** → rollback deployment
- **Single pod issue** → restart that pod, not scale
