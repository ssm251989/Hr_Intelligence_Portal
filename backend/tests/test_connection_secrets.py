"""Secrets never in responses/logs (Part 3 CHECKS)."""

import json

from app.models.connection import Connection
from app.models.secret import Secret
from app.platform.tenancy.context import TENANT_1_ID


def test_creating_a_connection_with_secrets_never_returns_them(client):
    response = client.post(
        "/api/v1/connections",
        json={"name": "Test SMTP", "provider_code": "smtp", "config": {"host": "smtp.example.com", "port": 587, "username": "hr@example.com"}, "secrets": {"password": "hunter2"}},
    )
    assert response.status_code == 201
    body = response.json()
    assert "secrets" not in body
    assert "secret_ref" not in body
    assert "password" not in json.dumps(body)
    assert "hunter2" not in json.dumps(body)


def test_listing_connections_never_returns_secret_material(client, db_session):
    client.post(
        "/api/v1/connections",
        json={"name": "Test SMTP 2", "provider_code": "smtp", "config": {"host": "smtp.example.com", "port": 587, "username": "hr@example.com"}, "secrets": {"password": "supersecretvalue"}},
    )

    response = client.get("/api/v1/connections")
    assert response.status_code == 200
    assert "supersecretvalue" not in response.text


def test_ciphertext_in_the_database_never_contains_the_plaintext_secret(client, db_session):
    client.post(
        "/api/v1/connections",
        json={"name": "Test SMTP 3", "provider_code": "smtp", "config": {"host": "smtp.example.com", "port": 587, "username": "hr@example.com"}, "secrets": {"password": "anothersecretvalue"}},
    )
    connection = db_session.query(Connection).filter(Connection.name == "Test SMTP 3").first()
    assert connection is not None
    assert connection.secret_ref is not None
    secret_row = db_session.query(Secret).filter(Secret.ref == connection.secret_ref).first()
    assert secret_row is not None
    assert "anothersecretvalue" not in secret_row.ciphertext


def test_test_connection_response_never_includes_the_secret(client, db_session):
    create = client.post(
        "/api/v1/connections",
        json={"name": "Test SMTP 4", "provider_code": "smtp", "config": {"host": "127.0.0.1", "port": 1, "username": "hr@example.com"}, "secrets": {"password": "yetanothersecret"}},
    )
    connection_id = create.json()["id"]

    response = client.post(f"/api/v1/connections/{connection_id}/test")
    assert response.status_code == 200
    assert "yetanothersecret" not in response.text
