# NovaOps v2 -- Evaluation Guide

This guide provides a step-by-step narrative to demonstrate the full power, complexity, and unique architectural design of NovaOps v2 to stakeholders and technical evaluators.

---

## The Pitch (1 Minute)

**The Problem:** When a P1 incident hits at 3 AM, an SRE is yanked out of bed. They spend the next 45 minutes manually pulling logs, checking Kubernetes states, querying Prometheus, and digging through recent GitHub commits just to *understand* what broke, let alone fix it.

**The Solution:** NovaOps v2 doesn't just automate bash scripts. It is a dual-pipeline, autonomous SRE War Room powered by Amazon Nova 2. It investigates anomalies using 4 parallel domain experts, synthesizes a root cause, proposes a fix, and calls the on-call engineer on the phone to explain the situation and get verbal approval.

**The Differentiator:** LLMs can hallucinate. To solve this, we built a **Blind Jury Validation** system. A separate panel of AI jurors looks at the raw data *without* seeing the War Room's conclusion. If they disagree, a strict Governance Gate halts automated execution and escalates to a human -- via a real phone call powered by Amazon Connect and Nova real-time voice AI.

---

## Pre-Demo Checklist

Before starting, ensure your environment is clean and ready:

1. Ensure your `.env` contains real AWS Bedrock credentials (see `AWS_PERMISSIONS_GUIDE.md`).
2. Start the backend: `docker compose up -d`
3. Have the dashboard open: `http://localhost:8082/dashboard/`
4. Have a terminal open in the project directory ready to run `./trigger_live_outage.sh`.
5. For voice escalation demo: set `NOVAOPS_VOICE_USE_MOCK=false` and configure Connect env vars (or keep mock mode to show the log output).

---

## The Live Demo (7-10 Minutes)

### Phase 1: Triggering the Disaster

Tell the evaluators you are going to simulate a real-world production outage.

1. Run `./trigger_live_outage.sh` in your terminal.
2. **Explain what's happening:** "This script spins up a real Minikube Kubernetes cluster, deploys our mock `dummy-service`, and aggressively spams a memory-leak endpoint. The pod will hit its 500Mi memory limit and Kubernetes will instantly `OOMKill` it. This simulates a classic, nasty production memory leak."

### Phase 2: Live Telemetry & The Multi-Agent War Room

Switch immediately to the **Dashboard** (`http://localhost:8082/dashboard/`) and click on the **Live Telemetry Logs** tab.

1. Show the logs streaming in real-time. Click the **Nova-Agent** filter.
2. **Highlight the Architecture:** "As soon as the pod crashed, our API received a webhook. Right now, Amazon Nova is spinning up a virtual War Room. It has dynamically dispatched four parallel SRE agents:
   - A **Log Analyst** fetching crash traces.
   - An **Infra Specialist** checking Kubernetes state.
   - An **Anomaly Specialist** identifying metric spikes.
   - A **Deployment Specialist** checking recent GitHub commits for bad code."
3. Show the agents passing data to the **Root Cause Reasoner**, and point out the **Critic Agent** which adversarially reviews the hypothesis to ensure Nova isn't jumping to conclusions.

### Phase 3: The Blind Jury

This is the most architecturally unique part. Switch the dashboard filter to **Jury & Gov**.

1. **Explain the Jury:** "Even with a Critic, AI can suffer from groupthink. While the War Room formulated a plan, we simultaneously spun up an entirely isolated **Jury** of Nova instances. They are fed *only* the raw logs and metrics -- they cannot see the War Room's output."
2. **The Convergence Check:** Show the logs where the Jury's conclusion is compared against the War Room's conclusion.
   - *"If they agree, our confidence score spikes."*
   - *"If they disagree, our custom Convergence logic mathematically penalizes the confidence score."*

### Phase 4: The Governance Gate

Stay on the logs or switch to the **Incident Resolutions** tab as the incident finalizes.

1. Explain the **Policy Engine**: "We don't just blindly execute AI code. The final mitigation plan passes through our Governance Engine. It looks at the severity (P1/P2), the action weight (Scale vs Rollback), and the mathematically adjusted Confidence Score."
2. Show how the engine dynamically assigns a risk score (e.g., `Risk: 75/100`) and enforces policies like `convergence_guard_require_approval`.

### Phase 5: Voice Escalation -- The Phone Call

This is the showstopper moment. Watch the logs for `ESCALATION POLICY: critical incident detected`.

1. **Explain the Flow:** "Because this is a P1 incident with a high risk score, our Escalation Policy has classified it as critical. NovaOps is now placing an outbound phone call to the on-call engineer via Amazon Connect."
2. **What happens on the call:** "The system plays a brief TTS summary of the incident, then Nova's real-time AI takes over the conversation. The engineer can ask questions -- 'What service is affected?', 'What's the root cause?' -- and Nova answers from the investigation context. When the engineer says 'yes, go ahead', the Lambda detects approval and triggers remediation through the same governance gate."
3. **Fallback safety:** "If the call fails -- no answer, Connect misconfigured, network issue -- NovaOps automatically falls back to a high-visibility Slack critical escalation. No incident is ever dropped because a phone call failed."
4. In mock mode, show the log output: `[MOCK CALL] Would dial +1XXXXXXXXXX for incident...` followed by the Slack critical escalation log.

### Phase 6: The Post-Incident Report (PIR)

Show the final incident card at the top of the dashboard feed.

1. Click the **Post-Incident Report** button on the UI.
2. **Explain the AWS Integration:** "Finally, nobody likes writing post-mortems. NovaOps takes the entire incident trace, uses Nova to draft a human-readable Post-Incident Report, dynamically generates a PDF, and saves it into Amazon S3."

---

## Key Talking Points for Q&A

If evaluators ask about the technical depth:

- **Zero-Shot & Few-Shot Reasoning:** We aren't using rigid IF/THEN statements. Nova evaluates raw Prometheus metrics and unstructured pod logs on the fly.
- **Asynchronous Python & ThreadPoolExecutors:** The agent orchestration is heavily parallelized. The four War Room agents and the Jury deliberations happen concurrently to reduce Time-To-Mitigate (TTM).
- **Dual-Backend Design:** We integrated AWS LocalStack so the app runs fully locally using simulated DynamoDB and S3, but scales instantly to real AWS environments simply by dropping the `ENDPOINT` environment overrides.
- **Append-Only Auditing:** Every decision made by every agent is logged into an `audit.jsonl` file, ensuring compliance and perfect traceability.
- **Voice Escalation Architecture:** Amazon Connect places the call, Lex V2 manages conversation turns, a Lambda bridges speech to Bedrock Nova in real time. Verbal approval flows through the same GovernanceGate as any other approval method -- full audit trail preserved.
- **Fallback Safety:** The system is designed so that no single component failure can cause an incident to be dropped. Audio fails? Text fallback. Call fails? Slack escalation. Slack fails? Logged to DB and artifacts.
- **Ghost Mode:** The AI never auto-approves. Every remediation requires explicit human consent -- whether verbal on a phone call, a button click in Slack, or an API call from the dashboard.
