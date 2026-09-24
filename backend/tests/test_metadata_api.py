"""platform/metadata/api_router.py -- custom fields, form layouts, masters, sequences
over real HTTP (Part 6 CHECKS)."""


def test_create_list_and_deactivate_a_custom_field_def(client):
    created = client.post("/api/v1/metadata/custom-fields", json={"entity": "candidate", "code": "test_linkedin_url", "type": "url", "label_i18n": {"en": "LinkedIn URL"}})
    assert created.status_code == 201
    def_id = created.json()["id"]

    listed = client.get("/api/v1/metadata/custom-fields", params={"entity": "candidate"})
    assert any(d["code"] == "test_linkedin_url" for d in listed.json())

    deactivated = client.patch(f"/api/v1/metadata/custom-fields/{def_id}", params={"is_active": False})
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    deleted = client.delete(f"/api/v1/metadata/custom-fields/{def_id}")
    assert deleted.status_code == 204


def test_create_custom_field_def_rejects_an_unknown_entity(client):
    response = client.post("/api/v1/metadata/custom-fields", json={"entity": "spaceship", "code": "x", "type": "text", "label_i18n": {}})
    assert response.status_code == 400


def test_form_layout_upsert_and_effective_layout_merges_custom_fields(client):
    client.post("/api/v1/metadata/custom-fields", json={"entity": "job", "code": "test_bonus_eligible", "type": "bool", "label_i18n": {"en": "Bonus eligible"}, "section": "Compensation"})

    upserted = client.put("/api/v1/metadata/form-layouts", json={"entity": "job", "context": "create", "sections": [{"name": "Basics", "fields": ["title", "department"]}]})
    assert upserted.status_code == 200

    effective = client.get("/api/v1/metadata/form-layouts/job/create")
    assert effective.status_code == 200
    body = effective.json()
    assert body["sections"][0]["name"] == "Basics"
    assert any(f["code"] == "test_bonus_eligible" for f in body["custom_fields"])


def test_master_types_and_values_over_http(client):
    types = client.get("/api/v1/metadata/master-types")
    assert types.status_code == 200
    codes = {t["code"] for t in types.json()}
    assert "source_of_hire" in codes

    created = client.post("/api/v1/metadata/master-values/source_of_hire", json={"code": "test_referral", "label_i18n": {"en": "Referral"}})
    assert created.status_code == 201
    value_id = created.json()["id"]

    listed = client.get("/api/v1/metadata/master-values/source_of_hire")
    assert any(v["code"] == "test_referral" for v in listed.json())

    deactivated = client.delete(f"/api/v1/metadata/master-values/{value_id}")
    assert deactivated.status_code == 204
    assert not any(v["code"] == "test_referral" for v in client.get("/api/v1/metadata/master-values/source_of_hire").json())


def test_define_and_advance_a_sequence_over_http(client):
    defined = client.post("/api/v1/metadata/sequences", json={"key": "test.http_seq", "pattern": "HTTP-{SEQ:3}", "reset": "never"})
    assert defined.status_code == 201

    first = client.post("/api/v1/metadata/sequences/test.http_seq/next")
    assert first.status_code == 200
    assert first.json()["value"] == "HTTP-001"

    second = client.post("/api/v1/metadata/sequences/test.http_seq/next")
    assert second.json()["value"] == "HTTP-002"


def test_get_next_value_for_undefined_sequence_returns_404(client):
    response = client.post("/api/v1/metadata/sequences/does.not.exist/next")
    assert response.status_code == 404
