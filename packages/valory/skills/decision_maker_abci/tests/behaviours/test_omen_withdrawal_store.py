# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""Tests for ``OmenWithdrawalStore`` — the shared chatui JSON-store I/O."""

from pathlib import Path
from unittest.mock import MagicMock

from packages.valory.skills.decision_maker_abci.behaviours.omen_withdrawal_store import (
    TOP_LEVEL_ERROR_TOKEN_ID,
    OmenWithdrawalStore,
)
from packages.valory.skills.market_manager_abci.graph_tooling.utils import (
    WithdrawablePosition,
)


def _make_store(tmp_path: Path) -> OmenWithdrawalStore:
    """Build a store backed by ``tmp_path`` with a fresh logger mock."""
    return OmenWithdrawalStore(
        store_dir=tmp_path, filename="chatui_param_store.json", logger=MagicMock()
    )


class TestStoreIO:
    """Tests for the raw read/write helpers."""

    def test_read_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """Missing file -> empty dict (not an exception)."""
        store = _make_store(tmp_path)
        assert store.read() == {}

    def test_read_malformed_file_returns_empty(self, tmp_path: Path) -> None:
        """Invalid JSON -> empty dict (not a JSONDecodeError)."""
        store = _make_store(tmp_path)
        store.path().write_text("not-valid-json{")
        assert store.read() == {}

    def test_write_then_read_roundtrip(self, tmp_path: Path) -> None:
        """Write a dict, read it back unchanged."""
        store = _make_store(tmp_path)
        payload = {"withdrawal_state": "selling", "withdrawal_fills": []}
        store.write(payload)
        assert store.read() == payload

    def test_path_uses_dir_and_filename(self, tmp_path: Path) -> None:
        """``path()`` joins dir + filename."""
        store = _make_store(tmp_path)
        assert store.path() == tmp_path / "chatui_param_store.json"


class TestSetState:
    """Tests for ``set_state``."""

    def test_set_state_writes_and_logs(self, tmp_path: Path) -> None:
        """State is persisted to disk and the logger is called."""
        store = _make_store(tmp_path)
        store.set_state("selling")
        assert store.read()["withdrawal_state"] == "selling"
        store._logger.info.assert_called_once()  # type: ignore[attr-defined]

    def test_set_state_preserves_other_fields(self, tmp_path: Path) -> None:
        """Setting state doesn't clobber unrelated keys."""
        store = _make_store(tmp_path)
        store.write({"unrelated": [1, 2, 3]})
        store.set_state("selling")
        data = store.read()
        assert data["unrelated"] == [1, 2, 3]
        assert data["withdrawal_state"] == "selling"


class TestResetSessionRecords:
    """Tests for ``reset_session_records``."""

    def test_reset_clears_fills_and_errors(self, tmp_path: Path) -> None:
        """Both record arrays are zeroed; other keys untouched."""
        store = _make_store(tmp_path)
        store.write(
            {
                "withdrawal_state": "selling",
                "withdrawal_fills": [{"x": 1}],
                "withdrawal_errors": [{"y": 2}],
            }
        )
        store.reset_session_records()
        data = store.read()
        assert data["withdrawal_fills"] == []
        assert data["withdrawal_errors"] == []
        assert data["withdrawal_state"] == "selling"


class TestRecordFill:
    """Tests for ``record_fill``."""

    def test_appends_decoded_event(self, tmp_path: Path) -> None:
        """Fill record carries shares_sold, fill_price, fpmm, outcome_index."""
        store = _make_store(tmp_path)
        store.record_fill(
            {
                "outcome_tokens_sold": 2 * 10**18,
                "return_amount": 5 * 10**17,  # 0.5 wxDAI
                "fee_amount": 10**15,
                "fpmm": "0xabc",
                "outcome_index": 1,
            }
        )
        fills = store.read()["withdrawal_fills"]
        assert len(fills) == 1
        row = fills[0]
        assert row["shares_sold"] == 2.0
        # fill_price = 0.5 / 2.0 = 0.25
        assert row["fill_price"] == 0.25
        assert row["fpmm"] == "0xabc"
        assert row["outcome_index"] == 1
        assert row["return_amount"] == 0.5
        assert row["token_id"] == TOP_LEVEL_ERROR_TOKEN_ID

    def test_zero_shares_gives_zero_fill_price(self, tmp_path: Path) -> None:
        """No shares -> fill_price 0.0 (avoid div-by-zero)."""
        store = _make_store(tmp_path)
        store.record_fill(
            {
                "outcome_tokens_sold": 0,
                "return_amount": 0,
                "fee_amount": 0,
                "fpmm": "0xabc",
                "outcome_index": 0,
            }
        )
        assert store.read()["withdrawal_fills"][0]["fill_price"] == 0.0

    def test_multiple_fills_appended_in_order(self, tmp_path: Path) -> None:
        """Repeated calls accumulate; order preserved."""
        store = _make_store(tmp_path)
        for i in range(3):
            store.record_fill(
                {
                    "outcome_tokens_sold": (i + 1) * 10**18,
                    "return_amount": (i + 1) * 10**17,
                    "fee_amount": 0,
                    "fpmm": f"0x{i}",
                    "outcome_index": 0,
                }
            )
        fills = store.read()["withdrawal_fills"]
        assert [f["fpmm"] for f in fills] == ["0x0", "0x1", "0x2"]


