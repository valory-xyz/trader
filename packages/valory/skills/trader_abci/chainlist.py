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

"""Chainlist RPC enrichment — fetch, probe, and rank public RPCs.

Optional module that downloads public RPC endpoints from chainlist.org,
validates them with ``eth_blockNumber`` probes, filters stale ones, and
returns the best candidates sorted by latency.  Used as fallback RPCs
for the RPC rotation system.
"""

import json
import logging
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_logger = logging.getLogger(__name__)

# -- Constants -----------------------------------------------------------------

CHAINLIST_URL = "https://chainlist.org/rpcs.json"
CACHE_TTL = 86400  # 24 hours
MAX_CHAINLIST_CANDIDATES = 15
PROBE_TIMEOUT = 5.0  # seconds per probe
MAX_BLOCK_LAG = 10  # blocks behind median → stale
MAX_RPCS = 20  # don't enrich beyond this

_CACHE_DIR = Path(tempfile.gettempdir()) / "trader_chainlist_cache"
_CACHE_PATH = _CACHE_DIR / "rpcs.json"


# -- Helpers -------------------------------------------------------------------


def _normalize_url(url: str) -> str:
    """Lowercase + strip trailing slash for dedup comparison."""
    return url.rstrip("/").lower()


def _is_template_url(url: str) -> bool:
    """Return True if URL has template vars (requires API key)."""
    return "${" in url or "{" in url


def probe_rpc(
    url: str,
    timeout: float = PROBE_TIMEOUT,
) -> Optional[Tuple[str, float, int]]:
    """Probe *url* with ``eth_blockNumber``.

    Returns ``(url, latency_ms, block_number)`` on success, ``None`` on
    failure.

    :param url: RPC endpoint URL to probe.
    :param timeout: request timeout in seconds.
    :return: tuple of (url, latency_ms, block_number) or None on failure.
    """
    payload = json.dumps(
        {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}
    ).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        start = time.monotonic()
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            data = json.loads(resp.read())
        latency_ms = (time.monotonic() - start) * 1000
        block_hex = data.get("result")
        if not block_hex or not isinstance(block_hex, str) or block_hex == "0x0":
            return None
        return (url, latency_ms, int(block_hex, 16))
    except Exception:  # noqa: BLE001
        return None


@dataclass
class RPCNode:
    """A single RPC entry from Chainlist."""

    url: str
    is_working: bool
    tracking: Optional[str] = None

    @property
    def is_tracking(self) -> bool:
        """True if the RPC is known to track user data."""
        return self.tracking in ("limited", "yes")


# -- Pipeline stages -----------------------------------------------------------


def _filter_candidates(
    nodes: List[RPCNode],
    existing_normalized: set,
) -> List[str]:
    """Filter to usable HTTPS candidates, dedup against existing."""
    candidates: List[str] = []
    for node in nodes:
        url = node.url
        if urllib.parse.urlparse(url).scheme != "https":
            continue
        if _is_template_url(url):
            continue
        if _normalize_url(url) in existing_normalized:
            continue
        candidates.append(url)
        if len(candidates) >= MAX_CHAINLIST_CANDIDATES:
            break
    return candidates


def _probe_candidates(candidates: List[str]) -> List[Tuple[str, float, int]]:
    """Probe candidates in parallel, return successful results."""
    results: List[Tuple[str, float, int]] = []
    n_workers = min(len(candidates), 10)
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {pool.submit(probe_rpc, url): url for url in candidates}
        for future in as_completed(futures, timeout=15):
            try:
                result = future.result()
                if result is not None:
                    results.append(result)
            except Exception:  # nosec B110  # noqa: BLE001
                pass
    return results


