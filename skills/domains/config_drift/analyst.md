# Config Drift Analyst Playbook

## Key Questions to Answer
1. Is the service CrashLooping immediately on startup?
2. Are there ConnectionRefused or Access Denied errors?
3. Was there a recent config/secret change?
4. Did a deploy change environment variables?
5. Is this a feature flag misconfiguration?

## Investigation Steps

### Step 1: Check CrashLoop Pattern
- Instant crash on startup = config/env issue
- Crash after running for a while = runtime issue (not config)

### Step 2: Check Logs for Config Errors
- ConnectionRefused → wrong host/port in config
- Access Denied → bad credentials
- Missing env var → deployment config issue

### Step 3: Correlate with Deployment
- Recent deploy that changed config → rollback candidate
- Recent secret rotation → rotation failure

### Step 4: Check Environment
- Compare running config vs expected config
- Check if configmap/secret was updated recently

## Critical Distinction
- **Bad deployment config** → rollback_deployment
- **Secret rotation failure** → rollback + rotate secrets (escalate)
- **Feature flag issue** → rollback flag change
