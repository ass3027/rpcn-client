"""RPCN client — minimal Python client for the RPCN PSN multiplayer server.

Protocol reference derived from: https://github.com/RPCS3/rpcn

Quick start:
  pip install -r requirements.txt
  python -m grpc_tools.protoc -I. --python_out=. np2_structs.proto
  python rpcn_client.py --user YOUR_USER --password YOUR_PASS
"""

import ssl
import socket
import struct

# ---------------------------------------------------------------------------
# Protocol constants (must match src/server/client.rs and src/server.rs)
# ---------------------------------------------------------------------------

HEADER_SIZE      = 15   # bytes
PROTOCOL_VERSION = 30

# PacketType values
PKT_REQUEST    = 0
PKT_REPLY      = 1
PKT_NOTIF      = 2
PKT_SERVERINFO = 3

# CommandType enum values (0-indexed, see src/server/client.rs)
CMD_LOGIN                  = 0
CMD_TERMINATE              = 1
CMD_GET_SERVER_LIST        = 12
CMD_GET_WORLD_LIST         = 13
CMD_SEARCH_ROOM            = 17
CMD_GET_ROOM_EXTERNAL_LIST = 18
CMD_GET_SCORE_RANGE        = 34
CMD_GET_SCORE_FRIENDS      = 35
CMD_GET_SCORE_NPID         = 36

# ErrorType::NoError
ERR_NO_ERROR = 0

# comm ID is always 12 ASCII bytes, e.g. b"NPWR04850_00"
COMMUNICATION_ID_SIZE = 12

# Header struct layout: u8 pkt_type | u16 cmd | u32 total_size | u64 packet_id
_HDR_FMT = "<BHIQ"  # 1+2+4+8 = 15 bytes


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RpcnError(Exception):
	pass


# ---------------------------------------------------------------------------
# Core client
# ---------------------------------------------------------------------------

