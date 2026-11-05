"""Part 17.7: "Candidate emails" -- what each reply is about, in one line, and whether someone
still has to act on it.

topic   interview_time | documents | question | offer | withdrawal | other  (keyword rules)
summary one line: the AI (feature `recruitment.email_summary`, when AI is switched on) or,
        otherwise, the reply's first real sentence (quoted history and signatures removed).
status  needs_action (new) | done (someone pressed "Mark done").
"""

import re
from typing import Optional

from sqlalchemy.orm import Session

from app.models.hr_inbound_email import HrInboundEmail

_TOPIC_WORDS = (
    ("withdrawal", ("not interested", "withdraw", "no longer interested", "decline the", "accepted another", "not looking")),
    ("interview_time", ("interview", "slot", "reschedul", "available on", "availability", "time works", "am ", "pm ", "tomorrow", "monday",
                        "tuesday", "wednesday", "thursday", "friday", "saturday", "meeting link")),
    ("documents", ("attached", "attachment", "document", "pan card", "aadhaar", "certificate", "payslip", "relieving", "resume", "cv ")),
    ("offer", ("offer", "ctc", "salary", "joining date", "notice period", "package")),
    ("question", ("?", "could you", "can you", "please clarify", "query", "would like to know")),
)
_AUTOMATED = re.compile(r"(no-?reply|do-?not-?reply|mailer-daemon|postmaster|notifications?@|newsletter|marketing@|updates@|alerts?@|"
                        r"digest@|bounce|info@.*(google|linkedin|naukri|facebook)|@.*(mailchimp|sendgrid|amazonses))", re.I)
AUTOMATED_SUMMARY = "Automatic email - not from a candidate"
_QUOTE = re.compile(r"^(>|On .+wrote:|From: |Sent: |-{2,}\s*Original Message)", re.I)
_SIGN = re.compile(r"^(thanks|thank you|regards|best regards|warm regards|cheers|sincerely)[,!.\s]*$", re.I)
# "Hi," / "Hello Priya," / "Dear HR team," / "Good morning!" - and what follows it on the same line
_GREETING = re.compile(r"^(?:hi|hello|dear|good (?:morning|afternoon|evening))\b(?:[^,!.?]{0,25}[,!.])?\s*(?P<rest>.*)$", re.I)


def topic_of(subject: Optional[str], body: Optional[str]) -> str:
    text = f" {subject or ''} \n {body or ''} ".lower()
    for topic, words in _TOPIC_WORDS:
        if any(w in text for w in words):
            return topic
    return "other"


def first_sentence(subject: Optional[str], body: Optional[str], limit: int = 140) -> str:
    lines = []
    for raw in (body or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if _QUOTE.match(line):
            break  # everything below is the quoted earlier message
        if _SIGN.match(line):
            continue
        greet = _GREETING.match(line)
        if greet and len(line) < 40:
            # Part 23.3e: "Hello, can I reschedule my call?" was dropped whole as a greeting line, so the summary
            # became the sign-off ("Vikas"); only the greeting itself is dropped now
            rest = greet.group("rest").strip()
            if len(rest) < 12:
                continue
            line = rest[0].upper() + rest[1:]
        lines.append(line)
    text = re.sub(r"\s+", " ", " ".join(lines)).strip() or (subject or "").strip()
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    sentence = m.group(1) if m and len(m.group(1)) >= 12 else text
    return sentence[: limit - 1] + "…" if len(sentence) > limit else sentence


def _ai_summary(db: Session, tenant, email: HrInboundEmail) -> Optional[str]:
    from app.platform.ai.governance import AIDisabledError, feature_enabled, governed_complete

    if not feature_enabled(db, tenant, "recruitment.email_summary"):
        return None
    try:
        result = governed_complete(
            db, tenant, feature="recruitment.email_summary", purpose="llm.judgment",
            system="You summarise a candidate's email reply to a recruiter in ONE plain sentence of at most 20 words, "
                   "saying what they want or answered (e.g. 'Can do the interview on Tuesday after 3 pm.'). No greeting, no names. "
                   "If it is not a person's reply (newsletter, promotion, automatic notice), answer exactly NOT_CANDIDATE.",
            messages=[{"role": "user", "content": f"Subject: {email.subject or ''}\n\n{(email.body or '')[:4000]}"}],
            input_refs={"hr_inbound_email_id": str(email.id)}, max_tokens=80,
        )
    except (AIDisabledError, Exception):  # noqa: BLE001 -- no AI connection / budget: fall back to the text
        return None
    text = (result.text or "").strip().strip('"')
    if "NOT_CANDIDATE" in text.upper():
        return AUTOMATED_SUMMARY
    return text[:200] or None


def triage(db: Session, tenant, email: HrInboundEmail, *, use_ai: bool = True) -> HrInboundEmail:
    """Fill topic + summary if missing (idempotent). Automatic mail (no-reply senders,
    newsletters, bounces) is labelled as such and needs no action."""
    changed = False
    if _AUTOMATED.search(email.from_address or "") and email.topic != "automated":
        email.topic, email.summary, email.summary_source = "automated", AUTOMATED_SUMMARY, "text"
        if email.status != "done":
            email.status, email.done_by = "done", "automatic"
        db.commit()
        return email
    if not email.topic:
        email.topic = topic_of(email.subject, email.body)
        changed = True
    if not email.summary:
        ai = _ai_summary(db, tenant, email) if use_ai else None
        email.summary = ai or first_sentence(email.subject, email.body)
        email.summary_source = "ai" if ai else "text"
        if ai == AUTOMATED_SUMMARY:
            email.topic, email.status, email.done_by = "automated", "done", "automatic"
        changed = True
    if changed:
        db.commit()
    return email
