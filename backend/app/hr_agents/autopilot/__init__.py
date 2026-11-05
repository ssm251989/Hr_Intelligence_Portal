"""HR Autopilot (Part 26): automatic agents that work without anyone asking.

The agent team (app/hr_agents) answers people in the HR assistant. The autopilot agents run on
their own, woken in two ways:

- EVENTS: every minute `runner.run_events` reads what happened since last time from the audit
  log (application created, salary checked, documents submitted, BGV report received, BGV
  passed ...) and hands each event to the agent that owns it. The audit log is the event
  outbox, so nothing in the hot paths changed and nothing is lost when a worker restarts.
- SCHEDULE: sweeps (`runner.SWEEPS`) catch what no event announces -- stuck candidates,
  joining days, exits, the morning briefing, sourcing for thin jobs.

What an agent may do (owner decision 2026-11-02, "auto within rules"):
- ROUTINE work runs automatically (screening, reminders, re-sends, escalations, briefings).
- DECISIONS about a person happen automatically ONLY when the company switched on the rule
  for it (settings `autopilot.rules.*`, all off by default) and the case is inside the rule;
  otherwise the agent raises the same approval card the HR assistant team uses (approvals.py).
- Every step is written to `agent_activity` (Autopilot page) with the rule that allowed it.

Master switch `autopilot.enabled` (off by default) + one switch per agent.
"""
