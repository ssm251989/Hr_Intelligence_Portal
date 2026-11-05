"""The HR agent team as a LangGraph graph.

Nodes: `hr_assistant` (supervisor) + one node per specialist (agents.AGENTS).
Edges are dynamic: a node returns `Command(goto=<next node>)`.

- The HR assistant hands a task to a specialist with `transfer_to_<agent>`.
- A specialist works through its own tools (a short tool-use loop), then either hands the
  next part to another specialist (agent-to-agent, `transfer_to_<agent>`) or reports back to
  the HR assistant.
- Every hand-off and report is an A2A-style message in `trace`:
  {"id", "from", "to", "kind": "task" | "result", "text", "data", "at"}.
- The HR assistant ends the run by answering the person.

Limits keep a run short and cheap: at most MAX_HOPS specialist turns per request and
MAX_STEPS model calls per specialist turn.
"""

import json
import operator
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.hr_agents.agents import AGENTS, SUPERVISOR, AgentSpec, tool_schemas
from app.hr_agents.tools import AgentContext, run_tool

MAX_HOPS = 6
MAX_STEPS = 6
PURPOSE = "llm.copilot"


class TeamState(TypedDict, total=False):
    request: str
    supervisor_messages: list  # the HR assistant's own conversation (Anthropic message format)
    pending_tool_use_id: Optional[str]  # the HR assistant's open transfer, answered by the report
    pending_skipped: list  # other transfers in the same turn (answered "not started")
    task: dict  # the A2A task the active specialist is working on
    chain: list  # reports from specialists in the current hand-off chain
    trace: Annotated[list, operator.add]
    hops: int
    final: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def a2a(sender: str, to: str, kind: str, text: str, data: Optional[dict] = None) -> dict:
    return {"id": str(uuid.uuid4()), "from": sender, "to": to, "kind": kind, "text": (text or "")[:2000], "data": data or {}, "at": _now()}


def _ctx(config) -> AgentContext:
    return config["configurable"]["ctx"]


def _call(ctx: AgentContext, spec: AgentSpec, messages: list, *, with_tools: bool = True) -> dict:
    from app.platform.ai import gateway

    kwargs: dict[str, Any] = {"max_tokens": 1500, "_feature": spec.feature}
    tools = tool_schemas(spec) if with_tools else []
    if tools:
        kwargs["tools"] = tools
    system = (AGENTS[spec.name].instructions if spec.name == SUPERVISOR else f"{_common()}\n\n{spec.instructions}")
    return gateway.complete(ctx.db, ctx.tenant, purpose=PURPOSE, system=system, messages=messages, **kwargs)


def _common() -> str:
    from app.hr_agents.agents import _COMMON

    return _COMMON


def _blocks(result: dict) -> list[dict]:
    content = result.get("content") if isinstance(result, dict) else None
    return [b for b in (content or []) if isinstance(b, dict)]


def _text(blocks: list[dict]) -> str:
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()


def _assistant_turn(blocks: list[dict]) -> dict:
    keep = []
    for b in blocks:
        if b.get("type") == "text" and b.get("text"):
            keep.append({"type": "text", "text": b["text"]})
        elif b.get("type") == "tool_use":
            keep.append({"type": "tool_use", "id": b["id"], "name": b["name"], "input": b.get("input") or {}})
    return {"role": "assistant", "content": keep}


def _enabled(ctx: AgentContext, name: str) -> bool:
    from app.platform.ai import governance

    return governance.feature_enabled(ctx.db, ctx.tenant, AGENTS[name].feature)


# ------------------------------------------------------------------ nodes


def hr_assistant(state: TeamState, config) -> Command:
    ctx = _ctx(config)
    spec = AGENTS[SUPERVISOR]
    messages = list(state.get("supervisor_messages") or [])
    if not messages:
        messages = [{"role": "user", "content": state["request"]}]
    pending = state.get("pending_tool_use_id")
    if pending:  # a specialist chain just reported back to the transfer that started it
        reports = state.get("chain") or []
        report = "\n\n".join(f"Report from the {AGENTS[r['agent']].title}:\n{r['text']}" for r in reports) or "No report."
        results = [{"type": "tool_result", "tool_use_id": pending, "content": report}]
        results += [{"type": "tool_result", "tool_use_id": i, "content": "Not started: hand over one task at a time."} for i in state.get("pending_skipped") or []]
        messages.append({"role": "user", "content": results})

    hops = int(state.get("hops") or 0)
    result = _call(ctx, spec, messages, with_tools=hops < MAX_HOPS)
    blocks = _blocks(result)
    transfers = [b for b in blocks if b.get("type") == "tool_use"]
    if not transfers:
        final = _text(blocks) or "Done."
        return Command(goto=END, update={"final": final, "pending_tool_use_id": None, "pending_skipped": []})

    messages.append(_assistant_turn(blocks))
    first, skipped = transfers[0], [b["id"] for b in transfers[1:]]
    target = str(first.get("name", "")).removeprefix("transfer_to_")
    task_text = (first.get("input") or {}).get("task") or state["request"]
    if target not in AGENTS or target == SUPERVISOR or not _enabled(ctx, target):
        results = [{"type": "tool_result", "tool_use_id": first["id"], "content": f"The {target} agent is not available (switched off)."}]
        results += [{"type": "tool_result", "tool_use_id": i, "content": "Not started."} for i in skipped]
        messages.append({"role": "user", "content": results})
        return Command(goto=SUPERVISOR, update={"supervisor_messages": messages, "pending_tool_use_id": None, "pending_skipped": [], "hops": hops + 1})
    msg = a2a(SUPERVISOR, target, "task", task_text)
    return Command(goto=target, update={"supervisor_messages": messages, "pending_tool_use_id": first["id"], "pending_skipped": skipped,
                                        "task": msg, "chain": [], "trace": [msg]})