class TestRecordError:
    """Tests for ``record_error``."""

    def _position(self) -> WithdrawablePosition:
        """Build a representative position."""
        return WithdrawablePosition(
            fpmm_address="0xfpmm",
            outcome_index=1,
            balance=3 * 10**18,
            condition_id="0x" + "ab" * 32,
            index_set=2,
            token_id="42",
        )

    def test_per_position_error_recorded(self, tmp_path: Path) -> None:
        """Error row carries token_id, shares_remaining, reason, fpmm."""
        store = _make_store(tmp_path)
        store.record_error(self._position(), "calcSellAmount reverted")
        errors = store.read()["withdrawal_errors"]
        assert len(errors) == 1
        row = errors[0]
        assert row["token_id"] == "42"
        assert row["shares_remaining"] == 3.0
        assert row["reason"] == "calcSellAmount reverted"
        assert row["fpmm"] == "0xfpmm"
        assert row["outcome_index"] == 1
        store._logger.warning.assert_called_once()  # type: ignore[attr-defined]


class TestRecordTopLevelError:
    """Tests for ``record_top_level_error``."""

    def test_top_level_uses_sentinel_token_id(self, tmp_path: Path) -> None:
        """Top-level rows use the empty-string sentinel for token_id."""
        store = _make_store(tmp_path)
        store.record_top_level_error("fetch_user_positions: retries exhausted")
        errors = store.read()["withdrawal_errors"]
        assert len(errors) == 1
        assert errors[0]["token_id"] == TOP_LEVEL_ERROR_TOKEN_ID
        assert errors[0]["shares_remaining"] == 0.0
        assert (
            errors[0]["reason"] == "fetch_user_positions: retries exhausted"
        )
        store._logger.error.assert_called_once()  # type: ignore[attr-defined]


class TestHasErrors:
    """Tests for ``has_errors``."""

    def test_no_errors_returns_false(self, tmp_path: Path) -> None:
        """Empty store -> False."""
        store = _make_store(tmp_path)
        assert store.has_errors() is False

    def test_empty_error_list_returns_false(self, tmp_path: Path) -> None:
        """Initialised but empty list -> False."""
        store = _make_store(tmp_path)
        store.write({"withdrawal_errors": []})
        assert store.has_errors() is False

    def test_non_empty_errors_returns_true(self, tmp_path: Path) -> None:
        """Any persisted error -> True."""
        store = _make_store(tmp_path)
        store.write({"withdrawal_errors": [{"reason": "x"}]})
        assert store.has_errors() is True


class TestPlannedFpmms:
    """Tests for the planned-FPMM allowlist roundtrip."""

    def test_roundtrip_lowercases_and_sorts(self, tmp_path: Path) -> None:
        """Stored addresses are lower-cased and sorted (stable comparison)."""
        store = _make_store(tmp_path)
        store.record_planned_fpmms(
            ["0xAaaa", "0xCCCC", "0xbbbb"]
        )
        assert store.planned_fpmms() == ["0xaaaa", "0xbbbb", "0xcccc"]

    def test_missing_returns_empty_list(self, tmp_path: Path) -> None:
        """No persisted allowlist -> empty list (caller falls back to no filter)."""
        store = _make_store(tmp_path)
        assert store.planned_fpmms() == []

    def test_empty_input_persists_empty_list(self, tmp_path: Path) -> None:
        """``record_planned_fpmms([])`` writes an empty list (legit signal)."""
        store = _make_store(tmp_path)
        store.record_planned_fpmms([])
        assert store.planned_fpmms() == []

    def test_dedupes_repeated_addresses(self, tmp_path: Path) -> None:
        """Duplicate addresses (e.g. one FPMM, two outcomeIndices) are deduped."""
        store = _make_store(tmp_path)
        store.record_planned_fpmms(["0xAAA", "0xaaa", "0xbbb"])
        assert store.planned_fpmms() == ["0xaaa", "0xbbb"]

    def test_filters_falsy_entries(self, tmp_path: Path) -> None:
        """Empty / None addresses are dropped, not persisted as ``""``."""
        store = _make_store(tmp_path)
        store.record_planned_fpmms(["", None, "0xAAA"])  # type: ignore[list-item]
        assert store.planned_fpmms() == ["0xaaa"]

    def test_preserves_other_fields(self, tmp_path: Path) -> None:
        """Recording the allowlist doesn't clobber unrelated keys."""
        store = _make_store(tmp_path)
        store.write({"withdrawal_state": "selling"})
        store.record_planned_fpmms(["0xAAA"])
        data = store.read()
        assert data["withdrawal_state"] == "selling"
        assert data["planned_fpmms"] == ["0xaaa"]


class TestWriteFailureLogsAndContinues:
    """Tests for write resilience."""

    def test_write_failure_logged_not_raised(self, tmp_path: Path) -> None:
        """OSError on write is logged via ``error``, not raised."""
        # Point to a path inside a missing directory; open will OSError.
        store = OmenWithdrawalStore(
            store_dir=tmp_path / "does-not-exist",
            filename="chatui.json",
            logger=MagicMock(),
        )
        # Should not raise.
        store.write({"x": 1})
        store._logger.error.assert_called_once()  # type: ignore[attr-defined]
