"""CopilotService (docs/HRMS_COMPLETE_SPEC.txt Part 12 section B, named in this part's
CHECKS) -- the employee & HR assistant.

One question goes down exactly one path:
1. an ACTION intent ("raise a ticket", "request a laptop", "I need a letter") -> a
   `copilot_drafts` row the user must confirm; nothing is ever submitted silently;
2. a PERSONAL-DATA intent -> a permission-checked tool from tools.py (the caller's own data);
3. otherwise POLICY Q&A -> retrieval over the tenant's own documents, answered by the LLM
   ONLY from the retrieved passages with numbered citations. An answer with no valid
   citation is not shown (RAG citations are required); low retrieval confidence hands over
   to the helpdesk as a draft ticket instead of guessing.

Everything goes through `governance.governed_complete` (feature `copilot.chat`), so the
AI toggle, budget cutoff, PII redaction and decision log all apply.
"""

import re
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.copilot import retrieval, tools
from app.models.intelligence import CopilotConversation, CopilotDraft, CopilotMessage
from app.models.user import User
from app.platform.ai import governance
from app.platform.i18n.service import SUPPORTED_LOCALES, translate
from app.platform.iam.authz import has_permission
from app.platform.iam.org_scope import my_employee_id
from app.platform.iam.roles import role_names_for
from app.platform.settings.resolver import SettingContext, SettingsService
from app.platform.tenancy.context import TenantContext

_CITATION = re.compile(r"\[(\d+)\]")

# Action intents -> (draft action, phrases in en/hi/ta).
_ACTIONS = (
    ("raise_ticket", ("raise a ticket", "raise ticket", "open a ticket", "create a ticket", "log a ticket", "टिकट बनाओ", "டிக்கெட் உருவாக்கு")),
    ("request_asset", ("request a laptop", "need a laptop", "request an asset", "need a new", "लैपटॉप चाहिए", "மடிக்கணினி வேண்டும்")),
    ("request_letter", ("need a letter", "request a letter", "experience letter", "employment letter", "address proof letter", "पत्र चाहिए", "கடிதம் வேண்டும்")),
)


# Part 22.1: words that make even a one-word question clear enough to try ("salary?", "leave")
_TOPIC_WORDS = {
    "leave", "leaves", "holiday", "holidays", "salary", "payslip", "payslips", "pay", "notice", "resign", "resignation", "travel", "hotel",
    "probation", "confirmation", "wfh", "remote", "home", "policy", "policies", "handbook", "bonus", "reimbursement", "reimbursements",
    "insurance", "attendance", "hours", "timing", "posh", "grievance", "assets", "laptop", "jobs", "job", "candidates", "candidate",
    "interview", "interviews", "openings", "vacancies", "hiring", "offer", "joining", "exit", "relieving", "conduct", "security",
}


def is_unclear(question: str) -> bool:
    """Too short / not a question we can work with ("Eg1", "hi", "asdf") -> ask what they mean instead of
    searching the policies and offering a ticket for it."""
    q = question.strip().lower()
    if re.fullmatch(r"(e\.?g\.?|example|test|hi|hello|hey|ok|okay|yes|no|thanks|thank you)\s*\d*[.!?]*", q):
        return True
    if any(ord(ch) > 0x2FF for ch in q):  # Hindi / Tamil etc.: only reject near-empty text
        return len(re.sub(r"\s+", "", q)) < 3
    words = re.findall(r"[a-z]{2,}", q)
    if any(w in _TOPIC_WORDS for w in words):
        return False
    return len([w for w in words if len(w) >= 3]) < 2


class CopilotError(ValueError):
    pass


