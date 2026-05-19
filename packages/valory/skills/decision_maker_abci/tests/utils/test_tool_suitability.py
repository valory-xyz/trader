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

"""Tests for the tool_suitability module of decision_maker_abci."""

from typing import Any, Dict

import pytest

from packages.valory.skills.decision_maker_abci.utils.tool_suitability import (
    explain_prediction_tool,
    is_prediction_tool,
)


def _make_tool(
    description: str = "",
    input_description: str = "The text to make a prediction on",
    result_type: str = "string",
    result_example: str = "",
) -> Dict[str, Any]:
    """Build a minimal manifest blob for a single tool."""
    return {
        "name": "test-tool",
        "description": description,
        "input": {"type": "text", "description": input_description},
        "output": {
            "type": "object",
            "schema": {
                "properties": {
                    "result": {
                        "type": result_type,
                        "example": result_example,
                    }
                }
            },
        },
    }


_PREDICTION_EXAMPLE = (
    '{"p_yes": 0.6, "p_no": 0.4, "confidence": 0.8, "info_utility": 0.6}'
)
_RESOLVER_EXAMPLE = '{"is_valid": true, "is_determinable": true, "has_occurred": true}'


class TestIsPredictionTool:
    """Direct verdict tests for is_prediction_tool."""

    def test_none_metadata(self) -> None:
        """No metadata returns False."""
        assert is_prediction_tool(None) is False

    def test_empty_metadata(self) -> None:
        """Empty dict returns False."""
        assert is_prediction_tool({}) is False

    def test_valid_predictor(self) -> None:
        """A schema declaring p_yes/p_no with prose claiming prediction passes."""
        meta = _make_tool(
            description="A tool for making binary predictions on markets.",
            result_example=_PREDICTION_EXAMPLE,
        )
        assert is_prediction_tool(meta) is True

    def test_description_negation_vetoes(self) -> None:
        """Prose disclaim vetoes even when schema looks correct."""
        meta = _make_tool(
            description="Produces facts only -- never predictions.",
            result_example=_PREDICTION_EXAMPLE,
        )
        assert is_prediction_tool(meta) is False

    def test_schema_prose_corroboration_vetoes(self) -> None:
        """Schema claims predictor but prose never mentions predict/forecast."""
        meta = _make_tool(
            description="A tool that runs a prompt against the OpenAI API.",
            result_example=_PREDICTION_EXAMPLE,
        )
        assert is_prediction_tool(meta) is False

    def test_input_domain_mismatch_vetoes(self) -> None:
        """Stock-domain input is vetoed even with prediction schema."""
        meta = _make_tool(
            description="Stock prediction tool for equities.",
            input_description="A question about stock price movement prediction",
            result_example=_PREDICTION_EXAMPLE,
        )
        assert is_prediction_tool(meta) is False

    def test_resolver_shape_vetoes(self) -> None:
        """Resolver-shaped example overrides any prediction claim."""
        meta = _make_tool(
            description="Multi-model jury tool for resolving prediction markets.",
            result_example=_RESOLVER_EXAMPLE,
        )
        assert is_prediction_tool(meta) is False

    def test_passthrough_vetoes(self) -> None:
        """Bare string output with no example is rejected."""
        meta = _make_tool(
            description="A tool that runs a prompt against an API.",
            result_type="string",
            result_example="",
        )
        assert is_prediction_tool(meta) is False

    def test_fail_closed_on_unknown(self) -> None:
        """Tool with no schema and no clear signal returns False."""
        meta = _make_tool(
            description="Some new tool category.",
            result_type="",
            result_example="",
        )
        assert is_prediction_tool(meta) is False


class TestExplainPredictionTool:
    """Verify the firing-rule names exposed by explain_prediction_tool."""

    @pytest.mark.parametrize(
        "meta,expected_verdict,expected_reason",
        [
            (None, False, "no_metadata"),
            ({}, False, "no_metadata"),
            (
                _make_tool(
                    description="never predictions",
                    result_example=_PREDICTION_EXAMPLE,
                ),
                False,
                "description_negation",
            ),
            (
                _make_tool(
                    description="runs a prompt against an API",
                    result_example=_PREDICTION_EXAMPLE,
                ),
                False,
                "schema_prose_corroboration",
            ),
            (
                _make_tool(
                    description="stock prediction tool",
                    input_description="stock price question",
                    result_example=_PREDICTION_EXAMPLE,
                ),
                False,
                "input_domain_mismatch",
            ),
            (
                _make_tool(
                    description="Resolves markets that have closed.",
                    result_example=_RESOLVER_EXAMPLE,
                ),
                False,
                "schema_resolver_shape",
            ),
            (
                _make_tool(
                    description="Performs a prompt request.",
                    result_type="string",
                    result_example="",
                ),
                False,
                "passthrough_result",
            ),
            (
                _make_tool(
                    description="Makes a prediction on markets.",
                    result_example=_PREDICTION_EXAMPLE,
                ),
                True,
                "schema_prediction_shape",
            ),
            (
                _make_tool(
                    description="Some new tool category.",
                    result_type="",
                    result_example="",
                ),
                False,
                "no_check_fired",
            ),
        ],
    )
    def test_firing_rule(
        self,
        meta: Any,
        expected_verdict: bool,
        expected_reason: str,
    ) -> None:
        """Each manifest variant fires the expected check."""
        verdict, reason = explain_prediction_tool(meta)
        assert verdict is expected_verdict
        assert reason == expected_reason
