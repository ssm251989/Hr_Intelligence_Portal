"""Fix 2026-10-04: sign the offer in the app when DocuSign isn't connected (or fails).

The offer email has a "Review & sign" link -> GET /offer/sign/<token>: the letter (and a PDF
download) -> the candidate types their full name and ticks "I accept" -> POST records the
signature (name, time, IP, browser), stamps the PDF ("Signed electronically by ... on ... from IP
...") and marks the offer signed.

on_offer_signed() is the ONE thing that happens after any signature (here, DocuSign, or HR marking
it signed): candidate -> Onboarding started, the hire's budget moves to committed, the recruiter is
told (in-app + email), and THEN the welcome email + welcome portal go out.
"""

import logging
import secrets
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.audit.service import log_action
from app.core.database import get_db
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.offer import Offer

log = logging.getLogger(__name__)
router = APIRouter(tags=["offer-esign"])
PDF_DIR = Path(__file__).resolve().parents[2] / "uploads" / "offers"


def ensure_token(offer: Offer) -> str:
    if not offer.sign_token:
        offer.sign_token = secrets.token_urlsafe(32)
    return offer.sign_token


def sign_url(db: Session, offer: Offer) -> str:
    from app.platform.links import public_base_url

    return f"{public_base_url(db)}/offer/sign/{ensure_token(offer)}"


def pdf_url(db: Session, offer: Offer) -> str:
    from app.platform.links import public_base_url

    return f"{public_base_url(db)}/offer/sign/{ensure_token(offer)}/letter.pdf"


def _letter_text(offer: Offer) -> str:
    from app.recruitment.offer_welcome import _text

    return _text(offer.offer_letter_text or "")


def _ist(dt: datetime) -> str:
    from app.integrations.google_calendar import format_ist_datetime

    return format_ist_datetime(dt)


def build_pdf(offer: Offer, company: str) -> bytes:
    """The letter as a PDF; once signed, with the signature stamp at the end."""
    from fpdf import FPDF

    def safe(s: str) -> str:  # core PDF fonts are Latin-1
        return (s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"') \
            .replace("–", "-").replace("—", "-").replace("₹", "Rs.").encode("latin-1", "replace").decode("latin-1")

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 10, safe(company or "Offer letter"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.ln(2)
    nl = {"new_x": "LMARGIN", "new_y": "NEXT"}  # back to the left margin after each block (else the next one has no width)
    pdf.multi_cell(0, 6, safe(_letter_text(offer)), **nl)
    if offer.signed_at:
        pdf.ln(6)
        pdf.set_draw_color(14, 124, 102)
        pdf.set_fill_color(226, 243, 238)
        pdf.set_font("Helvetica", "B", 11)
        pdf.multi_cell(0, 7, safe(f"Signed electronically by {offer.signed_name}"), border="LTR", fill=True, **nl)
        pdf.set_font("Helvetica", "", 10)
        how = {"in_app": "in the offer page", "docusign": "with DocuSign", "manual": "(recorded by HR)"}.get(offer.sign_method or "", "")
        pdf.multi_cell(0, 6, safe(f"On {_ist(offer.signed_at)} {how}" + (f" from IP {offer.signed_ip}" if offer.signed_ip else "")
                                  + f"\nReference: {offer.id}"), border="LBR", fill=True, **nl)
    return bytes(pdf.output())


def _company(db: Session, tenant) -> str:
    from app.platform.settings.resolver import SettingContext, SettingsService

    return SettingsService(db).get("org.display_name", SettingContext(tenant=tenant)) or ""


def _client_ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None))


# ---------------------------------------------------------------- after any signature

