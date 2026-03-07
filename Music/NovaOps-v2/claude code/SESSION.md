# NovaOps v2 - Session Log

## Session 1

- Created the v2 scaffold and core architecture plan.
- Chose Strands Agents SDK and a multi-agent SRE war room design.

## Session 2

- Built the initial agent graph, prompts, aggregators, API server, and evaluation harness.
- Added skills/playbooks across the incident domains.

## Session 3

- Hardened critic routing and Ghost Mode approval behavior.
- Added structured remediation planning and safer execution policy.
- Added tests for graph logic, execution, API flow, artifacts, and retrieval mode.

## Session 4

- Added typed schema parsing for agent outputs.
- Persisted structured output, validation summaries, and trace metadata.
- Exposed validation health through reports and API responses.
- Added hackathon-safe retrieval defaults and a guarded managed KB setup path.

## Current State

- Backend flow is stable enough for continued demo work.
- Offline mock mode now runs end-to-end without Bedrock access.
- Governance decisions, audit trails, and governance reports are part of the runtime flow.
- Remaining work is mostly dashboard polish, demo artifact refresh, and submission prep.

## Session 5

- Added governance policy engine, audit log, gate, and governance reports.
- Fixed governance execution bugs around payload normalization, deny handling, and duplicate execution.
- Added a fully offline mock graph path so `NOVAOPS_USE_MOCK=true` avoids live Bedrock calls.
- Added graceful runtime failure fallback with safe governance escalation.
- Tightened no-op governance so unknown alerts stay human-gated.
- Improved investigation and governance report readability for demo artifacts.
- Expanded tests to 45 passing in the repo virtual environment.
