# Redis OutOfMemoryError Runbook

## Symptoms
- `OutOfMemoryError: Java heap space` or `Connection timeout` in the database adapter logs
- Pods crash-looping with `OOMKilling`
- 5xx Error rate spikes
- High Memory utilization > 90%

## Root Causes
Usually caused by an unbounded cache growth or a large batch processing deployment causing memory spikes.

## Remediation Steps
1. **Rollback Deployment:** If a deployment was merged within the last 4 hours that touches caching or batch processing, rollback the deployment immediately using `kubectl rollout undo deployment/<service-name>`.
2. **Scale Up:** If no recent deployments are the culprit, scale the deployment to handle the burst load: `kubectl scale deployment <service-name> --replicas=3`.
3. **Restart Pods:** Force a cache flush by restarting the pods: `kubectl delete pods -l app=<service-name>`.
