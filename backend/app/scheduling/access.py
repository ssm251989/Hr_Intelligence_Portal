"""Part 20.4: what an interviewer may open. Hiring staff (recruitment.candidate.view) see everything as before;
anyone else sees a candidate / scorecard / AI questions only for interviews assigned to them (by user id or
by the interviewer email the scheduling flow records)."""

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.interview import Interview
from app.models.user import User

STAFF_ROLES = ("admin", "recruiter", "hiring_manager")


def is_hiring_staff(db: Session, user: User) -> bool:
    from app.platform.iam.authz import has_permission
    from app.platform.tenancy.context import get_current_tenant

    if getattr(user, "role", None) in STAFF_ROLES:
        return True
    tenant = get_current_tenant()
    return bool(tenant is not None and has_permission(db, tenant, user, "recruitment.candidate.view"))


def _emails(db: Session, user: User) -> set[str]:
    from app.models.core_hr import Employee

    out = {user.email.strip().lower()} if user.email else set()
    e = db.query(Employee).filter(Employee.user_id == user.id).first()
    if e is not None:
        out |= {a.strip().lower() for a in (e.company_email, e.personal_email) if a}
    return out


def mine_filter(db: Session, user: User):
    conds = [Interview.interviewer_id == user.id]
    emails = _emails(db, user)
    if emails:
        conds.append(func.lower(Interview.interviewer_email).in_(list(emails)))
    return or_(*conds)


def is_assigned_interview(db: Session, user: User, interview: Interview) -> bool:
    if interview.interviewer_id == user.id:
        return True
    return bool(interview.interviewer_email and interview.interviewer_email.strip().lower() in _emails(db, user))


def assigned_to_application(db: Session, user: User, application_id) -> bool:
    return db.query(Interview.id).filter(Interview.application_id == application_id, mine_filter(db, user)).first() is not None


def assigned_to_candidate(db: Session, user: User, candidate_id) -> bool:
    from app.models.application import Application

    return (db.query(Interview.id).join(Application, Application.id == Interview.application_id)
            .filter(Application.candidate_id == candidate_id, mine_filter(db, user)).first() is not None)


def require_staff(db: Session, user: User) -> None:
    if not is_hiring_staff(db, user):
        raise HTTPException(status_code=403, detail="Only the hiring team can see this. Interviewers see their own interviews under My interviews.")


def require_staff_or_candidate(db: Session, user: User, candidate_id) -> None:
    if not (is_hiring_staff(db, user) or assigned_to_candidate(db, user, candidate_id)):
        raise HTTPException(status_code=404, detail="Candidate not found")


def require_staff_or_application(db: Session, user: User, application_id) -> None:
    if not (is_hiring_staff(db, user) or assigned_to_application(db, user, application_id)):
        raise HTTPException(status_code=404, detail="Application not found")


def require_staff_or_interview(db: Session, user: User, interview: Optional[Interview]) -> None:
    if interview is None or not (is_hiring_staff(db, user) or is_assigned_interview(db, user, interview)):
        raise HTTPException(status_code=404, detail="Interview not found")
