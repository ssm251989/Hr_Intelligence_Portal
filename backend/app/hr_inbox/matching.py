"""Part 22.2: which candidate an incoming email belongs to.

Rules, in order (the rule that linked it is saved on the email as `match_rule`):
1. the sender's address = the candidate's email, or one of the extra addresses on the profile (`alt_emails`)
2. the sender name / subject / body (signature, quoted reply) contains the candidate's "First Last" or
   "Last First" -- case-insensitive, ignoring dots and extra spaces, initials allowed ("G. Kishore", "Kishore G")
3. it is a reply to an email the app sent (In-Reply-To / References = a Message-ID we stored)

Exactly one candidate -> linked automatically. Several -> not linked; the candidates are kept as
suggestions for HR to pick from. The app never guesses between two.
"""

import re
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.candidate import Candidate

_NON_WORD = re.compile(r"[^\w@]+", re.UNICODE)


def normalise(text_value: Optional[str]) -> str:
    return " ".join(_NON_WORD.sub(" ", (text_value or "").lower().replace("_", " ")).split())


def name_variants(full_name: Optional[str]) -> set[str]:
    """ "Gunda Kishore" -> gunda kishore, kishore gunda, g kishore, kishore g, gunda k, k gunda (two-part names and up)."""
    toks = normalise(full_name).split()
    toks = [t for t in toks if "@" not in t]
    if len(toks) < 2:
        return set()  # a single name is too common to link on
    first, last = toks[0], toks[-1]
    out = {f"{first} {last}", f"{last} {first}", " ".join(toks), " ".join(reversed(toks))}
    if len(first) > 1 and len(last) > 1:
        out |= {f"{first[0]} {last}", f"{last} {first[0]}", f"{first} {last[0]}", f"{last[0]} {first}"}
    return out


def _ids(header: Optional[str]) -> list[str]:
    return re.findall(r"<[^<>\s]+>", header or "")


def _latest_application(db: Session, candidate_id) -> Optional[Application]:
    return db.query(Application).filter(Application.candidate_id == candidate_id).order_by(Application.created_at.desc()).first()


def by_email(db: Session, tenant_id, address: str) -> tuple[list, str]:
    address = (address or "").strip().lower()
    if not address:
        return [], ""
    direct = [c.id for c in db.query(Candidate.id).filter(Candidate.tenant_id == tenant_id, func.lower(Candidate.email) == address)]
    if direct:
        return direct, "email"
    alt = [c.id for c in db.query(Candidate.id).filter(Candidate.tenant_id == tenant_id, Candidate.alt_emails.op("@>")(f'["{address}"]'))]
    return alt, "alt_email"


def by_name(db: Session, tenant_id, *texts: Optional[str]) -> list:
    hay = f" {normalise(' '.join(t or '' for t in texts))} "
    if len(hay) < 4:
        return []
    found = []
    for cid, name in db.query(Candidate.id, Candidate.full_name).filter(Candidate.tenant_id == tenant_id, Candidate.full_name.isnot(None)):
        if any(f" {v} " in hay for v in name_variants(name)):
            found.append(cid)
    return found


def by_thread(db: Session, tenant_id, in_reply_to: Optional[str], references: Optional[str]) -> list:
    from app.models.comms import OutboundMessage

    ids = _ids(in_reply_to) + _ids(references)
    if not ids:
        return []
    found = set()
    for m in db.query(OutboundMessage).filter(OutboundMessage.tenant_id == tenant_id, OutboundMessage.provider_message_id.in_(ids)):
        if m.related_entity_type == "candidate" and m.related_entity_id:
            found.add(m.related_entity_id)
        elif m.related_entity_type == "application" and m.related_entity_id:
            a = db.get(Application, m.related_entity_id)
            if a is not None:
                found.add(a.candidate_id)
        else:
            for addr in m.to_addresses or []:
                found |= set(by_email(db, tenant_id, addr)[0])
    return list(found)


def match(db: Session, tenant_id, *, from_address: str, from_name: Optional[str] = None, subject: Optional[str] = None,
          body: Optional[str] = None, in_reply_to: Optional[str] = None, references: Optional[str] = None) -> dict:
    """{"candidate_id", "application_id", "rule", "suggestions": [candidate ids]}"""
    def linked(cid, rule):
        app = _latest_application(db, cid)
        return {"candidate_id": cid, "application_id": app.id if app else None, "rule": rule, "suggestions": []}

    emails, rule = by_email(db, tenant_id, from_address)
    if len(emails) == 1:
        return linked(emails[0], rule)
    if len(emails) > 1:
        return {"candidate_id": None, "application_id": None, "rule": None, "suggestions": emails}
    names = by_name(db, tenant_id, from_name, subject, (body or "")[:20000])
    thread = by_thread(db, tenant_id, in_reply_to, references)
    if len(names) == 1:
        return linked(names[0], "name")
    if len(names) > 1:
        both = [c for c in names if c in thread]
        if len(both) == 1:
            return linked(both[0], "thread")
        return {"candidate_id": None, "application_id": None, "rule": None, "suggestions": names}
    if len(thread) == 1:
        return linked(thread[0], "thread")
    return {"candidate_id": None, "application_id": None, "rule": None, "suggestions": thread}


def suggestion_rows(db: Session, ids: list) -> list[dict]:
    from app.models.job_role import JobRole

    out = []
    for cid in ids or []:
        c = db.get(Candidate, cid)
        if c is None:
            continue
        app = _latest_application(db, c.id)
        job = db.get(JobRole, app.job_role_id) if app else None
        out.append({"candidate_id": str(c.id), "application_id": str(app.id) if app else None, "name": c.full_name, "email": c.email,
                    "job_title": job.title if job else None})
    return out


def apply(db: Session, tenant_id, row) -> dict:
    """Runs the rules for one stored email (only if it isn't linked yet) and saves the result."""
    if row.matched_candidate_id is not None:
        return {"rule": row.match_rule or "email"}
    r = match(db, tenant_id, from_address=row.from_address, from_name=row.from_name, subject=row.subject, body=row.body,
              in_reply_to=row.in_reply_to, references=row.references_header)
    if r["candidate_id"]:
        row.matched_candidate_id, row.matched_application_id, row.match_rule = r["candidate_id"], r["application_id"], r["rule"]
        row.match_suggestions_json = None
    else:
        row.match_suggestions_json = [str(x) for x in r["suggestions"]] or None
    return r


def rematch_unmatched(db: Session, tenant, *, actor: str = "system") -> dict:
    """Run the rules once over every email that isn't linked yet."""
    from app.audit.service import log_action
    from app.models.hr_inbound_email import HrInboundEmail

    counts = {"checked": 0, "linked": 0, "ambiguous": 0, "by_rule": {}}
    for row in db.query(HrInboundEmail).filter(HrInboundEmail.tenant_id == tenant.tenant_id, HrInboundEmail.matched_candidate_id.is_(None)).all():
        counts["checked"] += 1
        r = apply(db, tenant.tenant_id, row)
        if r.get("candidate_id"):
            counts["linked"] += 1
            counts["by_rule"][r["rule"]] = counts["by_rule"].get(r["rule"], 0) + 1
            log_action(db, "candidate", r["candidate_id"], "inbound_email_linked", actor[:50],
                       {"hr_inbound_email_id": str(row.id), "rule": r["rule"], "subject": row.subject})
        elif r.get("suggestions"):
            counts["ambiguous"] += 1
    db.commit()
    log_action(db, "hr_inbox", None, "candidate_emails_rematched", actor[:50], counts)
    return counts
