# rpcn-client

A Python client for [RPCN](https://github.com/RPCS3/rpcn), the PSN-compatible multiplayer server used by the [RPCS3](https://rpcs3.net) emulator.

Implements the RPCN binary protocol over TLS to query server/world lists, active rooms, and leaderboards. Includes a FastAPI application that exposes Tekken Tag Tournament 2 RPCN data as a REST API.

## Structure

```
src/rpcn_client/       # Core library — RPCN TCP transport
src/tekken_tt2/        # TTT2 REST API server (FastAPI + Redis cache)
  app.py               # FastAPI endpoints
  data.py              # TTT2 character ID → name table
  __main__.py          # python -m tekken_tt2 entry point
tests/
  test_rpcn_client.py  # Integration tests for the core client
  test_tekken_tt2.py   # Integration tests for TTT2 query functions
```

## Setup

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pip install -e .

# Generate protobuf bindings (required for rooms and leaderboard endpoints)
.venv/Scripts/python.exe -m grpc_tools.protoc -I. --python_out=src/rpcn_client np2_structs.proto
```

## TTT2 API server

### Requirements

- Redis (for caching)

```bash
docker run -d -p 6379:6379 redis
```

### Run

```bash
RPCN_USER=you RPCN_PASSWORD=secret RPCN_TOKEN=yourtoken \
  .venv/Scripts/python.exe -m tekken_tt2 --reload
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/servers` | Server and world hierarchy |
| GET | `/rooms` | Active rooms across all worlds |
| GET | `/rooms/all` | All rooms including hidden ones |
| GET | `/leaderboard` | Top N leaderboard entries with character info |

Interactive docs available at `http://localhost:8000/docs`.

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RPCN_USER` | *(required)* | RPCN username |
| `RPCN_PASSWORD` | *(required)* | RPCN password |
| `RPCN_TOKEN` | `""` | RPCN token |
| `RPCN_HOST` | `np.rpcs3.net` | RPCN server host |
| `RPCN_PORT` | `31313` | RPCN server port |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `CACHE_TTL_SERVERS` | `3600` | Server list cache TTL (seconds) |
| `CACHE_TTL_ROOMS` | `60` | Rooms cache TTL (seconds) |
| `CACHE_TTL_ROOMS_ALL` | `60` | Rooms/all cache TTL (seconds) |
| `CACHE_TTL_LEADERBOARD` | `300` | Leaderboard cache TTL (seconds) |

## Library usage

```python
from rpcn_client import RpcnClient

with RpcnClient(host="np.rpcs3.net", port=31313) as client:
    client.connect()
    client.login("username", "password")

    servers = client.get_server_list("NPWR02973_00")
    worlds  = client.get_world_list("NPWR02973_00", servers[0])
    rooms   = client.search_rooms("NPWR02973_00", world_id=worlds[0])
    scores  = client.get_score_range("NPWR02973_00", board_id=0, num_ranks=10)
```

## Tests

Tests connect to a live RPCN server. Edit the credentials at the top of each test file before running.

```bash
.venv/Scripts/python.exe -m pytest tests/ -v
```

## Protocol

RPCN uses a 15-byte little-endian header (`<BHIQ`) over TLS with a self-signed certificate:

| Field | Type | Description |
|-------|------|-------------|
| `pkt_type` | u8 | 0=Request, 1=Reply, 2=Notification, 3=ServerInfo |
| `cmd` | u16 | Command type |
| `total_size` | u32 | Header + payload bytes |
| `packet_id` | u64 | Monotonically increasing counter |

Complex commands (rooms, scores) use a protobuf payload with a u32 LE length prefix.