def _specialist(name: str):
    spec = AGENTS[name]

    def node(state: TeamState, config) -> Command:
        ctx = _ctx(config)
        task = state.get("task") or {}
        hops = int(state.get("hops") or 0) + 1
        sender = AGENTS[task.get("from", SUPERVISOR)].title if task.get("from") in AGENTS else "HR assistant"
        context = ""
        if task.get("data"):
            context = f"\n\nContext from {sender}: {json.dumps(task['data'], default=str)[:1500]}"
        messages: list = [{"role": "user", "content": f"Task from the {sender}: {task.get('text', '')}{context}\n\nOriginal request from the person: {state.get('request', '')}"}]
        actions: list = []
        trace_add: list = []
        for _step in range(MAX_STEPS):
            result = _call(ctx, spec, messages)
            blocks = _blocks(result)
            messages.append(_assistant_turn(blocks))
            uses = [b for b in blocks if b.get("type") == "tool_use"]
            if not uses:
                report = _text(blocks) or "Done."
                break
            transfer = next((b for b in uses if str(b.get("name", "")).startswith("transfer_to_")), None)
            if transfer is not None and hops < MAX_HOPS:
                target = transfer["name"].removeprefix("transfer_to_")
                if target in spec.hands_off_to and _enabled(ctx, target):
                    handover = (transfer.get("input") or {}).get("task") or ""
                    done_text = _text(blocks) or f"Handed the next part to the {AGENTS[target].title}."
                    trace_add.append(a2a(name, SUPERVISOR, "result", done_text, {"actions": actions}))
                    nxt = a2a(name, target, "task", handover, {"from_agent_actions": actions})
                    trace_add.append(nxt)
                    chain = list(state.get("chain") or []) + [{"agent": name, "text": f"{done_text}\n(Handed to the {AGENTS[target].title}: {handover})"}]
                    return Command(goto=target, update={"task": nxt, "chain": chain, "trace": trace_add, "hops": hops})
            tool_results = []
            for b in uses:
                if str(b.get("name", "")).startswith("transfer_to_"):
                    out = {"error": "That hand-over is not available now; finish your part and report."}
                else:
                    tool = next((t for t in spec.tools if t.name == b.get("name")), None)
                    out = run_tool(ctx, tool, b.get("input") or {}) if tool else {"error": f"unknown tool {b.get('name')}"}
                    actions.append({"tool": b.get("name"), "input": b.get("input") or {}, "ok": "error" not in out,
                                    **({"error": out["error"]} if "error" in out else {})})
                tool_results.append({"type": "tool_result", "tool_use_id": b["id"], "content": json.dumps(out, default=str)[:6000]})
            messages.append({"role": "user", "content": tool_results})
        else:
            report = "I stopped after the step limit; here is what I did so far: " + json.dumps(actions, default=str)[:800]
        trace_add.append(a2a(name, SUPERVISOR, "result", report, {"actions": actions}))
        chain = list(state.get("chain") or []) + [{"agent": name, "text": report}]
        return Command(goto=SUPERVISOR, update={"chain": chain, "trace": trace_add, "hops": hops})

    node.__name__ = name
    return node


_GRAPH = None


def build_graph():
    global _GRAPH
    if _GRAPH is None:
        g = StateGraph(TeamState)
        g.add_node(SUPERVISOR, hr_assistant)
        for name in AGENTS:
            if name != SUPERVISOR:
                g.add_node(name, _specialist(name))
        g.add_edge(START, SUPERVISOR)
        _GRAPH = g.compile()
    return _GRAPH


def run_team(ctx: AgentContext, request: str) -> dict:
    """One request through the team. Returns the answer for the person + the agent trace."""
    state = build_graph().invoke({"request": request, "trace": [], "hops": 0}, config={"configurable": {"ctx": ctx}, "recursion_limit": 40})
    trace = state.get("trace") or []
    used = []
    for m in trace:
        for who in (m["from"], m["to"]):
            if who != SUPERVISOR and who not in used:
                used.append(who)
    return {"answer": state.get("final") or "Done.", "trace": trace, "agents_used": [{"name": n, "title": AGENTS[n].title} for n in used],
            "suggestions": ctx.suggestions, "links": ctx.links}