def on_offer_signed(db: Session, tenant, offer: Offer, *, method: str, actor: str) -> dict:
    """Idempotent. Candidate -> onboarding started, budget committed, recruiter told, then the welcome."""
    from app.models.audit_log import AuditLog

    application = db.get(Application, offer.application_id)
    if application is None:
        return {"skipped": "no application"}
    if db.query(AuditLog).filter(AuditLog.entity_id == application.id, AuditLog.action == "offer_signed_followup").first() is not None:
        return {"skipped": "already done"}
    offer.signed = True
    offer.onboarding_status = "in_progress"
    offer.sign_method = offer.sign_method or method
    offer.signed_at = offer.signed_at or datetime.now(timezone.utc)
    previous = application.status
    if application.status in ("offer_sent", "bgv_cleared"):
        application.status = "onboarding_started"
    db.commit()
    try:  # Part 18.15: the hire's money moves from "reserved" to "committed"
        from app.recruitment import budgets

        budgets.commit(db, tenant, offer.application_id)
    except Exception:  # noqa: BLE001
        pass
    told = _tell_recruiter(db, tenant, application, offer)
    from app.recruitment.offer_welcome import send_welcome

    welcome = send_welcome(db, tenant, application, offer)
    result = {"method": method, "previous_status": previous, "new_status": application.status, "recruiter_told": told, **welcome}
    log_action(db, "application", application.id, "offer_signed_followup", actor[:50], result)
    return result


def _tell_recruiter(db: Session, tenant, application: Application, offer: Offer) -> list[str]:
    from app.integrations.hr_email import SmtpError, get_hr_integration, is_smtp_configured, send_hr_email
    from app.models.comms import OutboundMessage
    from app.recruitment.scoring.autoshortlist import _recipients

    job = db.get(JobRole, application.job_role_id)
    cand = db.get(Candidate, application.candidate_id)
    name = (cand.full_name if cand else None) or "The candidate"
    to = _recipients(db, job, ["job_owner", "hiring_manager"]) if job else []
    subject = f"{name} signed the offer for {job.title if job else 'the role'} - joining {offer.joining_date.strftime('%d %b %Y') if offer.joining_date else ''}"
    for addr in to:
        db.add(OutboundMessage(tenant_id=tenant.tenant_id, channel="in_app", purpose="recruitment.offer_signed", to_addresses=[addr], subject=subject,
                               body_ref=f"/candidates/{application.id}", status="sent", related_entity_type="application", related_entity_id=application.id))
    db.commit()
    sent = []
    hr = get_hr_integration(db)
    if is_smtp_configured(hr):
        for addr in to:
            try:
                send_hr_email(hr, to=addr, subject=subject, body=f"{subject}.\n\nSigned on {_ist(offer.signed_at)}. The welcome email and portal have gone to the new joiner.\n")
                sent.append(addr)
            except SmtpError as exc:
                log.warning("offer-signed email to %s failed: %s", addr, exc)
    return sent


# ---------------------------------------------------------------- the candidate's page

def _portal_link(db: Session, offer: Offer) -> str:
    """The welcome portal for this offer, once the case exists (it is made right after signing)."""
    from app.models.onboarding import PreboardingCase
    from app.platform.links import public_app_url

    case = db.query(PreboardingCase).filter(PreboardingCase.offer_id == offer.id).first()
    return f"{public_app_url(db)}/welcome/{case.portal_token}" if case is not None and case.portal_token else ""


# a few seconds of confetti right after signing (skipped for people who turn motion off)
CONFETTI = """<canvas id="cf" aria-hidden="true" style="position:fixed;inset:0;pointer-events:none;width:100%;height:100%"></canvas>
<script>(function(){if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;var c=document.getElementById('cf'),x=c.getContext('2d');
c.width=innerWidth;c.height=innerHeight;var col=['#0E7C66','#F5B700','#FF6B5A','#4C6FFF','#2BB673'],p=[];
for(var i=0;i<160;i++)p.push({x:Math.random()*c.width,y:-20-Math.random()*c.height*.5,r:4+Math.random()*5,v:2+Math.random()*3,s:Math.random()*6.28,c:col[i%5]});
var t0=performance.now();(function f(t){x.clearRect(0,0,c.width,c.height);p.forEach(function(q){q.y+=q.v;q.s+=.1;x.fillStyle=q.c;
x.fillRect(q.x+Math.sin(q.s)*8,q.y,q.r,q.r*1.6)});if(t-t0<4500)requestAnimationFrame(f);else x.clearRect(0,0,c.width,c.height)})(t0)})();</script>"""


