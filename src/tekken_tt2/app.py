"""Tekken Tag Tournament 2 RPCN queries and API server.

Credentials are read from environment variables:
  RPCN_USER      - RPCN username (required)
  RPCN_PASSWORD  - RPCN password (required)
  RPCN_TOKEN     - RPCN token   (optional, default: "")
  RPCN_HOST      - server host  (optional, default: np.rpcs3.net)
  RPCN_PORT      - server port  (optional, default: 31313)

API usage:
  RPCN_USER=you RPCN_PASSWORD=secret uvicorn tekken_tt2.app:app --reload
"""

import json
import logging
import os
import struct
from contextlib import contextmanager
from dataclasses import dataclass

import redis as _redis
from fastapi import FastAPI, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from rpcn_client import RpcnClient, RpcnError, SearchRoomsResult, ScoreEntry
from tekken_tt2.data import TTT2_CHARACTERS

# ---------------------------------------------------------------------------
# Game constants
# ---------------------------------------------------------------------------

TTT2_COM_ID = "NPWR02973_00"
TTT2_BOARD_ID = 0

_GAME_INFO_FMT = ">4B4I"
_GAME_INFO_SIZE = 20


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CharInfo:
	"""A single character's stats from a TTT2 leaderboard entry."""
	char_id: int
	rank: int
	wins: int
	losses: int

	@property
	def name(self) -> str:
		return TTT2_CHARACTERS.get(self.char_id, f"Unknown(0x{self.char_id:02x})")

	def __str__(self):
		return f"{self.name}/{hex(self.char_id)}(rank {self.rank}) {self.wins}W/{self.losses}L"


@dataclass
class TTT2GameInfo:
	"""Parsed TTT2 game_info from a 64-byte leaderboard blob."""
	main_char_info: CharInfo
	sub_char_info: CharInfo

	def __str__(self):
		return f"{self.main_char_info} + {self.sub_char_info}"


@dataclass
class TTT2LeaderboardEntry:
	"""A leaderboard entry with game_info already parsed into TTT2GameInfo."""
	rank: int
	np_id: str
	online_name: str
	score: int
	pc_id: int
	record_date: int
	has_game_data: bool
	comment: str
	player_info: TTT2GameInfo | None

	def __str__(self):
		base = f"#{self.rank} {self.online_name} ({self.np_id}) score={self.score}"
		if self.player_info:
			base += f"\n       >> {self.player_info}"
		return base


@dataclass
class TTT2LeaderboardResult:
	"""Leaderboard result with parsed TTT2-specific entries."""
	total_records: int
	last_sort_date: int
	entries: list[TTT2LeaderboardEntry]


# ---------------------------------------------------------------------------
# Game logic
# ---------------------------------------------------------------------------

def parse_game_info(data: bytes) -> TTT2GameInfo | None:
	"""Parse a 64-byte TTT2 game_info blob. Returns None if data is too short."""
	if len(data) < _GAME_INFO_SIZE:
		return None
	c1_id, c2_id, c1_rank, c2_rank, c1_w, c2_w, c1_l, c2_l = struct.unpack(
		_GAME_INFO_FMT, data[:_GAME_INFO_SIZE]
	)
	return TTT2GameInfo(
		main_char_info=CharInfo(char_id=c1_id, rank=c1_rank, wins=c1_w, losses=c1_l),
		sub_char_info=CharInfo(char_id=c2_id, rank=c2_rank, wins=c2_w, losses=c2_l),
	)


def format_score_entry(entry: ScoreEntry) -> str:
	"""Format a ScoreEntry with TTT2-specific game_info decoding."""
	base = str(entry)
	if entry.game_info:
		info = parse_game_info(entry.game_info)
		if info:
			base += f"\n       >> {info}"
	return base


def get_server_world_tree(client: RpcnClient, com_id: str) -> dict[int, list[int]]:
	"""Fetch the server → world hierarchy.  Returns {server_id: [world_ids]}."""
	servers = client.get_server_list(com_id)
	tree = {}
	for server_id in servers:
		tree[server_id] = client.get_world_list(com_id, server_id)
	return tree


def get_rooms(client: RpcnClient, com_id: str, worlds: list[int]) -> dict[int, SearchRoomsResult]:
	"""Search active rooms across all worlds.  Returns {world_id: result}, skipping empty/failed."""
	results = {}
	for world_id in worlds:
		try:
			resp = client.search_rooms(com_id, world_id=world_id, max_results=20)
			if resp.total > 0:
				results[world_id] = resp
		except RpcnError:
			pass
	return results


