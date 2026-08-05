from app.models.user import User


def _make_user(db_session, email, role, full_name=None) -> User:
    user = User(email=email, hashed_password="x", role=role, full_name=full_name)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_list_users_returns_all_users(client, db_session):
    _make_user(db_session, "interviewer-a@example.com", "interviewer")
    _make_user(db_session, "recruiter-a@example.com", "recruiter")

    response = client.get("/users")

    assert response.status_code == 200
    emails = {u["email"] for u in response.json()}
    assert {"interviewer-a@example.com", "recruiter-a@example.com"}.issubset(emails)


def test_list_users_filters_by_role(client, db_session):
    _make_user(db_session, "interviewer-b@example.com", "interviewer")
    _make_user(db_session, "recruiter-b@example.com", "recruiter")

    response = client.get("/users?role=interviewer")

    assert response.status_code == 200
    body = response.json()
    assert all(u["role"] == "interviewer" for u in body)
    assert any(u["email"] == "interviewer-b@example.com" for u in body)
    assert not any(u["email"] == "recruiter-b@example.com" for u in body)


def test_list_users_requires_authentication(anonymous_client):
    response = anonymous_client.get("/users")
    assert response.status_code == 401