def _page(db: Session, tenant, offer: Optional[Offer], *, error: Optional[str] = None, notice: Optional[str] = None,
          just_signed: bool = False) -> str:
    from app.platform.comms.theme import get_theme_and_org_context

    ctx = get_theme_and_org_context(db, tenant)
    theme, org = ctx["theme"], ctx["org"]["display_name"] or ""
    brand = escape(theme.get("primary_color") or "#0E7C66")
    if offer is None:
        body = f"<h1>Link not recognized</h1><p>We can't find this offer. Please use the newest email from {escape(org)}, or contact HR.</p>"
    else:
        cand = db.get(Candidate, db.get(Application, offer.application_id).candidate_id)
        token = escape(offer.sign_token or "")
        letter = offer.offer_letter_text or ""  # server-rendered from the company's own template
        if offer.signed:
            portal = _portal_link(db, offer)
            body = (("<div style='font-size:44px'>&#127881;</div>" if just_signed else "")
                    + f"<h1>{'Welcome aboard!' if just_signed else 'Offer signed'}</h1><p>Thank you{(', ' + escape(offer.signed_name)) if offer.signed_name else ''}! "
                    f"You signed on {escape(_ist(offer.signed_at)) if offer.signed_at else 'file'}. Your welcome email with the next steps is on its way.</p>"
                    + (f'<p><a class="btn" href="{escape(portal)}">Open your welcome portal</a></p>' if portal else "")
                    + f'<p><a href="/offer/sign/{token}/letter.pdf">Download the signed offer (PDF)</a></p>'
                    f'<div class="letter">{letter}</div>'
                    + (CONFETTI if just_signed else ""))
        elif offer.expiry_date and offer.expiry_date < date.today():
            body = f"<h1>This offer has expired</h1><p>It was valid until {offer.expiry_date.strftime('%d %B %Y')}. Please contact HR at {escape(org)}.</p>"
        else:
            body = (f"<h1>Your offer letter</h1><p>Please read your offer below"
                    + (f" and sign by <strong>{offer.expiry_date.strftime('%d %B %Y')}</strong>" if offer.expiry_date else "") + ".</p>"
                    f'<p><a href="/offer/sign/{token}/letter.pdf">Download as PDF</a></p>'
                    f'<div class="letter">{letter}</div>'
                    + (f'<div class="alert err">{escape(error)}</div>' if error else "")
                    + f'''<form method="post" class="sign">
                      <h2>Sign your offer</h2>
                      <label>Type your full name<input name="full_name" autocomplete="name" required minlength="2" value="{escape((cand.full_name or '') if cand else '')}" /></label>
                      <label class="check"><input type="checkbox" name="accept" value="yes" required /> I have read this offer and I accept it.</label>
                      <button type="submit" class="btn">Sign offer</button>
                      <p class="small">Signing records your name, the time and your IP address on the letter.</p>
                    </form>''')
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Offer - {escape(org)}</title>
<style>
 body{{margin:0;font-family:{escape(theme.get('font_family') or 'system-ui, sans-serif')};background:#F2F6F9;color:#15211D}}
 header{{background:{brand};color:#fff;padding:16px 20px;font-weight:800;letter-spacing:.5px}}
 main{{max-width:760px;margin:24px auto;padding:0 16px}}
 .card{{background:#fff;border-radius:16px;padding:24px;box-shadow:0 2px 10px rgba(0,0,0,.06)}}
 .letter{{border:1px solid #E2E8E5;border-radius:12px;padding:18px;margin:16px 0;line-height:1.6}}
 .btn{{display:inline-block;background:{brand};color:#fff;border:0;border-radius:11px;padding:12px 20px;font-weight:700;text-decoration:none;cursor:pointer;font-size:15px}}
 form.sign{{border-top:1px solid #E2E8E5;margin-top:18px;padding-top:12px}} label{{display:block;margin:12px 0}}
 input[name=full_name]{{display:block;width:100%;box-sizing:border-box;margin-top:6px;padding:12px;border:1px solid #c8d3ce;border-radius:10px;font-size:16px}}
 .check{{display:flex;gap:10px;align-items:flex-start}} .small{{color:#5B6A65;font-size:13px}}
 .alert{{padding:12px;border-radius:10px;margin:12px 0}} .err{{background:#FDECE7;color:#8a2b17}}
</style></head><body><header>{escape(org.upper())}</header><main><div class="card">{body}</div></main></body></html>"""


def _offer_by_token(db: Session, token: str) -> Optional[Offer]:
    return db.query(Offer).filter(Offer.sign_token == token).first() if token else None


@router.get("/offer/sign/{token}", response_class=HTMLResponse)
def offer_page(token: str, db: Session = Depends(get_db)):
    from app.platform.tenancy.context import require_current_tenant

    offer = _offer_by_token(db, token)
    if offer is not None and offer.viewed_at is None:
        offer.viewed_at = datetime.now(timezone.utc)
        db.commit()
    return HTMLResponse(_page(db, require_current_tenant(), offer))


@router.post("/offer/sign/{token}", response_class=HTMLResponse)
def offer_sign(token: str, request: Request, full_name: str = Form(""), accept: str = Form(""), db: Session = Depends(get_db)):
    from app.platform.tenancy.context import require_current_tenant

    tenant = require_current_tenant()
    offer = _offer_by_token(db, token)
    if offer is None or offer.signed:
        return HTMLResponse(_page(db, tenant, offer))
    if offer.expiry_date and offer.expiry_date < date.today():
        return HTMLResponse(_page(db, tenant, offer))
    name = " ".join((full_name or "").split())
    if len(name) < 2:
        return HTMLResponse(_page(db, tenant, offer, error="Please type your full name to sign."))
    if accept != "yes":
        return HTMLResponse(_page(db, tenant, offer, error='Please tick "I have read this offer and I accept it."'))
    now = datetime.now(timezone.utc)
    offer.signed_name, offer.signed_at, offer.signed_ip = name, now, _client_ip(request)
    offer.signed_user_agent = (request.headers.get("user-agent") or "")[:400]
    offer.sign_method = "in_app"
    offer.signed = True
    db.commit()  # the signature is saved first; the stamped PDF must never block it
    try:
        PDF_DIR.mkdir(parents=True, exist_ok=True)
        path = PDF_DIR / f"{offer.id}-signed.pdf"
        path.write_bytes(build_pdf(offer, _company(db, tenant)))
        offer.signed_pdf_path = str(path)
        db.commit()
    except Exception:  # noqa: BLE001 -- the PDF link then builds it on demand
        db.rollback()
        log.exception("signed PDF failed for offer %s", offer.id)
    log_action(db, "application", offer.application_id, "offer_signed", "candidate",
               {"method": "in_app", "signed_name": name, "signed_at": now.isoformat(), "ip": offer.signed_ip})
    try:
        on_offer_signed(db, tenant, offer, method="in_app", actor="candidate")
    except Exception:  # noqa: BLE001 -- the signature is recorded either way
        log.exception("after-signing steps failed for offer %s", offer.id)
    return HTMLResponse(_page(db, tenant, offer, just_signed=True))


@router.get("/offer/sign/{token}/letter.pdf")
def offer_pdf(token: str, db: Session = Depends(get_db)):
    from app.platform.tenancy.context import require_current_tenant

    offer = _offer_by_token(db, token)
    if offer is None:
        return Response(status_code=404)
    if offer.signed and offer.signed_pdf_path and Path(offer.signed_pdf_path).exists():
        data = Path(offer.signed_pdf_path).read_bytes()
    else:
        data = build_pdf(offer, _company(db, require_current_tenant()))
    name = "offer-letter-signed.pdf" if offer.signed else "offer-letter.pdf"
    return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})
