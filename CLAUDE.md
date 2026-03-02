# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
pip install -r requirements.txt
python -m grpc_tools.protoc -I. --python_out=. np2_structs.proto
```

The second command generates `np2_structs_pb2.py` (not committed). This file is required by the `search_rooms`, `get_score_range`, and `get_score_npid` methods. It must be regenerated whenever `np2_structs.proto` changes.

## Running

```bash
# CLI smoke test (connect + login + disconnect)
python rpcn_client.py --user YOUR_USER --password YOUR_PASS

# Optional flags
python rpcn_client.py --host rpcn.rpcs3.net --port 31313 --user U --password P --token T
```

## Architecture

This is a single-file Python client (`rpcn_client.py`) for [RPCN](https://github.com/RPCS3/rpcn), the PSN-compatible multiplayer server used by the RPCS3 emulator. The original RPCN server source is located at `C:/project/rpcn`.

### Binary protocol framing

All packets share a 15-byte little-endian header (`<BHIQ`):

| Field | Type | Description |
|-------|------|-------------|
| `pkt_type` | u8 | 0=Request, 1=Reply, 2=Notification, 3=ServerInfo |
| `cmd` | u16 | CommandType enum (see constants in `rpcn_client.py`) |
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
