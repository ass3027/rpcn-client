"""Integration tests for rpcn_client.py against the live RPCN server.

Run with:
    pytest test_rpcn_client.py -v

Protobuf tests (search_rooms, get_score_range, get_score_npid) require
np2_structs_pb2.py to be generated first:
    python -m grpc_tools.protoc -I. --python_out=. np2_structs.proto
"""

import pytest
from rpcn_client import RpcnClient, RpcnError, PROTOCOL_VERSION, LoginInfo, SearchRoomsResult, ScoreResult, _format_epoch

# ---------------------------------------------------------------------------
# Hardcoded credentials (Tekken Tag Tournament 2 / np.rpcs3.net)
# ---------------------------------------------------------------------------

HOST     = "np.rpcs3.net"
PORT     = 31313
USER     = "lsjin"
PASSWORD = "23866C8DAF2A8675DFB90B34A35089A68C813BFDEFB2EC99A0CD532A55BB62BB"
TOKEN    = "63FE49A5083ECBA0"
COM_ID   = "NPWR02973_00"
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
    assert isinstance(info, LoginInfo)
    assert isinstance(info.online_name, str) and info.online_name, \
        "online_name should be a non-empty string"
    assert isinstance(info.avatar_url, str), \
        "avatar_url should be a string"
    assert isinstance(info.user_id, int), \
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

    assert isinstance(resp, SearchRoomsResult)
    assert isinstance(resp.total, int) and resp.total >= 0
    assert isinstance(resp.rooms, list)


# ---------------------------------------------------------------------------
# Leaderboard tests (require generated protobuf module)
# ---------------------------------------------------------------------------

def test_get_score_range(session):
    pytest.importorskip("np2_structs_pb2")
    client = session["client"]

    resp = client.get_score_range(COM_ID, BOARD_ID, start_rank=1, num_ranks=10)

    assert isinstance(resp, ScoreResult)
    assert isinstance(resp.total_records, int) and resp.total_records >= 0

    assert isinstance(resp.entries, list)
    assert len(resp.entries) <= 10

    for entry in resp.entries:
        assert isinstance(entry.np_id, str) and entry.np_id, \
            "entry.np_id should be a non-empty string"
        assert entry.rank >= 1, \
            "entry.rank should be >= 1"


def test_get_score_npid(session):
    pytest.importorskip("np2_structs_pb2")
    client = session["client"]
    # online_name = session["login_info"]["online_name"]
    online_name = "tk_unnamed"

    resp = client.get_score_npid(COM_ID, BOARD_ID, [online_name])

    assert isinstance(resp, ScoreResult)
    assert isinstance(resp.entries, list)


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


# ---------------------------------------------------------------------------
# Utility function tests
# ---------------------------------------------------------------------------

def test_format_epoch():
    """Unit test for _format_epoch — no server connection needed."""
    result_zero = _format_epoch(0)
    print(f"_format_epoch(0) = {result_zero!r}")
    assert result_zero == "N/A"

    # 2024-01-01 00:00:00 UTC in microseconds
    known_us = 1_704_067_200 * 1_000_000
    result_known = _format_epoch(known_us)
    print(f"_format_epoch({known_us}) = {result_known!r}")
    assert result_known == "2024-01-01 00:00:00 UTC"

    # Negative overflow — should fall through to the fallback string
    result_bad = _format_epoch(-999_999_999_999_999_999)
    print(f"_format_epoch(-999...) = {result_bad!r}")
    assert result_bad.startswith("epoch=")
