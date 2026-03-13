"""FastAPI server exposing Tekken Tag Tournament 2 RPCN data.

Credentials are read from environment variables:
  RPCN_USER      - RPCN username (required)
  RPCN_PASSWORD  - RPCN password (required)
  RPCN_TOKEN     - RPCN token   (optional, default: "")
  RPCN_HOST      - server host  (optional, default: np.rpcs3.net)
  RPCN_PORT      - server port  (optional, default: 31313)

Run:
  pip install fastapi uvicorn
  RPCN_USER=you RPCN_PASSWORD=secret uvicorn tekken_tt2_api:app --reload
"""

import os
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, Query
from rpcn_client import RpcnClient, RpcnError
from tekken_tt2 import (
    TTT2_COM_ID,
    TTT2_BOARD_ID,
    get_server_world_tree,
    get_rooms,
    get_leaderboard,
    TTT2LeaderboardEntry,
    TTT2GameInfo,
    CharInfo,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_HOST = os.getenv("RPCN_HOST", "np.rpcs3.net")
_PORT = int(os.getenv("RPCN_PORT", "31313"))
_USER = os.environ["RPCN_USER"]
_PASSWORD = os.environ["RPCN_PASSWORD"]
_TOKEN = os.getenv("RPCN_TOKEN", "")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Tekken Tag Tournament 2 RPCN API",
    description="Live data from the RPCN multiplayer server for TTT2.",
)


@contextmanager
def _client():
    """Open an authenticated RpcnClient, yield it, then disconnect."""
    with RpcnClient(host=_HOST, port=_PORT) as client:
        try:
            client.connect()
            client.login(_USER, _PASSWORD, _TOKEN)
            yield client
        except RpcnError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _char_info_dict(c: CharInfo) -> dict:
    return {"char_id": c.char_id, "name": c.name, "rank": c.rank, "wins": c.wins, "losses": c.losses}


def _game_info_dict(g: TTT2GameInfo | None) -> dict | None:
    if g is None:
        return None
    return {
        "main": _char_info_dict(g.main_char_info),
        "sub": _char_info_dict(g.sub_char_info),
    }


def _lb_entry_dict(e: TTT2LeaderboardEntry) -> dict:
    return {
        "rank": e.rank,
        "np_id": e.np_id,
        "online_name": e.online_name,
        "score": e.score,
        "pc_id": e.pc_id,
        "record_date": e.record_date,
        "has_game_data": e.has_game_data,
        "comment": e.comment,
        "player_info": _game_info_dict(e.player_info),
    }


def _room_dict(r) -> dict:
    return {
        "room_id": r.room_id,
        "owner_npid": r.owner_npid,
        "owner_online_name": r.owner_online_name,
        "current_members": r.current_members,
        "max_slots": r.max_slots,
        "flag_attr": r.flag_attr,
        "int_attrs": [{"id": a.id, "value": a.value} for a in r.int_attrs],
        "bin_search_attrs": [{"id": a.id, "data": a.data.hex()} for a in r.bin_search_attrs],
        "bin_attrs": [{"id": a.id, "data": a.data.hex()} for a in r.bin_attrs],
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/servers", summary="Server and world list")
def servers(com_id: str = Query(default=TTT2_COM_ID, description="Game comm ID")):
    """Return the server → world hierarchy for the given comm ID."""
    with _client() as client:
        tree = get_server_world_tree(client, com_id)
    return {"com_id": com_id, "servers": {str(k): v for k, v in tree.items()}}


@app.get("/rooms", summary="Active rooms")
def rooms(com_id: str = Query(default=TTT2_COM_ID, description="Game comm ID")):
    """Return all active rooms across every world for the given comm ID."""
    with _client() as client:
        tree = get_server_world_tree(client, com_id)
        all_worlds = [w for worlds in tree.values() for w in worlds]
        room_map = get_rooms(client, com_id, all_worlds)

    return {
        "com_id": com_id,
        "worlds": {
            str(world_id): {
                "total": resp.total,
                "rooms": [_room_dict(r) for r in resp.rooms],
            }
            for world_id, resp in room_map.items()
        },
    }


@app.get("/rooms/all", summary="All rooms including hidden")
def rooms_all(
    com_id: str = Query(default=TTT2_COM_ID, description="Game comm ID"),
    world_id: int = Query(default=0, description="World ID (0 = any)"),
    start_index: int = Query(default=1, ge=1, description="Pagination start index"),
    max_results: int = Query(default=20, ge=1, le=20, description="Max results (capped at 20)"),
):
    """Search all rooms including hidden ones via SearchRoomAll."""
    with _client() as client:
        resp = client.search_rooms_all(
            com_id,
            world_id=world_id,
            start_index=start_index,
            max_results=max_results,
        )
    return {
        "com_id": com_id,
        "world_id": world_id,
        "total": resp.total,
        "rooms": [_room_dict(r) for r in resp.rooms],
    }


@app.get("/leaderboard", summary="Leaderboard entries")
def leaderboard(
    com_id: str = Query(default=TTT2_COM_ID, description="Game comm ID"),
    board: int = Query(default=TTT2_BOARD_ID, description="Score board ID"),
    top: int = Query(default=10, ge=1, le=100, description="Number of entries to return"),
):
    """Return the top N leaderboard entries with TTT2 character info decoded."""
    with _client() as client:
        lb = get_leaderboard(client, com_id, board, num_ranks=top)

    return {
        "com_id": com_id,
        "board": board,
        "total_records": lb.total_records,
        "last_sort_date": lb.last_sort_date,
        "entries": [_lb_entry_dict(e) for e in lb.entries],
    }
