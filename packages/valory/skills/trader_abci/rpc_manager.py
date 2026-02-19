# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2026 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""RPC manager with multi-endpoint rotation for Web3 direct calls.

Provides per-chain Web3 instance caching and automatic failover
when multiple RPC endpoints are provided (comma-separated).
"""

import logging
import threading
import time
from typing import Callable, Dict, List, Optional, TypeVar

from web3 import Web3


_logger = logging.getLogger(__name__)

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Error classification signals
# ---------------------------------------------------------------------------

RATE_LIMIT_SIGNALS = ("429", "rate limit", "too many requests", "ratelimit")

CONNECTION_SIGNALS = (
    "timeout",
    "timed out",
    "connection refused",
    "connection reset",
    "connection error",
    "connection aborted",
    "name resolution",
    "dns",
    "no route to host",
    "network unreachable",
    "max retries exceeded",
    "read timeout",
    "connect timeout",
    "remote end closed",
    "broken pipe",
    "404",
    "not found",
)

QUOTA_SIGNALS = (
    "exceeded the quota",
    "exceeded quota",
    "quota usage",
    "quota exceeded",
    "allowance exceeded",
)

SERVER_ERROR_SIGNALS = (
    "500",
    "502",
    "503",
    "504",
    "internal server error",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
)

FD_EXHAUSTION_SIGNALS = ("too many open files", "oserror(24", "errno 24")

# ---------------------------------------------------------------------------
# Backoff durations (seconds)
# ---------------------------------------------------------------------------

RATE_LIMIT_BACKOFF = 10.0
QUOTA_EXCEEDED_BACKOFF = 300.0
CONNECTION_ERROR_BACKOFF = 30.0
SERVER_ERROR_BACKOFF = 15.0
FD_EXHAUSTION_BACKOFF = 60.0

_BACKOFF_MAP: Dict[str, float] = {
    "rate_limit": RATE_LIMIT_BACKOFF,
    "connection": CONNECTION_ERROR_BACKOFF,
    "quota": QUOTA_EXCEEDED_BACKOFF,
    "server": SERVER_ERROR_BACKOFF,
    "fd_exhaustion": FD_EXHAUSTION_BACKOFF,
}

# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------

MAX_RETRIES = 6
RETRY_DELAY = 1.0
MAX_RETRY_DELAY = 5.0
ROTATION_COOLDOWN = 2.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_rpc_urls(rpc_string: str) -> List[str]:
    """Parse a single URL or comma-separated list into a list of URLs."""
    if "," in rpc_string:
        urls = [url.strip() for url in rpc_string.split(",") if url.strip()]
        return urls if urls else [rpc_string]
    return [rpc_string.strip()]


def classify_error(error: Exception) -> str:
    """Classify an RPC error into a category.

    Returns one of: ``"rate_limit"``, ``"connection"``, ``"quota"``,
    ``"server"``, ``"fd_exhaustion"``, or ``"unknown"``.
    """
    err_text = str(error).lower()
    if any(s in err_text for s in FD_EXHAUSTION_SIGNALS):
        return "fd_exhaustion"
    if any(s in err_text for s in RATE_LIMIT_SIGNALS):
        return "rate_limit"
    if any(s in err_text for s in QUOTA_SIGNALS):
        return "quota"
    if any(s in err_text for s in CONNECTION_SIGNALS):
        return "connection"
    if any(s in err_text for s in SERVER_ERROR_SIGNALS):
        return "server"
    return "unknown"


# ---------------------------------------------------------------------------
# RPCManager
# ---------------------------------------------------------------------------


class _ChainState:
    """Per-chain rotation state."""

    __slots__ = (
        "rpc_urls",
        "current_index",
        "backoff_until",
        "last_rotation_time",
        "w3",
    )

    def __init__(self, rpc_urls: List[str]) -> None:
        self.rpc_urls = rpc_urls
        self.current_index = 0
        self.backoff_until: Dict[int, float] = {}
        self.last_rotation_time = 0.0
        self.w3 = Web3(Web3.HTTPProvider(rpc_urls[0]))


class RPCManager:
    """Manages Web3 instances with multi-RPC rotation per chain.

    Usage::

        manager = RPCManager()
        manager.register_chain("gnosis", "https://rpc1,https://rpc2")
        w3 = manager.get_web3("gnosis")
        result = manager.execute_with_rotation("gnosis", lambda w3: w3.eth.block_number, "get_block")
    """

    def __init__(self) -> None:
        self._chains: Dict[str, _ChainState] = {}
        self._lock = threading.Lock()

    def register_chain(
        self,
        chain: str,
        rpc_string: str,
        chain_id: Optional[int] = None,
    ) -> None:
        """Register a chain with one or more comma-separated RPC URLs.

        If *chain_id* is provided, the RPC list is enriched with
        validated public endpoints from Chainlist.org.
        """
        if chain in self._chains:
            return  # already registered
        from packages.valory.skills.trader_abci.chainlist import (  # lazy import
            enrich_rpc_urls,
        )

        rpc_urls = parse_rpc_urls(rpc_string)
        rpc_urls = enrich_rpc_urls(rpc_urls, chain_id=chain_id)
        self._chains[chain] = _ChainState(rpc_urls)
        if len(rpc_urls) > 1:
            _logger.info(
                "Registered chain %s with %d RPCs (rotation enabled)",
                chain,
                len(rpc_urls),
            )

    def get_web3(self, chain: str) -> Optional[Web3]:
        """Return the cached Web3 instance for *chain*."""
        state = self._chains.get(chain)
        return state.w3 if state else None

    # ------------------------------------------------------------------
    # Rotation internals
    # ------------------------------------------------------------------

    def _is_healthy(self, state: _ChainState, index: int) -> bool:
        return time.monotonic() >= state.backoff_until.get(index, 0.0)

    def _mark_backoff(self, state: _ChainState, index: int, seconds: float) -> None:
        state.backoff_until[index] = time.monotonic() + seconds

    def _rotate(self, chain: str) -> bool:
        """Rotate to next healthy RPC for *chain*. Returns True if rotated."""
        state = self._chains.get(chain)
        if state is None:
            return False

        with self._lock:
            n = len(state.rpc_urls)
            if n <= 1:
                return False

            now = time.monotonic()
            if now - state.last_rotation_time < ROTATION_COOLDOWN:
                return False

            best: Optional[int] = None
            for offset in range(1, n):
                candidate = (state.current_index + offset) % n
                if self._is_healthy(state, candidate):
                    best = candidate
                    break

            if best is None:
                best = min(
                    (i for i in range(n) if i != state.current_index),
                    key=lambda i: state.backoff_until.get(i, 0.0),
                )

            state.current_index = best
            state.w3 = Web3(Web3.HTTPProvider(state.rpc_urls[best]))
            state.last_rotation_time = now
            _logger.info("Rotated %s RPC to #%d: %s", chain, best, state.rpc_urls[best])
            return True

    def _handle_error(self, chain: str, error: Exception, operation: str) -> bool:
        """Classify error, apply backoff, rotate. Returns True if should retry."""
        state = self._chains.get(chain)
        if state is None:
            return False

        category = classify_error(error)

        if category == "fd_exhaustion":
            _logger.error("FD exhaustion — pausing ALL RPCs for %s", chain)
            for i in range(len(state.rpc_urls)):
                self._mark_backoff(state, i, FD_EXHAUSTION_BACKOFF)
            return True

        if category == "unknown":
            return False

        backoff = _BACKOFF_MAP.get(category, 0.0)
        self._mark_backoff(state, state.current_index, backoff)
        _logger.warning(
            "%s RPC #%d %s error (backoff %ds) during %s: %.120s",
            chain,
            state.current_index,
            category.upper(),
            int(backoff),
            operation,
            str(error),
        )
        self._rotate(chain)
        return True

    # ------------------------------------------------------------------
    # Public execution wrapper
    # ------------------------------------------------------------------

    def execute_with_rotation(
        self,
        chain: str,
        operation: Callable[[Web3], T],
        operation_name: str = "rpc_call",
        is_write: bool = False,
    ) -> Optional[T]:
        """Execute *operation(w3)* with RPC rotation and retry logic.

        For **read** operations: retries across RPCs on recoverable errors.
        For **write** operations (``is_write=True``): retries only on clear
        connection failures.

        Returns ``None`` if the chain is not registered or all retries are exhausted.
        """
        state = self._chains.get(chain)
        if state is None:
            _logger.error("Chain %s not registered", chain)
            return None

        n = len(state.rpc_urls)
        if n <= 1:
            # Single RPC — direct call, no retry wrapper
            return operation(state.w3)

        max_retries = min(MAX_RETRIES, n * 2)
        last_error: Optional[Exception] = None

        for attempt in range(max_retries + 1):
            try:
                return operation(state.w3)
            except Exception as exc:
                last_error = exc
                category = classify_error(exc)

                if is_write and category not in ("connection", "fd_exhaustion"):
                    raise

                should_retry = self._handle_error(chain, exc, operation_name)
                if not should_retry or attempt >= max_retries:
                    raise

                delay = min(RETRY_DELAY * (2**attempt), MAX_RETRY_DELAY)
                _logger.info(
                    "%s attempt %d failed, retrying in %.1fs …",
                    operation_name,
                    attempt + 1,
                    delay,
                )
                time.sleep(delay)

        raise last_error  # type: ignore[misc]
