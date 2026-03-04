"""Integration tests for tekken_tt2.py query functions against the live RPCN server.

Run with:
    pytest test_tekken_tt2.py -v

Protobuf tests (get_rooms, get_leaderboard) require
np2_structs_pb2.py to be generated first:
    python -m grpc_tools.protoc -I. --python_out=. np2_structs.proto
"""

import pytest
from rpcn_client import RpcnClient, SearchRoomsResult
from tekken_tt2 import (
    TTT2_COM_ID,
    TTT2LeaderboardResult,
    TTT2LeaderboardEntry,
    get_server_world_tree,
    get_rooms,
    get_leaderboard,
)

# ---------------------------------------------------------------------------
# Hardcoded credentials (Tekken Tag Tournament 2 / np.rpcs3.net)
# ---------------------------------------------------------------------------

HOST     = "rpcn.mynarco.xyz"
PORT     = 31313
USER     = "doStudy"
PASSWORD = "23866C8DAF2A8675DFB90B34A35089A68C813BFDEFB2EC99A0CD532A55BB62BB"
TOKEN    = ""
COM_ID   = TTT2_COM_ID
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
# tekken_tt2.py wrapper tests
# ---------------------------------------------------------------------------

def test_get_server_world_tree(session):
    """Integration test for get_server_world_tree — returns dict[int, list[int]]."""
    client = session["client"]
    tree = get_server_world_tree(client, COM_ID)
    print(f"Returned tree: {tree}")
    assert isinstance(tree, dict)
    for server_id, worlds in tree.items():
        assert isinstance(server_id, int)
        assert isinstance(worlds, list)
        assert all(isinstance(w, int) for w in worlds)


def test_get_rooms(session):
    """Integration test for get_rooms — returns dict[int, SearchRoomsResult]."""
    pytest.importorskip("np2_structs_pb2")
    client = session["client"]
    tree = get_server_world_tree(client, COM_ID)
    all_worlds = [w for worlds in tree.values() for w in worlds]
    results = get_rooms(client, COM_ID, all_worlds)
    print(f"Returned rooms: {results}")
    assert isinstance(results, dict)
    for world_id, resp in results.items():
        assert isinstance(world_id, int)
        assert isinstance(resp, SearchRoomsResult)


def test_get_leaderboard(session):
    """Integration test for get_leaderboard — returns TTT2LeaderboardResult with parsed entries."""
    pytest.importorskip("np2_structs_pb2")
    client = session["client"]
    resp = get_leaderboard(client, COM_ID, BOARD_ID, num_ranks=5)
    print(f"Returned leaderboard: {resp}")
    assert isinstance(resp, TTT2LeaderboardResult)
    for entry in resp.entries:
        assert isinstance(entry, TTT2LeaderboardEntry)
        assert isinstance(entry.rank, int)
        assert isinstance(entry.np_id, str)


