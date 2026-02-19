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

"""Tests for the Chainlist RPC enrichment module."""

import json
from unittest.mock import MagicMock, patch

from packages.valory.skills.trader_abci.chainlist import (
    ChainlistRPC,
    MAX_CHAINLIST_CANDIDATES,
    RPCNode,
    _filter_candidates,
    _is_template_url,
    _normalize_url,
    _rank_and_select,
    enrich_rpc_urls,
    probe_rpc,
)


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


class TestNormalizeUrl:
    """Tests for _normalize_url."""

    def test_strips_trailing_slash(self) -> None:
        """Trailing slash is stripped."""
        assert _normalize_url("https://rpc.example.com/") == "https://rpc.example.com"

    def test_lowercases(self) -> None:
        """URL is lowercased."""
        assert _normalize_url("https://RPC.Example.COM") == "https://rpc.example.com"

    def test_no_change_needed(self) -> None:
        """Already-normalized URL is unchanged."""
        assert _normalize_url("https://rpc.example.com") == "https://rpc.example.com"


class TestIsTemplateUrl:
    """Tests for _is_template_url."""

    def test_dollar_brace(self) -> None:
        """Dollar-brace template is detected."""
        assert _is_template_url("https://rpc.example.com/${API_KEY}") is True

    def test_plain_brace(self) -> None:
        """Plain-brace template is detected."""
        assert _is_template_url("https://rpc.example.com/{key}") is True

    def test_no_template(self) -> None:
        """Plain URL is not a template."""
        assert _is_template_url("https://rpc.example.com") is False


# ---------------------------------------------------------------------------
# probe_rpc
# ---------------------------------------------------------------------------


class TestProbeRpc:
    """Tests for probe_rpc."""

    @patch("packages.valory.skills.trader_abci.chainlist.urllib.request.urlopen")
    def test_success(self, mock_urlopen: MagicMock) -> None:
        """Successful probe returns (url, latency, block)."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"jsonrpc": "2.0", "result": "0x1A4B5C", "id": 1}
        ).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = probe_rpc("https://rpc.example.com")
        assert result is not None
        url, latency, block = result
        assert url == "https://rpc.example.com"
        assert latency > 0
        assert block == 0x1A4B5C

    @patch("packages.valory.skills.trader_abci.chainlist.urllib.request.urlopen")
    def test_timeout_returns_none(self, mock_urlopen: MagicMock) -> None:
        """Timeout returns None."""
        mock_urlopen.side_effect = TimeoutError("timed out")
        assert probe_rpc("https://slow.example.com") is None

    @patch("packages.valory.skills.trader_abci.chainlist.urllib.request.urlopen")
    def test_zero_block_returns_none(self, mock_urlopen: MagicMock) -> None:
        """Block number 0x0 returns None."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"jsonrpc": "2.0", "result": "0x0", "id": 1}
        ).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        assert probe_rpc("https://rpc.example.com") is None


# ---------------------------------------------------------------------------
# RPCNode
# ---------------------------------------------------------------------------


class TestRPCNode:
    """Tests for RPCNode dataclass."""

    def test_tracking_limited(self) -> None:
        """Tracking 'limited' is flagged."""
        node = RPCNode(url="https://x.com", is_working=True, tracking="limited")
        assert node.is_tracking is True

    def test_tracking_none(self) -> None:
        """Tracking 'none' is not flagged."""
        node = RPCNode(url="https://x.com", is_working=True, tracking="none")
        assert node.is_tracking is False

    def test_tracking_default(self) -> None:
        """Default tracking (None) is not flagged."""
        node = RPCNode(url="https://x.com", is_working=True)
        assert node.is_tracking is False


# ---------------------------------------------------------------------------
# _filter_candidates
# ---------------------------------------------------------------------------