class RpcnClient:
	def __init__(self, host: str = "rpcn.rpcs3.net", port: int = 31313):
		self.host = host
		self.port = port
		self._sock = None
		self._packet_id = 0

	# ------------------------------------------------------------------
	# Connection lifecycle
	# ------------------------------------------------------------------

	def connect(self) -> int:
		"""Open a TLS connection and read the server's handshake packet.

		The server immediately sends a 19-byte ServerInfo packet whose 4-byte
		payload is PROTOCOL_VERSION (currently 30).  We verify the version and
		return it.
		"""
		ctx = ssl.create_default_context()
		ctx.check_hostname = False
		ctx.verify_mode = ssl.CERT_NONE  # RPCN uses a self-signed certificate

		raw = socket.create_connection((self.host, self.port), timeout=30)
		self._sock = ctx.wrap_socket(raw, server_hostname=self.host)

		# Read the 15-byte header of the ServerInfo packet
		hdr = self._recv_exact(HEADER_SIZE)
		pkt_type, _cmd, pkt_size, _pkt_id = struct.unpack(_HDR_FMT, hdr)
		if pkt_type != PKT_SERVERINFO:
			raise RpcnError(f"Expected ServerInfo packet (type 3), got {pkt_type}")

		# The payload is PROTOCOL_VERSION as a u32 LE
		payload_size = pkt_size - HEADER_SIZE
		if payload_size < 4:
			raise RpcnError("ServerInfo payload too short")
		payload = self._recv_exact(payload_size)
		(version,) = struct.unpack_from("<I", payload)
		if version != PROTOCOL_VERSION:
			raise RpcnError(f"Protocol version mismatch: server={version}, client={PROTOCOL_VERSION}")
		return version

	def disconnect(self):
		"""Send the Terminate command and close the socket."""
		try:
			self._send(CMD_TERMINATE, b"")
		except Exception:
			pass
		if self._sock:
			self._sock.close()
			self._sock = None

	def __enter__(self):
		return self

	def __exit__(self, *_):
		self.disconnect()

	# ------------------------------------------------------------------
	# Authentication
	# ------------------------------------------------------------------

	def login(self, username: str, password: str, token: str = "") -> dict:
		"""Log in to RPCN.

		Payload: username\\0 password\\0 token\\0  (token is empty for normal login)

		Returns a dict with keys: online_name, avatar_url, user_id.
		Raises RpcnError on failure.
		"""
		payload = (
			username.encode("utf-8") + b"\x00"
			+ password.encode("utf-8") + b"\x00"
			+ token.encode("utf-8") + b"\x00"
		)
		self._send(CMD_LOGIN, payload)
		error, data = self._recv_reply(CMD_LOGIN)
		if error != ERR_NO_ERROR:
			names = {
				5: "LoginError",
				6: "LoginAlreadyLoggedIn",
				7: "LoginInvalidUsername",
				8: "LoginInvalidPassword",
				9: "LoginInvalidToken",
			}
			raise RpcnError(f"Login failed: {names.get(error, f'error {error}')}")

		pos = 0
		online_name, pos = _read_cstr(data, pos)
		avatar_url, pos  = _read_cstr(data, pos)
		(user_id,) = struct.unpack_from("<q", data, pos)
		# The remainder is friend-list data which we don't need to parse here.
		return {"online_name": online_name, "avatar_url": avatar_url, "user_id": user_id}

	# ------------------------------------------------------------------
	# Server / World list
	# ------------------------------------------------------------------

	def get_server_list(self, com_id: str) -> list:
		"""Return a list of server IDs (u16) for the given comm ID string."""
		self._send(CMD_GET_SERVER_LIST, _encode_com_id(com_id))
		error, data = self._recv_reply(CMD_GET_SERVER_LIST)
		if error != ERR_NO_ERROR:
			raise RpcnError(f"GetServerList error {error}")
		(num,) = struct.unpack_from("<H", data, 0)
		return list(struct.unpack_from(f"<{num}H", data, 2))

	def get_world_list(self, com_id: str, server_id: int) -> list:
		"""Return a list of world IDs (u32) for the given comm ID + server."""
		payload = _encode_com_id(com_id) + struct.pack("<H", server_id)
		self._send(CMD_GET_WORLD_LIST, payload)
		error, data = self._recv_reply(CMD_GET_WORLD_LIST)
		if error != ERR_NO_ERROR:
			raise RpcnError(f"GetWorldList error {error}")
		(num,) = struct.unpack_from("<I", data, 0)
		return list(struct.unpack_from(f"<{num}I", data, 4))

	# ------------------------------------------------------------------
	# Rooms
	# ------------------------------------------------------------------

	def search_rooms(self, com_id: str, world_id: int = 0, start_index: int = 1, max_results: int = 20):
		"""Search for active rooms in the given world.

		Returns a SearchRoomResponse protobuf message.
		Requires np2_structs_pb2 (generate with grpc_tools.protoc).
		Note: start_index must be >= 1 (the server rejects 0).
		"""
		pb = _import_pb2()
		req = pb.SearchRoomRequest()
		# Field names match np2_structs.proto exactly
		req.worldId = world_id
		req.rangeFilter_startIndex = max(1, start_index)
		req.rangeFilter_max = min(max_results, 20)  # server caps at 20

		payload = _encode_com_id(com_id) + _pack_protobuf(req)
		self._send(CMD_SEARCH_ROOM, payload)
		error, data = self._recv_reply(CMD_SEARCH_ROOM)
		if error != ERR_NO_ERROR:
			raise RpcnError(f"SearchRoom error {error}")

		resp = pb.SearchRoomResponse()
		resp.ParseFromString(_unpack_data_packet(data))
		return resp

	# ------------------------------------------------------------------
	# Scores / Leaderboards
	# ------------------------------------------------------------------

	def get_score_range(self, com_id: str, board_id: int,
	                    start_rank: int = 1, num_ranks: int = 10,
	                    with_comment: bool = False, with_game_info: bool = False):
		"""Fetch leaderboard entries by rank range.

		Returns a GetScoreResponse protobuf message.
		"""
		pb = _import_pb2()
		req = pb.GetScoreRangeRequest()
		req.boardId    = board_id
		req.startRank  = start_rank
		req.numRanks   = num_ranks
		req.withComment  = with_comment
		req.withGameInfo = with_game_info

		payload = _encode_com_id(com_id) + _pack_protobuf(req)
		self._send(CMD_GET_SCORE_RANGE, payload)
		error, data = self._recv_reply(CMD_GET_SCORE_RANGE)
		if error != ERR_NO_ERROR:
			raise RpcnError(f"GetScoreRange error {error}")

		resp = pb.GetScoreResponse()
		resp.ParseFromString(_unpack_data_packet(data))
		return resp

	def get_score_npid(self, com_id: str, board_id: int, npids: list,
	                   pc_id: int = 0, with_comment: bool = False, with_game_info: bool = False):
		"""Fetch scores for a list of NP IDs.

		Returns a GetScoreResponse protobuf message.
		"""
		pb = _import_pb2()
		req = pb.GetScoreNpIdRequest()
		req.boardId    = board_id
		req.withComment  = with_comment
		req.withGameInfo = with_game_info
		for npid in npids:
			entry = req.npids.add()
			entry.npid = npid
			entry.pcId = pc_id

		payload = _encode_com_id(com_id) + _pack_protobuf(req)
		self._send(CMD_GET_SCORE_NPID, payload)
		error, data = self._recv_reply(CMD_GET_SCORE_NPID)
		if error != ERR_NO_ERROR:
			raise RpcnError(f"GetScoreNpId error {error}")

		resp = pb.GetScoreResponse()
		resp.ParseFromString(_unpack_data_packet(data))
		return resp

	# ------------------------------------------------------------------
	# Internal I/O
	# ------------------------------------------------------------------

	def _send(self, cmd: int, payload: bytes):
		self._packet_id += 1
		total_size = HEADER_SIZE + len(payload)
		header = struct.pack(_HDR_FMT, PKT_REQUEST, cmd, total_size, self._packet_id)
		self._sock.sendall(header + payload)

	def _recv_exact(self, n: int) -> bytes:
		buf = bytearray()
		while len(buf) < n:
			chunk = self._sock.recv(n - len(buf))
			if not chunk:
				raise RpcnError("Connection closed unexpectedly by server")
			buf.extend(chunk)
		return bytes(buf)

	def _recv_reply(self, expected_cmd: int) -> tuple:
		"""Read packets until a Reply for expected_cmd is found.

		Notification packets (type=2) are silently discarded — the server can
		push async notifications (friend status changes, room events) at any time
		between replies.
		"""
		while True:
			hdr = self._recv_exact(HEADER_SIZE)
			pkt_type, cmd, pkt_size, _pkt_id = struct.unpack(_HDR_FMT, hdr)

			payload_size = pkt_size - HEADER_SIZE
			payload = self._recv_exact(payload_size) if payload_size > 0 else b""

			if pkt_type == PKT_NOTIF:
				# Async server push — discard and keep waiting
				continue

			if pkt_type != PKT_REPLY:
				raise RpcnError(f"Unexpected packet type {pkt_type} (expected Reply=1)")

			error_type = payload[0] if payload else 0
			data = payload[1:] if len(payload) > 1 else b""
			return error_type, data


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _encode_com_id(com_id_str: str) -> bytes:
	"""Encode a comm ID string like 'NPWR04850_00' to 12 ASCII bytes."""
	if len(com_id_str) != COMMUNICATION_ID_SIZE:
		raise ValueError(f"comm ID must be exactly {COMMUNICATION_ID_SIZE} chars, got {len(com_id_str)!r}")
	return com_id_str.encode("ascii")


