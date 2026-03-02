"""Integration tests for rpcn_client.py against the live RPCN server.

Run with:
    pytest test_integration.py -v

Protobuf tests (search_rooms, get_score_range, get_score_npid) require
np2_structs_pb2.py to be generated first:
    python -m grpc_tools.protoc -I. --python_out=. np2_structs.proto
"""

import pytest
from rpcn_client import RpcnClient, RpcnError, PROTOCOL_VERSION

# ---------------------------------------------------------------------------
# Hardcoded credentials (Tekken Tag Tournament 2 / np.rpcs3.net)
# ---------------------------------------------------------------------------

HOST     = "np.rpcs3.net"
PORT     = 31313
USER     = "lsjin"
PASSWORD = "23866C8DAF2A8675DFB90B34A35089A68C813BFDEFB2EC99A0CD532A55BB62BB"
TOKEN    = "63FE49A5083ECBA0"
COM_ID   = "NPWR04850_00"
BOARD_ID = 0


# ---------------------------------------------------------------------------
# Session fixture — connect + login once, share across all tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def session():
    c = RpcnClient(HOST, PORT)
    c.connect()
    info = c.login(USER, PASSWORD, TOKEN)
    yield {"client": c, "login_info": info}
    c.disconnect()


# ---------------------------------------------------------------------------
# Connection / auth tests
# ---------------------------------------------------------------------------

def test_connect_returns_protocol_version():
    c = RpcnClient(HOST, PORT)
    version = c.connect()
    c.disconnect()
    assert version == PROTOCOL_VERSION


def test_login_info(session):
    info = session["login_info"]
    assert isinstance(info["online_name"], str) and info["online_name"], \
        "online_name should be a non-empty string"
    assert isinstance(info["avatar_url"], str), \
        "avatar_url should be a string"
    assert isinstance(info["user_id"], int), \
        "user_id should be an int"


# ---------------------------------------------------------------------------
# Server / world list tests
# ---------------------------------------------------------------------------

def test_get_server_list(session):
    client = session["client"]
    servers = client.get_server_list(COM_ID)
    assert isinstance(servers, list)
    assert all(isinstance(s, int) for s in servers)


def test_get_world_list(session):
    client = session["client"]
    servers = client.get_server_list(COM_ID)
    assert servers, "Need at least one server to test get_world_list"
    worlds = client.get_world_list(COM_ID, servers[0])
    assert isinstance(worlds, list)
    assert all(isinstance(w, int) for w in worlds)


# ---------------------------------------------------------------------------
# Room search test (requires generated protobuf module)
# ---------------------------------------------------------------------------

def test_search_rooms(session):
    pytest.importorskip("np2_structs_pb2")
    client = session["client"]

    servers = client.get_server_list(COM_ID)
    assert servers, "Need at least one server to resolve worlds"
    worlds = client.get_world_list(COM_ID, servers[0])

    world_id = worlds[0] if worlds else 0
    resp = client.search_rooms(COM_ID, world_id=world_id, max_results=20)

    assert hasattr(resp, "total"), "SearchRoomResponse missing 'total'"
    assert isinstance(resp.total, int) and resp.total >= 0
    assert hasattr(resp, "rooms"), "SearchRoomResponse missing 'rooms'"
    assert isinstance(list(resp.rooms), list)


# ---------------------------------------------------------------------------
# Leaderboard tests (require generated protobuf module)
# ---------------------------------------------------------------------------

def test_get_score_range(session):
    pytest.importorskip("np2_structs_pb2")
    client = session["client"]

    resp = client.get_score_range(COM_ID, BOARD_ID, start_rank=1, num_ranks=5)

    assert hasattr(resp, "totalRecord"), "GetScoreResponse missing 'totalRecord'"
    assert isinstance(resp.totalRecord, int) and resp.totalRecord >= 0

    assert hasattr(resp, "rankArray"), "GetScoreResponse missing 'rankArray'"
    entries = list(resp.rankArray)
    assert len(entries) <= 5

    for entry in entries:
        assert isinstance(entry.npId, str) and entry.npId, \
            "rankArray entry.npId should be a non-empty string"
        assert entry.rank >= 1, \
            "rankArray entry.rank should be >= 1"


def test_get_score_npid(session):
    pytest.importorskip("np2_structs_pb2")
    client = session["client"]
    online_name = session["login_info"]["online_name"]

    resp = client.get_score_npid(COM_ID, BOARD_ID, [online_name])

    assert hasattr(resp, "rankArray"), "GetScoreResponse missing 'rankArray'"
    assert isinstance(list(resp.rankArray), list)


# ---------------------------------------------------------------------------
# Error / validation tests
# ---------------------------------------------------------------------------

def test_invalid_com_id_raises(session):
    client = session["client"]
    with pytest.raises(ValueError):
        client.get_server_list("TOOSHORT")


def test_wrong_password_raises():
    c = RpcnClient(HOST, PORT)
    c.connect()
    try:
        with pytest.raises(RpcnError, match="Login failed"):
            c.login(USER, "wrongpassword", "")
    finally:
        c.disconnect()
