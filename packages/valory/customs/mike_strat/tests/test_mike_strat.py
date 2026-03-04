# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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

"""Tests for the mike_strat custom strategy."""

import pytest

from packages.valory.customs.mike_strat.mike_strat import (
    REQUIRED_FIELDS,
    amount_per_threshold,
    check_missing_fields,
    remove_irrelevant_fields,
    run,
)


class TestCheckMissingFields:
    """Tests for check_missing_fields."""

    def test_no_missing_fields(self) -> None:
        """All required fields present returns empty list."""
        kwargs = {"confidence": 0.8, "bet_amount_per_threshold": {"0.8": 100}}
        assert check_missing_fields(kwargs) == []

    def test_all_fields_missing(self) -> None:
        """Empty kwargs returns all required fields."""
        result = check_missing_fields({})
        assert set(result) == set(REQUIRED_FIELDS)

    def test_none_values_treated_as_missing(self) -> None:
        """Fields with None values are treated as missing."""
        kwargs = {"confidence": None, "bet_amount_per_threshold": {"0.8": 100}}
        result = check_missing_fields(kwargs)
        assert result == ["confidence"]


class TestRemoveIrrelevantFields:
    """Tests for remove_irrelevant_fields."""

    def test_keeps_relevant_fields(self) -> None:
        """Only required fields are kept."""
        kwargs = {
            "confidence": 0.8,
            "bet_amount_per_threshold": {"0.8": 100},
            "extra": "ignored",
        }
        result = remove_irrelevant_fields(kwargs)
        assert result == {"confidence": 0.8, "bet_amount_per_threshold": {"0.8": 100}}

    def test_empty_input(self) -> None:
        """Empty input returns empty dict."""
        assert remove_irrelevant_fields({}) == {}


class TestAmountPerThreshold:
    """Tests for amount_per_threshold — multiplies bet_amount by confidence."""

    def test_matching_threshold(self) -> None:
        """Matching threshold returns bet_amount * confidence."""
        result = amount_per_threshold(0.8, {"0.8": 100})
        assert result == {"bet_amount": 100 * 0.8}

    def test_no_matching_threshold(self) -> None:
        """No matching threshold returns error."""
        result = amount_per_threshold(0.9, {"0.5": 100})
        assert "error" in result

    def test_confidence_rounding(self) -> None:
        """Confidence is rounded to 1 decimal for string lookup."""
        result = amount_per_threshold(0.849, {"0.8": 100})
        assert result == {"bet_amount": 100 * 0.849}


class TestRun:
    """Tests for run entry point."""

    def test_missing_fields_returns_error(self) -> None:
        """Missing required fields returns error."""
        result = run()
        assert "error" in result

    def test_successful_run(self) -> None:
        """Successful run returns bet_amount with confidence multiplier."""
        result = run(confidence=0.8, bet_amount_per_threshold={"0.8": 100})
        assert result == {"bet_amount": 100 * 0.8}

    def test_positional_args_ignored(self) -> None:
        """Positional args are accepted but ignored."""
        result = run("ignored", confidence=0.8, bet_amount_per_threshold={"0.8": 100})
        assert result == {"bet_amount": 100 * 0.8}