class CopilotService:
    def __init__(self, db: Session, tenant: TenantContext, user: User):
        self.db = db
        self.tenant = tenant
        self.user = user
        self._settings = SettingsService(db)
        self._ctx = SettingContext(tenant=tenant)

    def _t(self, language: str, key: str) -> str:
        return translate(self.db, self.tenant, language, key)

    def _role_names(self) -> list[str]:
        return role_names_for(self.db, self.tenant, self.user)

    def _conversation(self, conversation_id: Optional[UUID], language: str) -> CopilotConversation:
        if conversation_id is not None:
            conversation = self.db.query(CopilotConversation).filter(
                CopilotConversation.tenant_id == self.tenant.tenant_id, CopilotConversation.id == conversation_id, CopilotConversation.user_id == self.user.id,
            ).first()
            if conversation is None:
                raise CopilotError("conversation not found")
            return conversation
        conversation = CopilotConversation(tenant_id=self.tenant.tenant_id, user_id=self.user.id, language=language)
        self.db.add(conversation)
        self.db.commit()
        self.db.refresh(conversation)
        return conversation

    def _reply(self, conversation: CopilotConversation, content: str, **fields) -> dict:
        message = CopilotMessage(tenant_id=self.tenant.tenant_id, conversation_id=conversation.id, role="assistant", content=content, **fields)
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return {
            "conversation_id": str(conversation.id), "message_id": str(message.id), "answer": content,
            "citations": message.citations_json or [], "tool_calls": message.tool_calls_json or [],
            "confidence": float(message.confidence) if message.confidence is not None else None,
            "draft": None,
        }

    # ---- drafts ----

    def create_draft(self, action: str, payload: dict, conversation: Optional[CopilotConversation] = None) -> CopilotDraft:
        draft = CopilotDraft(tenant_id=self.tenant.tenant_id, user_id=self.user.id, conversation_id=conversation.id if conversation else None, action=action, payload_json=payload)
        self.db.add(draft)
        self.db.commit()
        self.db.refresh(draft)
        return draft

    def helpdesk_on(self) -> bool:
        from app.platform.modules import enabled_modules

        return "helpdesk" in enabled_modules(self.db, self.tenant)

    def ticket_categories(self) -> list[dict]:
        from app.models.metadata import MasterValue

        rows = (self.db.query(MasterValue).filter(MasterValue.tenant_id == self.tenant.tenant_id, MasterValue.type_code == "ticket_category",
                                                  MasterValue.is_active.is_(True)).order_by(MasterValue.code).all())
        return [{"code": r.code, "name": (r.label_i18n or {}).get("en") or r.code.replace("_", " ").title()} for r in rows if r.parent_id is None]

    def default_category(self) -> Optional[str]:
        """Part 22.1: the handover ticket's category is chosen automatically -- the configured one if it is
        an active category, else "general", else "other", else the first active one (the user can change it)."""
        codes = [c["code"] for c in self.ticket_categories()]
        wanted = self._settings.get("copilot.handover_category", self._ctx) or ""
        for code in (wanted, "general", "other", "policy"):
            if code and code in codes:
                return code
        return codes[0] if codes else None

    def _draft_payload(self, action: str, question: str) -> dict:
        category = self.default_category()
        if action == "request_asset":
            return {"category_code": None, "reason": question}
        if action == "request_letter":
            return {"category_code": category, "subject": "Letter request", "description": question}
        return {"category_code": category, "subject": question[:120], "description": question}

    def confirm_draft(self, draft_id: UUID, *, overrides: Optional[dict] = None) -> CopilotDraft:
        """The ONLY place a chat-proposed action is actually executed."""
        draft = self.db.query(CopilotDraft).filter(CopilotDraft.tenant_id == self.tenant.tenant_id, CopilotDraft.id == draft_id, CopilotDraft.user_id == self.user.id).first()
        if draft is None:
            raise CopilotError("draft not found")
        if draft.status != "draft":
            return draft
        payload = {**(draft.payload_json or {}), **(overrides or {})}
        employee_id = my_employee_id(self.db, self.tenant, self.user)
        try:
            if draft.action in ("raise_ticket", "request_letter"):
                if not has_permission(self.db, self.tenant, self.user, "helpdesk.self.create"):
                    raise tools.ToolPermissionError("helpdesk.self.create")
                from app.service_desk import tickets

                if not payload.get("category_code"):
                    payload["category_code"] = self.default_category()
                if not payload.get("category_code"):
                    raise CopilotError("No helpdesk categories are set up yet. Ask HR to add one in Settings > Helpdesk.")
                ticket = tickets.create_ticket(self.db, self.tenant, category_code=payload["category_code"], subject=payload.get("subject") or "Copilot request",
                                               description=payload.get("description"), channel="copilot", requester_employee_id=employee_id,
                                               requester_user_id=self.user.id, requester_email=self.user.email)
                draft.result_ref = f"ticket:{ticket.number}"
            elif draft.action == "hr_handover":  # Part 22.1: Helpdesk is off -> an HR to-do + an email to the HR mailbox
                draft.result_ref = self._hand_to_hr(payload)
            elif draft.action == "request_asset":
                if not has_permission(self.db, self.tenant, self.user, "assets.self.create"):
                    raise tools.ToolPermissionError("assets.self.create")
                if employee_id is None or not payload.get("category_code"):
                    raise CopilotError("choose an asset category before confirming")
                from app.service_desk import assets

                request = assets.request_asset(self.db, self.tenant, employee_id=employee_id, category_code=payload["category_code"], reason=payload.get("reason"),
                                               source="copilot", actor=self.user.email, actor_user_id=self.user.id)
                draft.result_ref = f"asset_request:{request.id}"
            draft.payload_json = payload
            draft.status = "confirmed"
        except (CopilotError, tools.ToolPermissionError):
            raise
        except Exception as exc:
            draft.status, draft.error = "failed", str(exc)
        self.db.commit()
        self.db.refresh(draft)
        return draft

    def _hand_to_hr(self, payload: dict) -> str:
        from app.agents.service import suggest
        from app.integrations.hr_email import get_hr_integration
        from app.platform.comms.defaults import send_default
        from app.platform.links import public_app_url

        who = self.user.full_name or self.user.email
        question = (payload.get("description") or payload.get("subject") or "").strip()
        # Part 23.3d: agent="copilot" broke the CHECK agent_suggestions_agent_check (only recruiter / onboarding /
        # helpdesk_triage / policy_checker), so every hand-over failed; a question routed to HR is helpdesk triage
        todo = suggest(self.db, self.tenant, agent="helpdesk_triage", kind="copilot_question", title=f"Question from {who}: {question[:90]}",
                       payload={"question": question, "user_email": self.user.email, "user_name": who}, reviewer_permission="core_hr.employee.edit")
        hr = get_hr_integration(self.db)
        to = hr.hr_module_email or hr.from_address or hr.smtp_username
        if to:
            try:
                send_default(self.db, self.tenant, "copilot.hr_handover", to=[to], purpose="email.outbound.hr_letters",
                             ctx={"user_name": who, "user_email": self.user.email, "question": question, "link": f"{public_app_url(self.db)}/approvals"},
                             related_entity_type="agent_suggestion", related_entity_id=todo.id)
            except Exception:  # noqa: BLE001 -- the to-do is the record; the email is a nudge
                pass
        return f"hr_todo:{todo.id}"

    def discard_draft(self, draft_id: UUID) -> None:
        draft = self.db.query(CopilotDraft).filter(CopilotDraft.tenant_id == self.tenant.tenant_id, CopilotDraft.id == draft_id, CopilotDraft.user_id == self.user.id).first()
        if draft is not None and draft.status == "draft":
            draft.status = "discarded"
            self.db.commit()

    # ---- main entry ----

    def ask(self, question: str, *, language: str = "en", conversation_id: Optional[UUID] = None) -> dict:
        question = (question or "").strip()
        if not question:
            raise CopilotError("ask a question")
        allowed_languages = [l for l in (self._settings.get("copilot.languages", self._ctx) or ["en"]) if l in SUPPORTED_LOCALES]
        language = language if language in allowed_languages else (allowed_languages[0] if allowed_languages else "en")
        if not governance.feature_enabled(self.db, self.tenant, "copilot.chat"):
            raise governance.AIDisabledError(self._t(language, "copilot.disabled"))

        conversation = self._conversation(conversation_id, language)
        self.db.add(CopilotMessage(tenant_id=self.tenant.tenant_id, conversation_id=conversation.id, role="user", content=question))
        self.db.commit()
        lowered = question.lower()

        # 0. Part 22.1: unclear text ("Eg1") -> ask what they mean, with suggestions; never a ticket
        if is_unclear(question):
            reply = self._reply(conversation, self._t(language, "copilot.clarify"), tool_calls_json=[{"clarify": True}])
            return {**reply, "clarify": True}

        # 1. actions -> draft
        for action, phrases in _ACTIONS:
            if any(p in lowered for p in phrases):
                if action in ("raise_ticket", "request_letter") and not self.helpdesk_on():
                    action = "hr_handover"  # Part 22.1: no Helpdesk -> the request goes to HR as a to-do
                payload = {"subject": question[:120], "description": question} if action == "hr_handover" else self._draft_payload(action, question)
                draft = self.create_draft(action, payload, conversation)
                reply = self._reply(conversation, self._t(language, "copilot.draft_ready"), tool_calls_json=[{"draft": action}])
                extra = {"categories": self.ticket_categories()} if action in ("raise_ticket", "request_letter") else {}
                return {**reply, "draft": {"id": str(draft.id), "action": action, "payload": draft.payload_json, **extra}}

        # 2. personal data -> tool (caller's permissions only)
        tool = tools.match_tool(question)
        if tool is not None:
            try:
                data = tools.run_tool(self.db, self.tenant, self.user, tool)
            except tools.ToolPermissionError:
                return self._reply(conversation, self._t(language, "copilot.no_permission"), tool_calls_json=[{"tool": tool.name, "denied": True}])
            if not any(data.values()) and tool.name not in ("open_jobs", "waiting_for_interview"):  # 22.1: "none waiting" is an answer
                return self._reply(conversation, self._t(language, "copilot.nothing_found"), tool_calls_json=[{"tool": tool.name}])
            answer = self._phrase_tool_answer(question, data, language)
            return self._reply(conversation, answer, tool_calls_json=[{"tool": tool.name, "result": data}])

        # 3. policy Q&A -> retrieval + cited answer, or handover
        hits = retrieval.search(self.db, self.tenant, question, role_names=self._role_names(), language=language)
        conf = retrieval.confidence(hits, question)
        if not hits or conf < float(self._settings.get("copilot.min_confidence", self._ctx)):
            return self._handover(conversation, question, language, conf)

        passages = "\n\n".join(f"[{i + 1}] {h.document_title}{' - ' + h.heading if h.heading else ''}\n{h.text}" for i, h in enumerate(hits))
        system = (
            "You are an HR assistant for one organisation. Answer ONLY from the numbered policy passages provided. "
            "Cite every claim with its passage number in square brackets, e.g. [1]. If the passages don't answer the question, "
            f"reply exactly NO_ANSWER. Answer in the language with code '{language}'. Be concise."
        )
        result = governance.governed_complete(
            self.db, self.tenant, feature="copilot.chat", purpose="llm.copilot", system=system,
            messages=[{"role": "user", "content": f"Passages:\n{passages}\n\nQuestion: {question}"}],
            input_refs={"conversation_id": str(conversation.id), "chunk_ids": [h.chunk_id for h in hits]}, actor_user_id=self.user.id,
        )
        cited = sorted({int(n) for n in _CITATION.findall(result.text) if 1 <= int(n) <= len(hits)})
        if "NO_ANSWER" in result.text or not cited:
            return self._handover(conversation, question, language, conf, decision_log_id=result.decision_log_id)
        citations = [{"n": n, "document_id": hits[n - 1].document_id, "title": hits[n - 1].document_title, "heading": hits[n - 1].heading,
                      "excerpt": hits[n - 1].text[:240]} for n in cited]
        return self._reply(conversation, result.text, citations_json=citations, confidence=conf, decision_log_id=result.decision_log_id)

    def _phrase_tool_answer(self, question: str, data: dict, language: str) -> str:
        """LLM phrasing when available; a plain structured summary otherwise (the data is
        already the caller's own, so no redaction concern, but it still goes through the
        governed call for the toggle/budget/log)."""
        try:
            return governance.governed_complete(
                self.db, self.tenant, feature="copilot.chat", purpose="llm.copilot",
                system=f"Summarise this data for the user in one or two sentences, in the language with code '{language}'. Use only the data.",
                messages=[{"role": "user", "content": f"Question: {question}\nData: {data}"}], actor_user_id=self.user.id,
            ).text
        except Exception:
            parts = []
            for key, rows in data.items():
                for row in rows:
                    parts.append(", ".join(f"{k}: {v}" for k, v in row.items() if v is not None))
            return "\n".join(parts)

    def _handover(self, conversation: CopilotConversation, question: str, language: str, conf: float, decision_log_id=None) -> dict:
        # Part 22.1: Helpdesk on -> a ticket draft (category chosen automatically, editable);
        # Helpdesk hidden -> "Hand over to HR" (an HR to-do + an email to the HR mailbox)
        cats = self.ticket_categories() if self.helpdesk_on() else []
        if cats and has_permission(self.db, self.tenant, self.user, "helpdesk.self.create"):
            action, payload, key, extra = "raise_ticket", self._draft_payload("raise_ticket", question), "copilot.handover", {"categories": cats}
        else:
            action, payload, key, extra = "hr_handover", {"subject": question[:120], "description": question}, "copilot.handover_hr", {}
        draft = self.create_draft(action, payload, conversation)
        reply = self._reply(conversation, self._t(language, key), confidence=conf, decision_log_id=decision_log_id,
                            tool_calls_json=[{"handover": True, "action": action}])
        return {**reply, "draft": {"id": str(draft.id), "action": action, "payload": draft.payload_json, **extra}, "handover": True}
