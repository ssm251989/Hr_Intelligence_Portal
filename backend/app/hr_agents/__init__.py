"""HR agent team (HR Agent Platform): the HR assistant works WITH nine specialist agents, end to end.

    HR Assistant (supervisor) --task--> any agent; every agent reports back (result)

    Job -> Screening -> Interview -> Salary -> Documents & BGV -> Offer -> Onboarding
    Exit (resignations, clearance, letters)        HR policy (handbook, with sources)

- Built on LangGraph (graph.py): one node per agent; an agent hands work to another agent
  with a `transfer_to_<agent>` tool, which becomes a LangGraph `Command(goto=...)`.
- Every hand-off is an agent-to-agent message in the A2A shape
  ({id, from, to, kind: task|result, text, data, at}), kept in the conversation's trace
  (copilot_messages.tool_calls_json) so HR can see who did what.
- Agents act only through their own tools (tools.py, tools_e2e.py), each checked against the asking
  user's permissions. Anything that changes a person's outcome (shortlist, salary decision,
  documents approval, BGV vendor / result, joining dates, joined, exit letters) becomes an
  approval card in My approvals (approvals.py runs the screen's own code on approval) --
  an agent never decides for a person.
- The automatic agents (HR Autopilot, autopilot/) work without anyone asking: woken by events and
  schedules, routine work automatic, decisions only inside company rules (docs/HR_AUTOPILOT.md).
- Every model call goes through the AI gateway (platform/ai/gateway.py), so the provider
  switch (Anthropic / Amazon Bedrock), usage limits and the per-feature cost metering apply.
"""
