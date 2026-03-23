"""Tests for community comments."""

USER = "testuser"
HEADERS = {"X-Community-User": USER, "Content-Type": "application/json"}


def _create_post(client, body="test post"):
    r = client.post("/community/posts", json={"body": body}, headers=HEADERS)
    return r.json()["id"]


def test_create_comment(client):
    post_id = _create_post(client)
    r = client.post(
        f"/community/posts/{post_id}/comments",
        json={"body": "nice post"},
        headers=HEADERS,
    )
    assert r.status_code == 201
    assert r.json()["body"] == "nice post"
    assert r.json()["post_id"] == post_id
    assert r.json()["parent_id"] is None


def test_create_reply(client):
    post_id = _create_post(client)
    r = client.post(
        f"/community/posts/{post_id}/comments",
        json={"body": "parent"},
        headers=HEADERS,
    )
    parent_id = r.json()["id"]

    r = client.post(
        f"/community/posts/{post_id}/comments",
        json={"body": "reply", "parent_id": parent_id},
        headers=HEADERS,
    )
    assert r.status_code == 201
    assert r.json()["parent_id"] == parent_id


def test_reject_nested_reply(client):
    post_id = _create_post(client)
    r = client.post(
        f"/community/posts/{post_id}/comments",
        json={"body": "parent"},
        headers=HEADERS,
    )
    parent_id = r.json()["id"]

    r = client.post(
        f"/community/posts/{post_id}/comments",
        json={"body": "reply", "parent_id": parent_id},
        headers=HEADERS,
    )
    reply_id = r.json()["id"]

    # try replying to the reply — should fail
    r = client.post(
        f"/community/posts/{post_id}/comments",
        json={"body": "nested", "parent_id": reply_id},
        headers=HEADERS,
    )
    assert r.status_code == 400


def test_comments_appear_in_post_detail(client):
    post_id = _create_post(client)
    client.post(
        f"/community/posts/{post_id}/comments",
        json={"body": "c1"},
        headers=HEADERS,
    )

    r = client.get(f"/community/posts/{post_id}")
    assert len(r.json()["comments"]) == 1
    assert r.json()["comments"][0]["body"] == "c1"
