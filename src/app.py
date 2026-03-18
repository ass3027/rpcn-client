"""Tekken Tag Tournament 2 RPCN queries and API server.

Credentials are read from environment variables (or a .env file):
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
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tekken_tt2.cache import redis_health_check
from tekken_tt2.client import shutdown_client
from tekken_tt2.router import router as ttt2_router
from env import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

logger.info("Settings:\n%s", json.dumps(get_settings().model_dump(), indent=2, default=str))

try:
    redis_health_check()
except Exception:
    logger.critical("Shutting down: Redis is unavailable")
    os._exit(1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    shutdown_client()


app = FastAPI(
    title="Tekken Tag Tournament 2 RPCN API",
    description="Live data from the RPCN multiplayer server for TTT2.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ttt2_router)


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}