def get_leaderboard(client: RpcnClient, com_id: str, board_id: int, num_ranks: int = 10) -> TTT2LeaderboardResult:
	"""Fetch the top N leaderboard entries with parsed TTT2 game_info."""
	result = client.get_score_range(
		com_id, board_id,
		start_rank=1, num_ranks=num_ranks,
		with_comment=True, with_game_info=True,
	)
	entries = [
		TTT2LeaderboardEntry(
			rank=e.rank, np_id=e.np_id, online_name=e.online_name,
			score=e.score, pc_id=e.pc_id, record_date=e.record_date,
			has_game_data=e.has_game_data, comment=e.comment,
			player_info=parse_game_info(e.game_info) if e.game_info else None,
		)
		for e in result.entries
	]
	return TTT2LeaderboardResult(
		total_records=result.total_records,
		last_sort_date=result.last_sort_date,
		entries=entries,
	)


# ---------------------------------------------------------------------------
# API config
# ---------------------------------------------------------------------------

_HOST = os.getenv("RPCN_HOST", "np.rpcs3.net")
_PORT = int(os.getenv("RPCN_PORT", "31313"))

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_redis_client = _redis.from_url(_REDIS_URL, decode_responses=True)

_TTL = {
	"servers":     int(os.getenv("CACHE_TTL_SERVERS",     "3600")),
	"leaderboard": int(os.getenv("CACHE_TTL_LEADERBOARD", "300")),
	"rooms":       int(os.getenv("CACHE_TTL_ROOMS",       "60")),
	"rooms_all":   int(os.getenv("CACHE_TTL_ROOMS_ALL",   "60")),
}


def _cache_get(key: str):
	try:
		raw = _redis_client.get(key)
		return json.loads(raw) if raw else None
	except Exception as e:
		logging.warning("Redis get failed: %s", e)
		return None


def _cache_set(key: str, value, ttl: int):
	try:
		_redis_client.setex(key, ttl, json.dumps(value))
	except Exception as e:
		logging.warning("Redis set failed: %s", e)


@contextmanager
def _api_client():
	"""Open an authenticated RpcnClient for an API request."""
	user = os.environ["RPCN_USER"]
	password = os.environ["RPCN_PASSWORD"]
	token = os.getenv("RPCN_TOKEN", "")
	with RpcnClient(host=_HOST, port=_PORT) as client:
		try:
			client.connect()
			client.login(user, password, token)
			yield client
		except RpcnError as exc:
			raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

app = FastAPI(
	title="Tekken Tag Tournament 2 RPCN API",
	description="Live data from the RPCN multiplayer server for TTT2.",
)


@app.get("/servers", summary="Server and world list")
def servers(com_id: str = Query(default=TTT2_COM_ID, description="Game comm ID")):
	"""Return the server → world hierarchy for the given comm ID."""
	key = f"ttt2:servers:{com_id}"
	if cached := _cache_get(key):
		return cached
	with _api_client() as client:
		tree = get_server_world_tree(client, com_id)
	result = {str(k): v for k, v in tree.items()}
	_cache_set(key, result, _TTL["servers"])
	return result


@app.get("/rooms", summary="Active rooms")
def rooms(com_id: str = Query(default=TTT2_COM_ID, description="Game comm ID")):
	"""Return all active rooms across every world for the given comm ID."""
	key = f"ttt2:rooms:{com_id}"
	if cached := _cache_get(key):
		return cached
	with _api_client() as client:
		tree = get_server_world_tree(client, com_id)
		all_worlds = [w for worlds in tree.values() for w in worlds]
		room_map = get_rooms(client, com_id, all_worlds)
	result = {str(world_id): resp for world_id, resp in room_map.items()}
	_cache_set(key, jsonable_encoder(result), _TTL["rooms"])
	return result


@app.get("/rooms/all", summary="All rooms including hidden")
def rooms_all(
	com_id: str = Query(default=TTT2_COM_ID, description="Game comm ID"),
	world_id: int = Query(default=0, description="World ID (0 = any)"),
	start_index: int = Query(default=1, ge=1, description="Pagination start index"),
	max_results: int = Query(default=20, ge=1, le=20, description="Max results (capped at 20)"),
):
	"""Search all rooms including hidden ones via SearchRoomAll."""
	key = f"ttt2:rooms_all:{com_id}:{world_id}:{start_index}:{max_results}"
	if cached := _cache_get(key):
		return cached
	with _api_client() as client:
		resp = client.search_rooms_all(
			com_id,
			world_id=world_id,
			start_index=start_index,
			max_results=max_results,
		)
	_cache_set(key, jsonable_encoder(resp), _TTL["rooms_all"])
	return resp


@app.get("/leaderboard", summary="Leaderboard entries")
def leaderboard(
	com_id: str = Query(default=TTT2_COM_ID, description="Game comm ID"),
	board: int = Query(default=TTT2_BOARD_ID, description="Score board ID"),
	top: int = Query(default=10, ge=1, le=100, description="Number of entries to return"),
):
	"""Return the top N leaderboard entries with TTT2 character info decoded."""
	key = f"ttt2:leaderboard:{com_id}:{board}:{top}"
	if cached := _cache_get(key):
		return cached
	with _api_client() as client:
		lb = get_leaderboard(client, com_id, board, num_ranks=top)
	_cache_set(key, jsonable_encoder(lb), _TTL["leaderboard"])
	return lb
