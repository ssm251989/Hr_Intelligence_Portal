"""Fix 2026-10-05: Settings > Company > Policies & handbook + configuration-health links."""

import io

import pytest

from app.copilot import policies, retrieval
from app.experience import config_health
from app.models.intelligence import KnowledgeChunk, KnowledgeDocument
from app.platform.tenancy.context import get_current_tenant


@pytest.fixture(autouse=True)
def _no_existing_policies(db_session):
    """Tests share the database with tenant 1's real data; hide its policies inside this
    test's own (rolled-back) transaction so counts start from zero."""
    db_session.query(KnowledgeDocument).filter(KnowledgeDocument.status.in_(("active", "processing", "failed"))).update(
        {"status": "retired"}, synchronize_session=False)
    db_session.commit()


@pytest.fixture
def assistant(monkeypatch):
    """The HR assistant switched on (module + AI feature); returns a switch to turn it off."""
    state = {"on": True}
    import app.platform.ai.governance as governance
    import app.platform.modules as modules

    real_modules = modules.enabled_modules
    monkeypatch.setattr(modules, "enabled_modules", lambda db, t: (real_modules(db, t) | {"copilot"}) if state["on"] else real_modules(db, t) - {"copilot"})
    real_feature = governance.feature_enabled
    monkeypatch.setattr(governance, "feature_enabled", lambda db, t, f: state["on"] if f == "copilot.chat" else real_feature(db, t, f))
    return state


def _codes(db):
    return {i["code"]: i for i in config_health.check(db, get_current_tenant())["issues"]}


def _upload(db, data=None, name="handbook.docx", **kw):
    return policies.upload(db, get_current_tenant(), data=data or policies.sample_docx(), filename=name, title=kw.pop("title", "Employee handbook"),
                           category=kw.pop("category", "leave"), version=kw.pop("version", "1.0"), effective_date=None, actor="hr@example.com", **kw)


def test_health_item_opens_policies_page_and_clears_when_ready(db_session, assistant):
    item = _codes(db_session)["COPILOT_NO_KNOWLEDGE"]
    assert item["fix_path"] == "/settings/company/policies" and item["action_label"] == "Upload policies"
    doc = _upload(db_session)
    assert doc.status == "processing" and "COPILOT_NO_KNOWLEDGE" in _codes(db_session)  # not Ready yet -> still shown
    policies.process(db_session, get_current_tenant(), doc.id)
    assert doc.status == "active" and doc.error is None
    assert "COPILOT_NO_KNOWLEDGE" not in _codes(db_session)
    hits = retrieval.search(db_session, get_current_tenant(), "how many days of annual leave", role_names=[])
    assert hits and hits[0].document_title == "Employee handbook" and hits[0].heading == "Leave policy"
    assert "18 days" in hits[0].text


def test_health_item_hidden_when_assistant_off(db_session, assistant):
    assistant["on"] = False
    assert "COPILOT_NO_KNOWLEDGE" not in _codes(db_session)


def test_scanned_or_broken_file_fails_with_reason(db_session):
    from pypdf import PdfWriter

    buf = io.BytesIO()
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.write(buf)
    doc = _upload(db_session, buf.getvalue(), name="scan.pdf")
    policies.process(db_session, get_current_tenant(), doc.id)
    assert doc.status == "failed" and "scanned" in doc.error
    bad = _upload(db_session, b"%PDF-1.4 not really", name="broken.pdf")
    policies.process(db_session, get_current_tenant(), bad.id)
    assert bad.status == "failed" and "couldn't be opened" in bad.error
    with pytest.raises(policies.PolicyError, match="PDF or Word"):
        _upload(db_session, b"hello", name="notes.txt")


def test_new_version_replaces_only_once_ready(db_session):
    t = get_current_tenant()
    v1 = _upload(db_session)
    policies.process(db_session, t, v1.id)
    v2 = _upload(db_session, version="2.0", replaces=v1)
    assert v1.status == "active"  # the old one keeps answering while the new one is read
    policies.process(db_session, t, v2.id)
    assert v1.status == "retired" and v2.status == "active"
    assert db_session.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == v1.id).count() == 0
    rows = policies.listing(db_session, t)
    assert [r["version"] for r in rows] == ["2.0"] and rows[0]["older_versions"][0]["version"] == "1.0"
    policies.delete(db_session, t, v2, actor="hr")
    assert v2.status == "deleted" and v1.status == "deleted" and policies.listing(db_session, t) == []
    assert db_session.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == v2.id).count() == 0


def test_api_upload_list_preview_delete(client, db_session):
    r = client.post("/api/v1/ui/policies", data={"title": "Leave policy", "category": "leave", "version": "3"},
                    files={"file": ("leave.docx", policies.sample_docx(), policies.TYPES["docx"])})
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]
    policies.process(db_session, get_current_tenant(), doc_id)  # the background task runs on its own session
    listing = client.get("/api/v1/ui/policies").json()
    row = next(p for p in listing["policies"] if p["id"] == doc_id)
    assert row["status"] == "ready" and row["category"] == "leave" and listing["ready"] >= 1
    assert client.get(f"/api/v1/ui/policies/{doc_id}/file").content[:2] == b"PK"
    assert any(p["heading"] == "Leave policy" for p in client.get(f"/api/v1/ui/policies/{doc_id}/text").json()["passages"])
    assert client.get("/api/v1/ui/policies/sample").status_code == 200
    assert client.post("/api/v1/ui/policies", files={"file": ("x.txt", b"hi", "text/plain")}).status_code == 400
    assert client.delete(f"/api/v1/ui/policies/{doc_id}").status_code == 204
    assert db_session.get(KnowledgeDocument, doc_id).status == "deleted"


def test_ignore_health_item_and_undo(db_session, assistant):
    t = get_current_tenant()
    key = _codes(db_session)["COPILOT_NO_KNOWLEDGE"]["key"]
    out = config_health.set_ignored(db_session, t, key, ignore=True, actor="admin@example.com")
    assert "COPILOT_NO_KNOWLEDGE" not in {i["code"] for i in out["issues"]}
    assert [i["code"] for i in out["ignored"]] == ["COPILOT_NO_KNOWLEDGE"]
    out = config_health.set_ignored(db_session, t, key, ignore=False, actor="admin@example.com")
    assert "COPILOT_NO_KNOWLEDGE" in {i["code"] for i in out["issues"]} and out["ignored"] == []