def _rank_and_select(
    results: List[Tuple[str, float, int]],
    candidates: List[str],
    chain_id: int,
    max_results: int,
) -> List[str]:
    """Rank by latency, filter stale RPCs (>MAX_BLOCK_LAG behind median)."""
    blocks = sorted(r[2] for r in results)
    median_block = blocks[len(blocks) // 2]

    valid = [
        (url, latency)
        for url, latency, block in results
        if median_block - block <= MAX_BLOCK_LAG
    ]
    valid.sort(key=lambda x: x[1])

    selected = [url for url, _ in valid[:max_results]]
    if selected:
        _logger.info(
            "ChainList: validated %d/%d candidates for chain %d (median block: %d)",
            len(selected),
            len(candidates),
            chain_id,
            median_block,
        )
    return selected


# -- Main class ----------------------------------------------------------------


class ChainlistRPC:
    """Fetcher and parser for Chainlist RPC data with local caching."""

    def __init__(self) -> None:
        """Initialise with empty RPC data."""
        self._data: List[Dict[str, Any]] = []

    def fetch_data(self, force_refresh: bool = False) -> None:
        """Fetch RPC data from chainlist.org (cached for 24h)."""
        if not force_refresh and _CACHE_PATH.exists():
            try:
                mtime = _CACHE_PATH.stat().st_mtime
                if time.time() - mtime < CACHE_TTL:
                    with _CACHE_PATH.open("r") as fh:
                        self._data = json.load(fh)
                    if self._data:
                        return
            except Exception:  # nosec B110  # noqa: BLE001
                pass

        try:
            req = urllib.request.Request(CHAINLIST_URL)
            with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
                self._data = json.loads(resp.read())
            if self._data:
                _CACHE_DIR.mkdir(parents=True, exist_ok=True)
                with _CACHE_PATH.open("w") as fh:
                    json.dump(self._data, fh)
        except Exception as exc:  # noqa: BLE001
            _logger.debug("Chainlist fetch failed: %s", exc)
            if not self._data and _CACHE_PATH.exists():
                try:
                    with _CACHE_PATH.open("r") as fh:
                        self._data = json.load(fh)
                except Exception:  # nosec B110  # noqa: BLE001
                    pass
            if not self._data:
                self._data = []

    def get_rpcs(self, chain_id: int) -> List[RPCNode]:
        """Return parsed RPC nodes for *chain_id*."""
        if not self._data:
            self.fetch_data()
        for entry in self._data:
            if entry.get("chainId") == chain_id:
                return [
                    RPCNode(
                        url=rpc.get("url", ""),
                        is_working=True,
                        tracking=rpc.get("tracking"),
                    )
                    for rpc in entry.get("rpc", [])
                ]
        return []

    def get_validated_rpcs(
        self,
        chain_id: int,
        existing_rpcs: List[str],
        max_results: int = 5,
    ) -> List[str]:
        """Return Chainlist RPCs filtered, probed, and sorted by quality.

        Pipeline:
        1. Fetch HTTPS RPCs from Chainlist for *chain_id*.
        2. Filter out template URLs, duplicates, and non-HTTPS.
        3. Probe top candidates in parallel with ``eth_blockNumber``.
        4. Discard stale RPCs (block number lagging behind median).
        5. Return up to *max_results* URLs sorted by latency.

        :param chain_id: numeric EVM chain identifier.
        :param existing_rpcs: URLs already known, used for deduplication.
        :param max_results: maximum number of validated RPCs to return.
        :return: list of validated RPC URLs sorted by latency.
        """
        nodes = self.get_rpcs(chain_id)
        if not nodes:
            return []

        existing_normalized = {_normalize_url(u) for u in existing_rpcs}
        candidates = _filter_candidates(nodes, existing_normalized)
        if not candidates:
            return []

        results = _probe_candidates(candidates)
        if not results:
            return []

        return _rank_and_select(results, candidates, chain_id, max_results)


def enrich_rpc_urls(
    rpc_urls: List[str],
    chain_id: Optional[int] = None,
    max_rpcs: int = MAX_RPCS,
    skip_chainlist: bool = False,
) -> List[str]:
    """Enrich *rpc_urls* with validated public RPCs from Chainlist.

    This is the main entry point for the RPC rotation system.
    Returns the original URLs followed by any Chainlist fallbacks.

    If *chain_id* is ``None`` or enrichment fails, returns *rpc_urls*
    unchanged.

    :param rpc_urls: existing RPC URLs to enrich.
    :param chain_id: numeric EVM chain identifier, or None to skip enrichment.
    :param max_rpcs: upper bound on total RPC URLs to return.
    :param skip_chainlist: disable Chainlist enrichment entirely.
    :return: original URLs followed by any validated Chainlist fallbacks.
    """
    if skip_chainlist:
        _logger.info("Chainlist enrichment disabled via skip_chainlist param")
        return rpc_urls

    if chain_id is None or len(rpc_urls) >= max_rpcs:
        return rpc_urls

    try:
        cl = ChainlistRPC()
        extra = cl.get_validated_rpcs(
            chain_id,
            existing_rpcs=rpc_urls,
            max_results=max_rpcs - len(rpc_urls),
        )
        if extra:
            _logger.info(
                "Enriched with %d Chainlist RPCs (total: %d)",
                len(extra),
                len(rpc_urls) + len(extra),
            )
            return rpc_urls + extra
    except Exception as exc:  # noqa: BLE001
        _logger.debug("Chainlist enrichment failed: %s", exc)

    return rpc_urls