def _read_cstr(data: bytes, pos: int) -> tuple:
	"""Read a null-terminated UTF-8 string starting at *pos* in *data*.

	Returns (string, new_pos).
	"""
	end = data.index(b"\x00", pos)
	return data[pos:end].decode("utf-8", errors="replace"), end + 1


def _pack_protobuf(msg) -> bytes:
	"""Serialize *msg* with a u32 LE length prefix (matches get_protobuf in stream_extractor.rs)."""
	raw = msg.SerializeToString()
	return struct.pack("<I", len(raw)) + raw


def _unpack_data_packet(data: bytes) -> bytes:
	"""Extract the raw protobuf bytes written by Client::add_data_packet.

	add_data_packet prepends a u32 LE length before the protobuf bytes.
	"""
	if len(data) < 4:
		raise RpcnError(f"Data packet too short: {len(data)} bytes")
	(size,) = struct.unpack_from("<I", data, 0)
	return data[4:4 + size]


def _import_pb2():
	"""Import the generated protobuf module, with a helpful error if missing."""
	try:
		import np2_structs_pb2 as pb
		return pb
	except ImportError:
		raise RpcnError(
			"np2_structs_pb2 not found.\n"
			"Generate it with:\n"
			"  python -m grpc_tools.protoc -I. --python_out=. np2_structs.proto"
		)


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
	import argparse

	parser = argparse.ArgumentParser(description="RPCN client smoke test")
	parser.add_argument("--host",     default="rpcn.rpcs3.net")
	parser.add_argument("--port",     type=int, default=31313)
	parser.add_argument("--user",     required=True, help="RPCN username")
	parser.add_argument("--password", required=True, help="RPCN password")
	parser.add_argument("--token",    default="", help="RPCN token (leave blank if not required)")
	args = parser.parse_args()

	client = RpcnClient(host=args.host, port=args.port)

	print(f"Connecting to {args.host}:{args.port} ...")
	version = client.connect()
	print(f"  Protocol version: {version}")

	print(f"Logging in as {args.user!r} ...")
	info = client.login(args.user, args.password, args.token)
	print(f"  online_name : {info['online_name']}")
	print(f"  avatar_url  : {info['avatar_url']}")
	print(f"  user_id     : {info['user_id']}")

	client.disconnect()
	print("Done.")
