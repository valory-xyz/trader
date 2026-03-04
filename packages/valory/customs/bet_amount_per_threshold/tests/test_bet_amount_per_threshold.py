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

"""Tests for the bet_amount_per_threshold custom strategy."""

from types import NoneType

import pytest

from packages.valory.customs.bet_amount_per_threshold.bet_amount_per_threshold import (
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
        kwargs = {"confidence": 0.8, "bet_amount_per_threshold": {0.8: 100}}
        assert check_missing_fields(kwargs) == []

    def test_all_fields_missing(self) -> None:
        """Empty kwargs returns all required fields."""
        result = check_missing_fields({})
        assert set(result) == set(REQUIRED_FIELDS)

    def test_partial_missing(self) -> None:
        """One field present, one missing."""
        kwargs = {"confidence": 0.8}
        result = check_missing_fields(kwargs)
        assert result == ["bet_amount_per_threshold"]

    def test_none_values_treated_as_missing(self) -> None:
        """Fields with None values are treated as missing."""
        kwargs = {"confidence": None, "bet_amount_per_threshold": {0.8: 100}}
        result = check_missing_fields(kwargs)
        assert result == ["confidence"]


class TestRemoveIrrelevantFields:
    """Tests for remove_irrelevant_fields."""

    def test_keeps_relevant_fields(self) -> None:
        """Only required fields are kept."""
        kwargs = {
            "confidence": 0.8,
            "bet_amount_per_threshold": {0.8: 100},
            "extra_field": "ignored",
        }
        result = remove_irrelevant_fields(kwargs)
        assert result == {"confidence": 0.8, "bet_amount_per_threshold": {0.8: 100}}

    def test_empty_input(self) -> None:
        """Empty input returns empty dict."""
        assert remove_irrelevant_fields({}) == {}

    def test_all_irrelevant(self) -> None:
        """All irrelevant fields returns empty dict."""
        assert remove_irrelevant_fields({"foo": 1, "bar": 2}) == {}


class TestAmountPerThreshold:
    """Tests for amount_per_threshold."""

    def test_int_key_match(self) -> None:
        """Integer key mapping: round(0.8,1)=0.8, int(0.8)=0, looks up key 0."""
        mapping = {1: 100, 0: 50}
        result = amount_per_threshold(0.8, mapping)
        assert result == {"bet_amount": 50}

    def test_float_key_match(self) -> None:
        """Float key mapping returns correct bet amount."""
        mapping = {0.8: 200, 0.9: 300}
        result = amount_per_threshold(0.8, mapping)
        assert result == {"bet_amount": 200}

    def test_str_key_match(self) -> None:
        """String key mapping returns correct bet amount."""
        mapping = {"0.8": 150}
        result = amount_per_threshold(0.8, mapping)
        assert result == {"bet_amount": 150}

    def test_empty_mapping_returns_error(self) -> None:
        """Empty mapping returns NoneType key error."""
        result = amount_per_threshold(0.8, {})
        assert "error" in result

    def test_mixed_key_types_returns_error(self) -> None:
        """Mixed key types in mapping returns error."""
        mapping = {0.8: 100, "0.9": 200}
        result = amount_per_threshold(0.8, mapping)
        assert "error" in result

    def test_unsupported_key_type_returns_error(self) -> None:
        """Unsupported key type (e.g., tuple) returns error."""
        mapping = {(1,): 100}
        result = amount_per_threshold(0.8, mapping)
        assert "error" in result

    def test_no_matching_threshold_returns_error(self) -> None:
        """No matching threshold in mapping returns error."""
        mapping = {0.5: 100}
        result = amount_per_threshold(0.8, mapping)
        assert "error" in result

    def test_confidence_rounding(self) -> None:
        """Confidence is rounded to 1 decimal place for lookup."""
        mapping = {0.8: 100}
        # 0.849... rounds to 0.8
        result = amount_per_threshold(0.849, mapping)
        assert result == {"bet_amount": 100}

    def test_nan_confidence_with_int_keys_returns_error(self) -> None:
        """NaN confidence with int keys triggers ValueError in int(nan)."""
        mapping = {1: 100}
        result = amount_per_threshold(float("nan"), mapping)
        assert "error" in result


class TestRun:
    """Tests for run entry point."""

    def test_missing_fields_returns_error(self) -> None:
        """Missing required fields returns error."""
        result = run()
        assert "error" in result

    def test_partial_missing_returns_error(self) -> None:
        """Partially missing fields returns error with field names."""
        result = run(confidence=0.8)
        assert "error" in result
        assert "bet_amount_per_threshold" in result["error"][0]

    def test_successful_run(self) -> None:
        """Successful run returns bet_amount."""
        result = run(confidence=0.8, bet_amount_per_threshold={0.8: 100})
        assert result == {"bet_amount": 100}

    def test_extra_kwargs_ignored(self) -> None:
        """Extra kwargs are filtered out before processing."""
        result = run(
            confidence=0.8,
            bet_amount_per_threshold={0.8: 100},
            extra="ignored",
        )
        assert result == {"bet_amount": 100}

    def test_positional_args_ignored(self) -> None:
        """Positional args are accepted but ignored."""
        result = run("ignored", confidence=0.8, bet_amount_per_threshold={0.8: 100})
        assert result == {"bet_amount": 100}
