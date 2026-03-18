"""Singleton RPCN client lifecycle management."""
import logging
import time
import threading
from contextlib import contextmanager

from fastapi import HTTPException
from rpcn_client import RpcnClient, RpcnError
from env import get_settings
from tekken_tt2.metrics import TrackedRpcnClient

logger = logging.getLogger(__name__)

_client_lock = threading.Lock()
_shared_client: RpcnClient | None = None
_RECONNECT_COOLDOWN = 5.0  # seconds
_last_failure: float = 0.0


def shutdown_client():
    """Disconnect the shared RPCN client if connected."""
    global _shared_client
    with _client_lock:
        if _shared_client is not None:
            try:
                _shared_client.disconnect()
                logger.info("RPCN client disconnected")
            except Exception:
                logger.warning("RPCN disconnect failed", exc_info=True)
            finally:
                _shared_client = None


@contextmanager
def api_client():
    global _shared_client, _last_failure
    settings = get_settings()
    with _client_lock:
        if _shared_client is None:
            elapsed = time.monotonic() - _last_failure
            if _last_failure and elapsed < _RECONNECT_COOLDOWN:
                raise HTTPException(status_code=502, detail=f"RPCN reconnect cooldown ({_RECONNECT_COOLDOWN - elapsed:.1f}s remaining)")
        try:
            if _shared_client is None:
                raw = RpcnClient(host=settings.rpcn_host, port=settings.rpcn_port)
                _shared_client = TrackedRpcnClient(raw)
                _shared_client.connect()
                _shared_client.login(settings.rpcn_user, settings.rpcn_password, settings.rpcn_token)
            yield _shared_client
        except (RpcnError, OSError) as exc:
            logger.error("RPCN connection error: %s", exc)
            if _shared_client is not None:
                try:
                    _shared_client.disconnect()
                except Exception:
                    pass
                _shared_client = None
            _last_failure = time.monotonic()
            raise HTTPException(status_code=502, detail=str(exc)) from exc
