# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pip install -e .
.venv/Scripts/python.exe -m grpc_tools.protoc -I. --python_out=src/rpcn_client np2_structs.proto
```

The last command generates `src/rpcn_client/np2_structs_pb2.py` (not committed). This file is required by the `search_rooms`, `get_score_range`, and `get_score_npid` methods. It must be regenerated whenever `np2_structs.proto` changes.

## Python environment

Always use the project virtual environment when running Python commands:

```bash
.venv/Scripts/python.exe -m pytest ...
.venv/Scripts/python.exe -m rpcn_client ...
.venv/Scripts/python.exe -m grpc_tools.protoc ...
```

## Running

```bash
# Start the TTT2 API server
RPCN_USER=U RPCN_PASSWORD=P .venv/Scripts/python.exe -m tekken_tt2

# Or with uvicorn directly (supports --reload)
RPCN_USER=U RPCN_PASSWORD=P .venv/Scripts/python.exe -m uvicorn tekken_tt2.app:app --reload

# RPCN client CLI smoke test (connect + login + disconnect)
.venv/Scripts/python.exe -m rpcn_client --user YOUR_USER --password YOUR_PASS
```

## Tests

```bash
.venv/Scripts/python.exe -m pytest tests/ -v
```

## Architecture

This is a Python package (`src/rpcn_client/`) for [RPCN](https://github.com/RPCS3/rpcn), the PSN-compatible multiplayer server used by the RPCS3 emulator. The original RPCN server source is located at `C:/project/rpcn`.

### Package modules

| Module | Contents |
|--------|----------|
| `constants.py` | `HEADER_SIZE`, `PKT_*`, `CMD_*`, `ERR_*`, `_HDR_FMT` |
| `exceptions.py` | `RpcnError` |
| `utils.py` | `_format_epoch` |
| `models.py` | `LoginInfo`, `RoomAttr`, `RoomBinAttr`, `RoomInfo`, `SearchRoomsResult`, `ScoreEntry`, `ScoreResult` |
| `helpers.py` | `_encode_com_id`, `_read_cstr`, `_pack_protobuf`, `_unpack_data_packet`, `_score_response_to_dto`, `_import_pb2` |
| `client.py` | `RpcnClient` class |
| `__init__.py` | re-exports full public API |
| `__main__.py` | CLI entry point (`python -m rpcn_client`) |

### Binary protocol framing

All packets share a 15-byte little-endian header (`<BHIQ`):

| Field | Type | Description |
|-------|------|-------------|
| `pkt_type` | u8 | 0=Request, 1=Reply, 2=Notification, 3=ServerInfo |
| `cmd` | u16 | CommandType enum (see `constants.py`) |
| `total_size` | u32 | Header + payload bytes |
| `packet_id` | u64 | Monotonically increasing per-connection counter |

TLS is used with `CERT_NONE` because RPCN uses a self-signed certificate.

### Two payload formats

- **Simple commands** (server list, world list): raw `struct.pack` little-endian integers
- **Complex commands** (rooms, scores): protobuf message serialized with a u32 LE length prefix. Use `_pack_protobuf()` to serialize and `_unpack_data_packet()` to deserialize.

### Notification handling

`_recv_reply()` silently discards `PKT_NOTIF` (type 2) packets. The server can push async notifications (friend status changes, room events) between request/reply pairs, so the reply loop must skip them rather than erroring.

### Comm IDs

Game communication IDs are exactly 12 ASCII bytes (e.g. `NPWR04850_00`). Use `_encode_com_id()` to validate and encode them; it is prepended to most request payloads.
