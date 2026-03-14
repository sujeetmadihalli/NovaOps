---
name: human-escalation
description: Determines when the agent should stop investigating and escalate to a human SRE. Used when confidence is low, domain is unknown, or destructive actions are needed.
---

# Human Escalation Skill

## When to Escalate

1. **Unknown domain**: Alert doesn't match any known skill
2. **Database operations**: Agent has no safe DB tools
3. **Security incidents**: Potential breach, unauthorized access
4. **Data corruption**: Risk of data loss
5. **Multi-region failures**: Blast radius too large
6. **Confidence < 0.5 after 3 loops**: Agent is going in circles
7. **Contradictory evidence**: Findings from analysts conflict

## How to Escalate

1. Write current findings to `plans/{id}/report.md` with status: ESCALATED
2. Include what was investigated and what remains unclear
3. Send Slack message with noop_require_human tool
4. Do NOT attempt remediation

## Escalation Message Format
Include:
- What was investigated (tools run, findings)
- What the top hypothesis is (even if uncertain)
- What specific information a human should look at
- Suggested next steps for the human
