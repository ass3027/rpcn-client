"""Tekken Tag Tournament 2 RPCN queries.

Queries the official RPCN server for TTT2 server/world list, active rooms,
and leaderboard scores.

Usage:
  pip install -r requirements.txt
  python -m grpc_tools.protoc -I. --python_out=. np2_structs.proto
  python tekken_tt2.py --user YOUR_USER --password YOUR_PASS

Comm ID note:
  NPWR04850_00 is the candidate for Tekken Tag Tournament 2 (NPEB01406 / NPUB30958).
  If get_server_list() returns an empty list, the comm ID is wrong for your
  region — try the alternate below.  The definitive source is the game's
  PARAM.SFO (NP_COMMUNICATION_ID field) or RPCS3's gamedb.yml.
"""

import argparse
from rpcn_client import RpcnClient, RpcnError

# ---------------------------------------------------------------------------
# Game constants
# ---------------------------------------------------------------------------

# Primary comm ID (EU/US disc — verify against your game's PARAM.SFO)
TTT2_COM_ID = "NPWR02973_00"

# Score board IDs — TTT2 uses board 0 for the main ranking
TTT2_BOARD_ID = 0


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------

def print_server_world_tree(client: RpcnClient, com_id: str) -> list:
	"""Fetch and print the server → world hierarchy.  Returns list of world IDs."""
	servers = client.get_server_list(com_id)
	print(f"\n=== Server list for {com_id} ({len(servers)} server(s)) ===")

	all_worlds = []
	for server_id in servers:
		worlds = client.get_world_list(com_id, server_id)
		print(f"  Server {server_id}: {len(worlds)} world(s) → {worlds}")
		all_worlds.extend(worlds)

	return all_worlds


def print_rooms(client: RpcnClient, com_id: str, worlds: list):
	"""Search and print active rooms across all worlds."""
	print(f"\n=== Active rooms for {com_id} ===")
	total = 0
	for world_id in worlds:
		try:
			resp = client.search_rooms(com_id, world_id=world_id, max_results=20)
			if resp.total == 0:
				continue
			print(f"\n  World {world_id}: {resp.total} room(s) (showing {len(resp.rooms)})")
			for room in resp.rooms:
				print(f"    {room}")
			total += resp.total
		except RpcnError as e:
			print(f"  World {world_id}: search failed — {e}")

	if total == 0:
		print("  (no active rooms found)")


def print_leaderboard(client: RpcnClient, com_id: str, board_id: int, num_ranks: int = 10):
	"""Fetch and print the top N leaderboard entries with full detail."""
	print(f"\n=== Top {num_ranks} leaderboard (board {board_id}) for {com_id} ===")
	try:
		resp = client.get_score_range(
			com_id, board_id,
			start_rank=1, num_ranks=num_ranks,
			with_comment=True, with_game_info=True,
		)
		if resp.total_records == 0:
			print("  (no scores recorded)")
			return
		for line in str(resp).splitlines():
			print(f"  {line}")
	except RpcnError as e:
		print(f"  Leaderboard query failed — {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
	parser = argparse.ArgumentParser(description="Tekken Tag Tournament 2 RPCN queries")
	parser.add_argument("--host",     default="np.rpcs3.net")
	parser.add_argument("--port",     type=int, default=31313)
	parser.add_argument("--user",     required=True, default="lsjin",help="RPCN username")
	parser.add_argument("--password", required=True, default="crecent1",help="RPCN password")
	parser.add_argument("--token",    default="63FE49A5083ECBA0", help="RPCN token (optional)")
	parser.add_argument("--com-id",   default=TTT2_COM_ID,
	                    help=f"Comm ID to query (default: {TTT2_COM_ID})")
	parser.add_argument("--board",    type=int, default=TTT2_BOARD_ID,
	                    help=f"Score board ID (default: {TTT2_BOARD_ID})")
	parser.add_argument("--top",      type=int, default=10,
	                    help="Number of leaderboard entries to display (default: 10)")
	args = parser.parse_args()

	with RpcnClient(host=args.host, port=args.port) as client:
		print(f"Connecting to {args.host}:{args.port} ...")
		version = client.connect()
		print(f"  Protocol version: {version}")

		print(f"Logging in as {args.user!r} ...")
		info = client.login(args.user, args.password, args.token)
		print(f"  Logged in — {info}")

		worlds = print_server_world_tree(client, args.com_id)
		print_rooms(client, args.com_id, worlds)
		print_leaderboard(client, args.com_id, args.board, num_ranks=args.top)

	print("\nDone.")


if __name__ == "__main__":
	main()