class TestFilterCandidates:
    """Tests for _filter_candidates."""

    def test_filters_non_https(self) -> None:
        """Non-HTTPS URLs are filtered out."""
        nodes = [
            RPCNode(url="http://insecure.com", is_working=True),
            RPCNode(url="wss://ws.com", is_working=True),
            RPCNode(url="https://good.com", is_working=True),
        ]
        result = _filter_candidates(nodes, set())
        assert result == ["https://good.com"]

    def test_filters_templates(self) -> None:
        """Template URLs are filtered out."""
        nodes = [
            RPCNode(url="https://rpc.com/${API_KEY}", is_working=True),
            RPCNode(url="https://good.com", is_working=True),
        ]
        result = _filter_candidates(nodes, set())
        assert result == ["https://good.com"]

    def test_deduplicates_existing(self) -> None:
        """Existing URLs are deduplicated."""
        nodes = [
            RPCNode(url="https://already.com", is_working=True),
            RPCNode(url="https://new.com", is_working=True),
        ]
        existing = {"https://already.com"}
        result = _filter_candidates(nodes, existing)
        assert result == ["https://new.com"]

    def test_max_candidates_limit(self) -> None:
        """Candidate list is capped at MAX_CHAINLIST_CANDIDATES."""
        nodes = [
            RPCNode(url=f"https://rpc{i}.com", is_working=True)
            for i in range(MAX_CHAINLIST_CANDIDATES + 10)
        ]
        result = _filter_candidates(nodes, set())
        assert len(result) == MAX_CHAINLIST_CANDIDATES


# ---------------------------------------------------------------------------
# _rank_and_select
# ---------------------------------------------------------------------------


class TestRankAndSelect:
    """Tests for _rank_and_select."""

    def test_sorts_by_latency(self) -> None:
        """Results are sorted by latency (fastest first)."""
        results = [
            ("https://slow.com", 200.0, 1000),
            ("https://fast.com", 10.0, 1000),
            ("https://med.com", 80.0, 1000),
        ]
        selected = _rank_and_select(results, [], chain_id=100, max_results=3)
        assert selected == ["https://fast.com", "https://med.com", "https://slow.com"]

    def test_filters_stale(self) -> None:
        """Stale RPCs lagging behind median block are filtered out."""
        results = [
            ("https://fresh.com", 50.0, 1000),
            ("https://stale.com", 30.0, 900),
            ("https://ok.com", 60.0, 999),
        ]
        selected = _rank_and_select(results, [], chain_id=100, max_results=5)
        assert "https://stale.com" not in selected
        assert "https://fresh.com" in selected

    def test_respects_max_results(self) -> None:
        """Output is capped at max_results."""
        results = [(f"https://rpc{i}.com", float(i), 1000) for i in range(10)]
        selected = _rank_and_select(results, [], chain_id=100, max_results=3)
        assert len(selected) == 3


# ---------------------------------------------------------------------------
# ChainlistRPC
# ---------------------------------------------------------------------------


class TestChainlistRPC:
    """Tests for ChainlistRPC."""

    def test_get_rpcs_parses_nodes(self) -> None:
        """get_rpcs parses RPC entries into RPCNode objects."""
        with patch.object(ChainlistRPC, "fetch_data"):
            cl = ChainlistRPC()
            cl._data = [
                {
                    "chainId": 100,
                    "rpc": [
                        {"url": "https://rpc1.example.com", "tracking": "none"},
                        {"url": "https://rpc2.example.com", "tracking": "yes"},
                    ],
                }
            ]
            result = cl.get_rpcs(100)
            assert len(result) == 2
            assert result[0].url == "https://rpc1.example.com"

    def test_get_rpcs_chain_not_found(self) -> None:
        """Unknown chain_id returns empty list."""
        with patch.object(ChainlistRPC, "fetch_data"):
            cl = ChainlistRPC()
            cl._data = [{"chainId": 1, "rpc": []}]
            assert cl.get_rpcs(999) == []

    @patch.object(ChainlistRPC, "get_rpcs")
    @patch("packages.valory.skills.trader_abci.chainlist.probe_rpc")
    def test_get_validated_rpcs_full_pipeline(
        self, mock_probe: MagicMock, mock_get_rpcs: MagicMock
    ) -> None:
        """Full pipeline: filter → probe → rank → select."""
        mock_get_rpcs.return_value = [
            RPCNode(url="https://rpc.com/${API_KEY}", is_working=True),
            RPCNode(url="https://good1.com", is_working=True),
            RPCNode(url="https://good2.com", is_working=True),
        ]
        mock_probe.side_effect = [
            ("https://good1.com", 100.0, 1000),
            ("https://good2.com", 50.0, 1000),
        ]

        cl = ChainlistRPC()
        result = cl.get_validated_rpcs(100, existing_rpcs=[])
        assert result == ["https://good2.com", "https://good1.com"]

    @patch.object(ChainlistRPC, "get_rpcs")
    def test_returns_empty_on_no_rpcs(self, mock_get_rpcs: MagicMock) -> None:
        """Returns empty when no RPCs exist for chain."""
        mock_get_rpcs.return_value = []
        cl = ChainlistRPC()
        assert cl.get_validated_rpcs(100, existing_rpcs=[]) == []


