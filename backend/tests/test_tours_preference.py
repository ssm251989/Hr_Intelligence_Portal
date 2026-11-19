"""Part 27 (cross-cutting): "Don't show tours again" is one switch per person, saved on the server."""


def test_tours_off_is_saved_per_user_and_comes_back_in_bootstrap(client):
    before = client.get("/api/me/bootstrap").json()
    assert before["ux"]["tours_off"] is False
    assert client.put("/api/v1/me/preferences", json={"tours_off": True}).json() == {"ok": True}
    assert client.get("/api/me/bootstrap").json()["ux"]["tours_off"] is True
