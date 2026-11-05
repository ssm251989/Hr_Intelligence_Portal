"""Part 17.10: "Start from a ready-made template (optional)". A starting point for an industry:
suggested hiring stages, email wording, scoring rules, extra roles and a few settings.
Everything it adds can be changed later; applying one never deletes anything (the old
hiring pipeline stays, it just stops being the default; emails get a new published version,
the older versions stay in history; scoring rules get a new version).

    preview(key) -> what it will add (shown before Apply)
    apply(key)   -> does it, records `platform.setup.config_pack` = {"template": key, ...}
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.platform.tenancy.context import TenantContext

_ROLE_BASE = "Interviewer"  # extra roles start from this system role's permissions


def _stages(*names: tuple[str, str, str, int | None]) -> list[dict]:
    return [{"code": c, "name": n, "category": cat, "sla_days": sla} for (c, n, cat, sla) in names]


TEMPLATES: dict[str, dict] = {
    "it_services": {
        "name": "IT services",
        "line": "For software and IT services companies hiring engineers in volume.",
        "stages": _stages(("received", "Applied", "applied", 2), ("screened", "Screened by AI", "screening", 2),
                          ("hr_selected", "Shortlisted", "screening", 3), ("interview_scheduled", "Technical interview", "interview", 5),
                          ("interview_selected", "Passed interviews", "interview", 3), ("bgv_requested", "Background check", "assessment", 7),
                          ("offer_sent", "Offer sent", "offer", 5), ("onboarding_completed", "Joined", "hired", None)),
        "scoring_preset": "skills_first",
        "roles": [("Technical panel", "Interviewers who take technical rounds.")],
        "settings": {"recruitment.scoring.shortlist_threshold": 70, "recruitment.salary.approval_margin_pct": 10, "recruitment.salary.target_hike_pct": 25},
        "emails": {
            "recruitment.application.received": ("We've received your application for {{ job_title }}",
                                                 "Hi {{ candidate_first_name }},\n\nThanks for applying for {{ job_title }}. Our team reviews every application; "
                                                 "if your skills match, we'll email you about a technical interview within a week.\n\n{{ org.display_name }} Talent team"),
        },
    },
    "manufacturing": {
        "name": "Manufacturing",
        "line": "For plants and factories hiring shop-floor, technician and supervisor roles.",
        "stages": _stages(("received", "Applied", "applied", 2), ("screened", "Screened", "screening", 2),
                          ("hr_selected", "Shortlisted", "screening", 2), ("interview_scheduled", "Interview & trade test", "assessment", 5),
                          ("interview_selected", "Selected", "interview", 2), ("bgv_requested", "Medical & document check", "assessment", 7),
                          ("offer_sent", "Offer sent", "offer", 3), ("onboarding_completed", "Joined", "hired", None)),
        "scoring_preset": "location_first",
        "roles": [("Plant HR", "HR at a plant: sees the plant's hiring and joiners."), ("Shift supervisor panel", "Supervisors who take trade tests.")],
        "settings": {"recruitment.scoring.shortlist_threshold": 60, "recruitment.salary.approval_margin_pct": 5, "recruitment.salary.target_hike_pct": 15},
        "emails": {
            "recruitment.application.received": ("Application received: {{ job_title }}",
                                                 "Hello {{ candidate_first_name }},\n\nWe have received your application for {{ job_title }}. "
                                                 "If you are shortlisted, we will call you for an interview and trade test at the plant.\n\n{{ org.display_name }} HR"),
        },
    },
    "retail": {
        "name": "Retail",
        "line": "For stores and chains hiring store staff, cashiers and store managers quickly.",
        "stages": _stages(("received", "Applied", "applied", 1), ("screened", "Screened", "screening", 1),
                          ("hr_selected", "Shortlisted", "screening", 2), ("interview_scheduled", "Store interview", "interview", 3),
                          ("interview_selected", "Selected", "interview", 2), ("offer_sent", "Offer sent", "offer", 2),
                          ("onboarding_completed", "Joined", "hired", None)),
        "scoring_preset": "location_first",
        "roles": [("Store manager", "Store managers who interview and approve local hires.")],
        "settings": {"recruitment.scoring.shortlist_threshold": 55, "recruitment.salary.approval_margin_pct": 5, "recruitment.salary.target_hike_pct": 10,
                     "recruitment.shortlisting.auto_shortlist": True},
        "emails": {
            "recruitment.application.received": ("Thanks for applying to {{ org.display_name }}",
                                                 "Hi {{ candidate_first_name }},\n\nThanks for applying for {{ job_title }}. If you are a good fit, "
                                                 "the store team will call you in the next few days to fix a short interview.\n\n{{ org.display_name }}"),
        },
    },
}


def _sample(text: str) -> str:
    """Placeholders shown with example values ("{{ job_title }}" -> "Automation Architect")."""
    import re

    from app.platform.comms.catalog import VARIABLES

    return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", lambda m: VARIABLES.get(m.group(1), (m.group(1), m.group(1)))[1], text)


def _placeholders(text: str) -> list[str]:
    """Variables a template uses (org.* comes from the company, not the caller)."""
    import re

    return sorted({v for v in re.findall(r"\{\{\s*([\w.]+)\s*\}\}", text) if not v.startswith("org.")})


def listing() -> list[dict]:
    return [{"key": k, "name": t["name"], "line": t["line"]} for k, t in TEMPLATES.items()]


def preview(key: str) -> dict:
    from app.recruitment.scoring.factors import FACTORS
    from app.recruitment.scoring.rules import PRESET_NAMES, PRESETS

    t = TEMPLATES[key]
    rules = PRESETS[t["scoring_preset"]]
    weights = [f"{FACTORS[k][1]} {f['weight']}%" for k, f in rules["factors"].items() if f["enabled"]]
    names = {"recruitment.scoring.shortlist_threshold": "Shortlist threshold", "recruitment.salary.approval_margin_pct": "Salary approval margin (%)",
             "recruitment.salary.target_hike_pct": "Usual salary hike (%)", "recruitment.shortlisting.auto_shortlist": "Shortlist automatically"}
    return {
        "key": key, "name": t["name"], "line": t["line"],
        "adds": [
            {"what": "Hiring stages", "items": [s["name"] for s in t["stages"]]},
            {"what": "Scoring rules", "items": [f"Start from '{PRESET_NAMES[t['scoring_preset']]}': " + ", ".join(weights)]},
            {"what": "Email wording", "items": [f"'{_sample(subject)}'" for (subject, _b) in t["emails"].values()]},
            {"what": "Extra roles", "items": [f"{n} - {d}" for (n, d) in t["roles"]]},
            {"what": "Settings", "items": [f"{names.get(k, k)}: {'on' if v is True else v}" for k, v in t["settings"].items()]},
        ],
        "note": "Nothing is deleted: your current stages, emails and rules stay in history and you can change everything later.",
    }


def apply(db: Session, tenant: TenantContext, key: str, *, actor: str) -> dict:
    from app.models.iam import Role
    from app.models.pipeline import PipelineTemplate
    from app.platform.comms.templates import create_draft, publish
    from app.platform.settings.resolver import SettingsService
    from app.recruitment.pipeline import add_stage, create_template
    from app.recruitment.scoring.engine import save_rules
    from app.recruitment.scoring.rules import PRESETS

    t = TEMPLATES[key]
    done: dict[str, int] = {}
    # hiring stages: a new default pipeline (the old one is kept)
    pipe_name = f"{t['name']} hiring"
    if db.query(PipelineTemplate).filter(PipelineTemplate.tenant_id == tenant.tenant_id, PipelineTemplate.name == pipe_name).first() is None:
        pipe = create_template(db, tenant, name=pipe_name, is_default=True)
        for i, s in enumerate(t["stages"]):
            add_stage(db, tenant, template_id=pipe.id, code=s["code"], category=s["category"], order=i,
                      name_i18n={"en": s["name"]}, sla_days=s["sla_days"], candidate_visible_name=s["name"])
        done["stages"] = len(t["stages"])
    # scoring rules: a new company version
    save_rules(db, tenant, None, PRESETS[t["scoring_preset"]], actor=actor, note=f"From template: {t['name']}")
    done["scoring_rules"] = 1
    # email wording: a new published version per email
    for tkey, (subject, body) in t["emails"].items():
        draft = create_draft(db, tenant.tenant_id, key=tkey, channel="email", locale="en", subject_tpl=subject,
                             html_tpl="<p>" + body.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>", text_tpl=body,
                             variables_schema={"required": _placeholders(subject + body)})
        try:
            publish(db, draft, actor=actor)
            done["emails"] = done.get("emails", 0) + 1
        except Exception:  # noqa: BLE001 -- a wording problem leaves the draft for a person to fix
            done["email_drafts"] = done.get("email_drafts", 0) + 1
    # extra roles (start from the Interviewer permissions; admins widen them later)
    base = db.query(Role).filter(Role.tenant_id == tenant.tenant_id, Role.name == _ROLE_BASE, Role.is_system.is_(True)).first()
    for name, desc in t["roles"]:
        if db.query(Role).filter(Role.tenant_id == tenant.tenant_id, Role.name == name).first() is None:
            db.add(Role(tenant_id=tenant.tenant_id, name=name, description=desc, is_system=False, permissions=list(base.permissions) if base else []))
            done["roles"] = done.get("roles", 0) + 1
    db.commit()
    service = SettingsService(db)
    for skey, value in t["settings"].items():
        service.set(skey, value, scope_type="tenant", scope_id=None, actor=actor, tenant=tenant)
    done["settings"] = len(t["settings"])
    service.set("platform.setup.config_pack", {"template": key, "name": t["name"], "applied_at": datetime.now(timezone.utc).isoformat()},
                scope_type="tenant", scope_id=None, actor=actor, tenant=tenant)
    return {"template": key, "name": t["name"], "added": done}
