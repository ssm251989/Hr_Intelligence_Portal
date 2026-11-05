"""Prompt-registry evaluation fixtures (docs/HRMS_COMPLETE_SPEC.txt Part 12 D): before a
tenant publishes a prompt override, its draft version runs against the fixtures for that
key and each expectation is checked. Runs through the governed call, so evaluation spend
is metered and logged like any other AI use."""

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.intelligence import PromptEvalFixture
from app.models.prompt import PromptTemplate
from app.platform.ai import governance
from app.platform.tenancy.context import TenantContext


def check_expectations(output: str, expectations: dict) -> dict:
    lowered = output.lower()
    failures = []
    for phrase in expectations.get("must_include", []):
        if phrase.lower() not in lowered:
            failures.append(f"missing: {phrase}")
    for phrase in expectations.get("must_not_include", []):
        if phrase.lower() in lowered:
            failures.append(f"forbidden: {phrase}")
    if expectations.get("json_keys"):
        try:
            parsed = json.loads(output.strip().strip("`").removeprefix("json"))
            missing = [k for k in expectations["json_keys"] if k not in parsed]
            failures += [f"json key missing: {k}" for k in missing]
        except (ValueError, AttributeError):
            failures.append("output is not JSON")
    return {"passed": not failures, "failures": failures}


def run(db: Session, tenant: TenantContext, *, prompt_key: str, version: Optional[int] = None) -> dict:
    query = db.query(PromptTemplate).filter(PromptTemplate.tenant_id == tenant.tenant_id, PromptTemplate.key == prompt_key)
    prompt = (query.filter(PromptTemplate.version == version) if version else query.order_by(PromptTemplate.version.desc())).first()
    if prompt is None:
        raise KeyError(prompt_key)
    fixtures = db.query(PromptEvalFixture).filter(PromptEvalFixture.tenant_id == tenant.tenant_id, PromptEvalFixture.prompt_key == prompt_key).all()
    results = []
    for fixture in fixtures:
        try:
            output = governance.governed_complete(
                db, tenant, feature="platform.prompt_eval", purpose=prompt.purpose or "llm.judgment", system=prompt.system_prompt,
                messages=[{"role": "user", "content": fixture.input_text}], prompt_key=prompt.key, prompt_version=prompt.version,
                input_refs={"fixture_id": str(fixture.id)},
            ).text
            outcome = check_expectations(output, fixture.expectations_json or {})
        except Exception as exc:
            outcome = {"passed": False, "failures": [f"error: {type(exc).__name__}"]}
        fixture.last_result_json = {**outcome, "version": prompt.version}
        fixture.last_run_at = datetime.now(timezone.utc)
        results.append({"fixture": fixture.name, **outcome})
    db.commit()
    return {"prompt_key": prompt_key, "version": prompt.version, "passed": all(r["passed"] for r in results) if results else None, "results": results}