# ---------------------------------------------------------------------------
# enrich_rpc_urls
# ---------------------------------------------------------------------------


class TestEnrichRpcUrls:
    """Tests for enrich_rpc_urls."""

    def test_no_chain_id_returns_unchanged(self) -> None:
        """No chain_id returns URLs unchanged."""
        urls = ["https://rpc1.com"]
        assert enrich_rpc_urls(urls) is urls

    def test_already_at_max_returns_unchanged(self) -> None:
        """Already at max RPCs returns URLs unchanged."""
        urls = [f"https://rpc{i}.com" for i in range(20)]
        assert enrich_rpc_urls(urls, chain_id=100) is urls

    @patch("packages.valory.skills.trader_abci.chainlist.ChainlistRPC")
    def test_enriches_with_chainlist_rpcs(self, mock_cl_cls: MagicMock) -> None:
        """Chainlist RPCs are appended to the original list."""
        mock_cl = mock_cl_cls.return_value
        mock_cl.get_validated_rpcs.return_value = [
            "https://extra1.com",
            "https://extra2.com",
        ]

        result = enrich_rpc_urls(["https://original.com"], chain_id=100)
        assert result == [
            "https://original.com",
            "https://extra1.com",
            "https://extra2.com",
        ]

    @patch("packages.valory.skills.trader_abci.chainlist.ChainlistRPC")
    def test_survives_failure(self, mock_cl_cls: MagicMock) -> None:
        """Enrichment failure returns original URLs."""
        mock_cl_cls.side_effect = Exception("network error")
        urls = ["https://rpc1.com"]
        result = enrich_rpc_urls(urls, chain_id=100)
        assert result == ["https://rpc1.com"]


# ---------------------------------------------------------------------------
# Integration: RPCManager.register_chain with chain_id
# ---------------------------------------------------------------------------


class TestRPCManagerChainlistIntegration:
    """Test that register_chain enriches RPCs when chain_id is given."""

    @patch("packages.valory.skills.trader_abci.chainlist.ChainlistRPC")
    def test_register_chain_enriches_with_chain_id(
        self, mock_cl_cls: MagicMock
    ) -> None:
        """register_chain enriches RPCs when chain_id is provided."""
        from packages.valory.skills.trader_abci.rpc_manager import RPCManager

        mock_cl = mock_cl_cls.return_value
        mock_cl.get_validated_rpcs.return_value = ["https://extra.com"]

        mgr = RPCManager()
        mgr.register_chain("gnosis", "https://original.com", chain_id=100)

        assert mgr.get_web3("gnosis") is not None

    @patch("packages.valory.skills.trader_abci.chainlist.ChainlistRPC")
    def test_register_chain_no_chain_id_no_enrichment(
        self, mock_cl_cls: MagicMock
    ) -> None:
        """register_chain skips enrichment when no chain_id is given."""
        from packages.valory.skills.trader_abci.rpc_manager import RPCManager

        mgr = RPCManager()
        mgr.register_chain("gnosis", "https://only.com")

        mock_cl_cls.assert_not_called()
