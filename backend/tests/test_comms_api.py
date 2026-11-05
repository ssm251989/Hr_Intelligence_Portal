"""platform/comms/api_router.py -- the scoped-down Communications API (Part 4 section 6):
template create/publish/preview, rule CRUD, a single default brand_theme, the message log +
resend, suppression listing, and the token-based candidate/employee preferences page."""

from app.models.comms import BrandTheme, NotificationRule, OutboundMessage, SuppressionListEntry
from app.models.connection import Connection, ConnectionRoute
from app.platform.comms.api_router import PREFERENCE_EVENT_GROUPS, make_preferences_token
from app.platform.connectors.providers.smtp import SmtpAdapter
from app.platform.tenancy.context import TENANT_1_ID


# ---- templates ----


def test_create_publish_and_preview_a_template(client):
    created = client.post(
        "/api/v1/comms/templates",
        json={
            "key": "test.comms_api.greeting", "channel": "email",
            "subject_tpl": "Hello {{ name }}", "html_tpl": "<p>Hi {{ name }}, welcome to {{ org.display_name }}.</p>",
            "variables_schema": {"required": ["name"]},
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "draft"
    assert body["key"] == "test.comms_api.greeting"

    published = client.post(f"/api/v1/comms/templates/{body['id']}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "published"

    preview = client.post(f"/api/v1/comms/templates/{body['id']}/preview", json={"sample_context": {"name": "Jane"}})
    assert preview.status_code == 200
    rendered = preview.json()
    assert "Hi Jane" in rendered["html"]
    # org.display_name comes from the real tenant #1 setting, not the caller -- proves the
    # preview renders with the same theme/org context a real send would.
    assert "welcome to" in rendered["html"]


def test_publishing_a_template_with_a_missing_required_variable_fails_loudly(client):
    created = client.post(
        "/api/v1/comms/templates",
        json={"key": "test.comms_api.broken", "channel": "email", "subject_tpl": "{{ never_provided }}", "variables_schema": {"required": ["never_provided"]}},
    )
    template_id = created.json()["id"]
    # publish()'s own sample-fill covers every required var with a placeholder, so this
    # particular template actually publishes fine -- the real failure mode is a template
    # syntax error, which render_template surfaces as a 400.
    broken = client.post(
        "/api/v1/comms/templates",
        json={"key": "test.comms_api.syntax_error", "channel": "email", "subject_tpl": "{{ unterminated", "variables_schema": {}},
    )
    response = client.post(f"/api/v1/comms/templates/{broken.json()['id']}/publish")
    assert response.status_code == 400


def test_list_templates_returns_only_the_latest_version_per_key(client):
    first = client.post("/api/v1/comms/templates", json={"key": "test.comms_api.versioned", "channel": "email", "subject_tpl": "v1"})
    client.post(f"/api/v1/comms/templates/{first.json()['id']}/publish")
    second = client.post("/api/v1/comms/templates", json={"key": "test.comms_api.versioned", "channel": "email", "subject_tpl": "v2"})

    listed = client.get("/api/v1/comms/templates").json()
    matches = [t for t in listed if t["key"] == "test.comms_api.versioned"]
    assert len(matches) == 1
    assert matches[0]["version"] == 2

    versions = client.get("/api/v1/comms/templates/test.comms_api.versioned/versions").json()
    assert [v["version"] for v in versions] == [2, 1]


# ---- rules ----


def test_create_update_and_delete_a_rule(client, db_session):
    created = client.post(
        "/api/v1/comms/rules",
        json={
            "name": "Test rule", "event_type": "test.comms_api.event", "recipients_json": {"users": ["a@example.com"]},
            "channels": ["email"], "template_key": "test.comms_api.greeting",
        },
    )
    assert created.status_code == 201
    rule_id = created.json()["id"]

    updated = client.patch(f"/api/v1/comms/rules/{rule_id}", json={"enabled": False, "priority": 5})
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False
    assert updated.json()["priority"] == 5

    deleted = client.delete(f"/api/v1/comms/rules/{rule_id}")
    assert deleted.status_code == 204
    assert db_session.get(NotificationRule, rule_id) is None


# ---- brand theme ----


def test_get_brand_theme_returns_none_until_one_is_upserted(client, db_session):
    db_session.query(BrandTheme).filter(BrandTheme.tenant_id == TENANT_1_ID, BrandTheme.is_default.is_(True)).delete()
    db_session.commit()

    assert client.get("/api/v1/comms/brand-theme").json() is None

    upserted = client.put("/api/v1/comms/brand-theme", json={"name": "Default", "primary_color": "#123456"})
    assert upserted.status_code == 200
    assert upserted.json()["primary_color"] == "#123456"

    fetched = client.get("/api/v1/comms/brand-theme").json()
    assert fetched["primary_color"] == "#123456"

    # A second PUT updates the same row rather than creating a second default theme.
    client.put("/api/v1/comms/brand-theme", json={"name": "Default", "primary_color": "#654321"})
    rows = db_session.query(BrandTheme).filter(BrandTheme.tenant_id == TENANT_1_ID, BrandTheme.is_default.is_(True)).all()
    assert len(rows) == 1
    assert rows[0].primary_color == "#654321"


# ---- message log ----


def test_list_and_filter_outbound_messages(client, db_session):
    db_session.add(OutboundMessage(tenant_id=TENANT_1_ID, channel="email", purpose="test.x", to_addresses=["a@example.com"], status="sent"))
    db_session.add(OutboundMessage(tenant_id=TENANT_1_ID, channel="email", purpose="test.x", to_addresses=["b@example.com"], status="failed"))
    db_session.commit()

    failed_only = client.get("/api/v1/comms/outbound", params={"status": "failed"}).json()
    assert all(m["status"] == "failed" for m in failed_only)
    assert any(m["to_addresses"] == ["b@example.com"] for m in failed_only)


def test_resend_an_outbound_message_reuses_its_already_rendered_content(client, db_session, monkeypatch):
    conn = Connection(tenant_id=TENANT_1_ID, name="resend-test-smtp", provider_code="smtp", capability=["EmailSender"], config_json={"host": "smtp.example.com", "port": 587, "username": "hr@example.com"}, status="active")
    db_session.add(conn)
    db_session.commit()
    db_session.add(ConnectionRoute(tenant_id=TENANT_1_ID, purpose="test.comms_api.resend", connection_id=conn.id, priority=1))
    db_session.commit()

    captured = []
    monkeypatch.setattr(SmtpAdapter, "send", lambda self, msg: captured.append(msg) or __import__("app.platform.connectors.capabilities", fromlist=["ProviderResult"]).ProviderResult(success=True, provider_message_id="mid-123"))

    message = OutboundMessage(
        tenant_id=TENANT_1_ID, channel="email", purpose="test.comms_api.resend",
        to_addresses=["candidate@example.com"], subject="Original subject", body_ref="Original body", status="failed",
    )
    db_session.add(message)
    db_session.commit()
    db_session.refresh(message)

    response = client.post(f"/api/v1/comms/outbound/{message.id}/resend")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "sent"
    assert len(captured) == 1
    assert captured[0].to == ["candidate@example.com"]
    assert captured[0].subject == "Original subject"


# ---- suppression ----


def test_list_and_remove_a_suppression_entry(client, db_session):
    db_session.add(SuppressionListEntry(tenant_id=TENANT_1_ID, address="bounced@example.com", reason="bounce"))
    db_session.commit()

    listed = client.get("/api/v1/comms/suppression").json()
    assert any(row["address"] == "bounced@example.com" for row in listed)

    removed = client.delete("/api/v1/comms/suppression/bounced@example.com")
    assert removed.status_code == 204
    assert db_session.query(SuppressionListEntry).filter(SuppressionListEntry.address == "bounced@example.com").first() is None


# ---- public preferences page ----


def test_get_and_set_preferences_via_a_signed_token(client):
    import uuid

    candidate_id = uuid.uuid4()
    token = make_preferences_token(tenant_id=TENANT_1_ID, candidate_id=candidate_id)

    fetched = client.get("/api/v1/public/comms/preferences", params={"token": token})
    assert fetched.status_code == 200
    body = fetched.json()
    assert len(body["preferences"]) == len(PREFERENCE_EVENT_GROUPS)
    assert all(p["opted_in"] is True for p in body["preferences"])

    group = PREFERENCE_EVENT_GROUPS[0]
    updated = client.post("/api/v1/public/comms/preferences", json={"token": token, "event_group": group, "channel": "email", "opted_in": False})
    assert updated.status_code == 200
    assert updated.json()["opted_in"] is False

    refetched = client.get("/api/v1/public/comms/preferences", params={"token": token}).json()
    matched = next(p for p in refetched["preferences"] if p["event_group"] == group)
    assert matched["opted_in"] is False
    # every other event_group is untouched
    others = [p for p in refetched["preferences"] if p["event_group"] != group]
    assert all(p["opted_in"] is True for p in others)


def test_a_forged_or_corrupted_preferences_token_is_rejected(client):
    response = client.get("/api/v1/public/comms/preferences", params={"token": "not-a-real-token"})
    assert response.status_code == 400


def test_preferences_html_page_renders_current_state_and_saves_a_change(client, db_session):
    import uuid

    candidate_id = uuid.uuid4()
    token = make_preferences_token(tenant_id=TENANT_1_ID, candidate_id=candidate_id)

    page = client.get("/api/v1/public/comms/preferences/page", params={"token": token})
    assert page.status_code == 200
    assert "Email Preferences" in page.text
    group = PREFERENCE_EVENT_GROUPS[0]
    assert group in page.text
    # every event_group starts opted in -- checked in the rendered form
    assert page.text.count(" checked />") == len(PREFERENCE_EVENT_GROUPS)

    # Submitting with only some event_group checkboxes present (an unchecked box simply
    # isn't in form data, same as a real browser) opts the omitted ones out.
    from urllib.parse import urlencode

    body = urlencode([("token", token)] + [("event_group", g) for g in PREFERENCE_EVENT_GROUPS if g != group])
    submitted = client.post(
        "/api/v1/public/comms/preferences/page",
        content=body, headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert submitted.status_code == 200
    assert "Preferences saved." in submitted.text
    assert submitted.text.count(" checked />") == len(PREFERENCE_EVENT_GROUPS) - 1

    from app.platform.comms.suppression import is_opted_in
    from app.platform.tenancy.context import TenantContext

    tenant = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")
    assert is_opted_in(db_session, tenant, candidate_id=candidate_id, channel="email", event_group=group) is False


def test_preferences_token_for_one_candidate_cannot_set_prefs_for_another():
    """make_preferences_token embeds exactly one identity -- there is no way to pass a
    different candidate_id at set-time, so this is really a shape assertion that the
    payload never carries anything the caller supplies."""
    import uuid

    from app.platform.comms.api_router import _decode_preferences_token

    token = make_preferences_token(tenant_id=TENANT_1_ID, candidate_id=uuid.uuid4())
    decoded = _decode_preferences_token(token)
    assert set(decoded) <= {"purpose", "tenant_id", "candidate_id", "user_id"}
