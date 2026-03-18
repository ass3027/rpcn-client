"""CloudWatch EMF (Embedded Metric Format) metric emission for RPCN client calls."""

from __future__ import annotations

import json
import logging
import time
from functools import wraps
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rpcn_client import RpcnClient

logger = logging.getLogger("emf")

_NAMESPACE = "TAG2NOW"

_TRACKED_METHODS = {
    "connect", "login", "disconnect",
    "get_server_list", "get_world_list",
    "search_rooms", "search_rooms_all",
    "get_score_range", "get_score_npid",
}


def _emit_emf(method: str, duration_ms: float, success: bool):
    """Emit a single CloudWatch EMF structured log entry."""
    emf = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": _NAMESPACE,
                    "Dimensions": [["Method"], ["Method", "Status"]],
                    "Metrics": [
                        {"Name": "CallCount", "Unit": "Count"},
                        {"Name": "Duration", "Unit": "Milliseconds"},
                    ],
                }
            ],
        },
        "Method": method,
        "Status": "Success" if success else "Failure",
        "CallCount": 1,
        "Duration": round(duration_ms, 2),
    }
    logger.info(json.dumps(emf))


class TrackedRpcnClient:
    """Proxy that wraps an RpcnClient and emits EMF metrics for tracked methods."""

    def __init__(self, client: RpcnClient):
        self._client = client

    def __getattr__(self, name: str):
        attr = getattr(self._client, name)
        if name in _TRACKED_METHODS and callable(attr):
            @wraps(attr)
            def wrapper(*args, **kwargs):
                start = time.monotonic()
                success = True
                try:
                    return attr(*args, **kwargs)
                except Exception:
                    success = False
                    raise
                finally:
                    duration_ms = (time.monotonic() - start) * 1000
                    try:
                        _emit_emf(name, duration_ms, success)
                    except Exception:
                        logger.debug("EMF emission failed for %s", name, exc_info=True)
            self.__dict__[name] = wrapper
            return wrapper
        return attr
