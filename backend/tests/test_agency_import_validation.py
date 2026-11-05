"""Part 23.3b: the agency Excel import refused nothing - an unknown type became "Recruitment" and a bad
email was stored. Unknown types and bad emails are now reported per row; good rows are still imported."""
import io
import uuid

from openpyxl import Workbook

COLUMNS = ["Name", "Type (Recruitment / BGV / Both)", "Contact person", "Email", "Phone", "Address", "GST / PAN", "Contract start (YYYY-MM-DD)",
           "Contract end (YYYY-MM-DD)", "Fee type (percent / fixed)", "Fee value", "Payment terms", "BGV checks (check:price; ...)",
           "Turnaround days", "Report format", "Notes"]


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(COLUMNS)
    for r in rows:
        ws.append(r + [""] * (16 - len(r)))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _import(client, rows):
    r = client.post("/api/v1/agencies/import", files={"file": ("a.xlsx", _xlsx(rows), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    return {x["name"]: x for x in r.json()["results"]}


def test_import_reads_type_words(client):
    tag = uuid.uuid4().hex[:6]
    good, both = f"Imp {tag} good", f"Imp {tag} both"
    res = _import(client, [
        [good, "", "", f"Ops-{tag}@Agency.example"],
        [both, "Recruitment + BGV", "", "", "", "", "", "", "", "", "", "", "education:700"],
    ])
    assert res[good]["result"] == "created" and res[both]["result"] == "created"
    names = {a["name"]: a for a in client.get("/api/v1/agencies").json()}
    assert names[good]["agency_type"] == "recruitment"  # blank type = Recruitment
    assert names[good]["contact_email"] == f"ops-{tag}@agency.example"
    assert names[both]["agency_type"] == "both"


def test_import_row_checks_refuse_unknown_type_and_bad_email():
    # (a refused row rolls the request's session back, which in this test set-up would also roll back the
    # test's own transaction - so the row checks the import runs are tested directly)
    import pytest
    from fastapi import HTTPException

    from app.models.agency import RecruitmentAgency
    from app.recruitment.agency_router import _TYPE_WORDS, _apply_fields, _clean_email

    def row_type(word):
        return _TYPE_WORDS.get(" ".join(word.lower().split()), word)

    assert row_type("") == "recruitment" and row_type(" BGV ") == "bgv" and row_type("Recruitment  +  BGV") == "both"
    with pytest.raises(HTTPException) as exc:
        _apply_fields(RecruitmentAgency(name="x"), {"agency_type": row_type("Payroll")})
    assert "Type must be" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        _clean_email("not-an-email")
    assert "doesn't look right" in exc.value.detail
    assert _clean_email("") is None


def test_create_and_edit_refuse_a_bad_email(client):
    r = client.post("/api/v1/agencies", json={"name": f"Bad mail {uuid.uuid4().hex[:6]}", "contact_email": "nope"})
    assert r.status_code == 400 and "doesn't look right" in r.json()["detail"]
    ok = client.post("/api/v1/agencies", json={"name": f"Good mail {uuid.uuid4().hex[:6]}", "contact_email": " Desk@Agency.Example "})
    assert ok.status_code == 201 and ok.json()["contact_email"] == "desk@agency.example"
    r = client.patch(f"/api/v1/agencies/{ok.json()['id']}", json={"contact_email": "still wrong"})
    assert r.status_code == 400
