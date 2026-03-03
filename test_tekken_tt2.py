"""Integration tests for tekken_tt2.py wrapper functions against the live RPCN server.

Run with:
    pytest test_tekken_tt2.py -v

Protobuf tests (print_rooms, print_leaderboard) require
np2_structs_pb2.py to be generated first:
    python -m grpc_tools.protoc -I. --python_out=. np2_structs.proto
"""

import pytest
from rpcn_client import RpcnClient
from tekken_tt2 import (
    TTT2_COM_ID,
    print_server_world_tree,
    print_rooms,
    print_leaderboard,
)

# ---------------------------------------------------------------------------
# Hardcoded credentials (Tekken Tag Tournament 2 / np.rpcs3.net)
# ---------------------------------------------------------------------------

HOST     = "np.rpcs3.net"
PORT     = 31313
USER     = "lsjin"
PASSWORD = "23866C8DAF2A8675DFB90B34A35089A68C813BFDEFB2EC99A0CD532A55BB62BB"
TOKEN    = "63FE49A5083ECBA0"
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

def test_print_server_world_tree(session):
    """Integration test for print_server_world_tree."""
    client = session["client"]
    worlds = print_server_world_tree(client, COM_ID)
    print(f"Returned worlds: {worlds}")
    assert isinstance(worlds, list)
    assert all(isinstance(w, int) for w in worlds)


def test_print_rooms(session):
    """Integration test for print_rooms (requires protobuf)."""
    pytest.importorskip("np2_structs_pb2")
    client = session["client"]
    worlds = print_server_world_tree(client, COM_ID)
    print_rooms(client, COM_ID, worlds)
    print("print_rooms completed successfully")


def test_print_leaderboard(session):
    """Integration test for print_leaderboard (requires protobuf)."""
    pytest.importorskip("np2_structs_pb2")
    client = session["client"]
    print_leaderboard(client, COM_ID, BOARD_ID, num_ranks=5)
    print("print_leaderboard completed successfully")
