"""Tests for community thumb toggle logic."""

USER = "testuser"
HEADERS = {"X-Community-User": USER, "Content-Type": "application/json"}


def _create_post(client, body="test post"):
    r = client.post("/community/posts", json={"body": body}, headers=HEADERS)
    return r.json()["id"]


def test_thumb_up_post(client):
    post_id = _create_post(client)
    r = client.post(f"/community/posts/{post_id}/thumb", json={"direction": 1}, headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["thumbs_up"] == 1
    assert r.json()["thumbs_down"] == 0


def test_thumb_toggle_off(client):
    post_id = _create_post(client)
    # thumb up
    client.post(f"/community/posts/{post_id}/thumb", json={"direction": 1}, headers=HEADERS)
    # same direction again → toggle off
    r = client.post(f"/community/posts/{post_id}/thumb", json={"direction": 1}, headers=HEADERS)
    assert r.json()["thumbs_up"] == 0


def test_thumb_switch_direction(client):
    post_id = _create_post(client)
    client.post(f"/community/posts/{post_id}/thumb", json={"direction": 1}, headers=HEADERS)
    r = client.post(f"/community/posts/{post_id}/thumb", json={"direction": -1}, headers=HEADERS)
    assert r.json()["thumbs_up"] == 0
    assert r.json()["thumbs_down"] == 1


def test_thumb_invalid_direction(client):
    post_id = _create_post(client)
    r = client.post(f"/community/posts/{post_id}/thumb", json={"direction": 0}, headers=HEADERS)
    assert r.status_code == 422


def test_thumb_nonexistent_post(client):
    r = client.post("/community/posts/99999/thumb", json={"direction": 1}, headers=HEADERS)
    assert r.status_code == 404
