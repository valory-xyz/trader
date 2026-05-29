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

"""Classify mech tools as prediction-suitable from their manifest metadata."""

import re
from typing import Any, Dict, Optional, Tuple

_PRED_NEGATION_RE = re.compile(
    r"\bnot\s+(?:a\s+)?prediction\s+(?:tool|model|engine|system)\b|"
    r"\bnever\s+predict(?:ion)?s?\b|"
    r"\bdoes\s+not\s+predict\b|"
    r"\bnot\s+(?:for\s+)?forecast(?:ing)?\b",
    re.IGNORECASE,
)

_PROSE_PREDICT_PREDICATE = re.compile(
    r"\bpredict(?:s|ed|ion|ions|or|ors|ing)?\b|"
    r"\bforecast(?:s|ed|er|ers|ing)?\b|"
    r"\bestimat(?:e|es|ed|ing|or|ors)\b|"
    r"\bassess(?:es|ed|ing|ment|ments)?\b|"
    r"\blikelihood(?:s)?\b|"
    r"\bprobabilit(?:y|ies)\b",
    re.IGNORECASE,
)

_INPUT_DOMAIN_MISMATCH_RE = re.compile(
    r"\bstock(?:s|\s+price)?\b|"
    r"\bequit(?:y|ies)\b|"
    r"\bforex\b|\bfx\s+price\b|"
    r"\bcommodit(?:y|ies)\s+price\b",
    re.IGNORECASE,
)

_RESOLVER_FIELD_RE = re.compile(
    r'"(?:is_valid|is_determinable|has_occurred'
    r'|agreement_ratio|votes|judge_reasoning)"\s*:'
)


def _description(meta: Dict[str, Any]) -> str:
    """Return the tool's top-level description, or empty string."""
    return str(meta.get("description") or "")


def _input_description(meta: Dict[str, Any]) -> str:
    """Return `input.description`, or empty string."""
    return str((meta.get("input") or {}).get("description") or "")


def _result_field(meta: Dict[str, Any], field: str) -> str:
    """Return `output.schema.properties.result.<field>`, or empty string."""
    return str(
        (((meta.get("output") or {}).get("schema") or {}).get("properties") or {})
        .get("result", {})
        .get(field, "")
        or ""
    )


def is_prediction_tool(tool_metadata: Optional[Dict[str, Any]]) -> bool:
    """Return True iff the manifest blob describes a binary-prediction tool."""
    verdict, _ = explain_prediction_tool(tool_metadata)
    return verdict


def explain_prediction_tool(
    tool_metadata: Optional[Dict[str, Any]],
) -> Tuple[bool, str]:
    """Return (verdict, firing-rule-name) for is_prediction_tool."""
    if not tool_metadata:
        return False, "no_metadata"

    desc = _description(tool_metadata)
    example = _result_field(tool_metadata, "example")
    schema_claims_predictor = (
        bool(example) and '"p_yes"' in example and '"p_no"' in example
    )

    if _PRED_NEGATION_RE.search(desc):
        return False, "description_negation"

    if schema_claims_predictor and not _PROSE_PREDICT_PREDICATE.search(desc):
        return False, "schema_prose_corroboration"

    input_desc = _input_description(tool_metadata)
    if not schema_claims_predictor and (
        _INPUT_DOMAIN_MISMATCH_RE.search(input_desc)
        or _INPUT_DOMAIN_MISMATCH_RE.search(desc)
    ):
        return False, "input_domain_mismatch"

    if not schema_claims_predictor and example and _RESOLVER_FIELD_RE.search(example):
        return False, "schema_resolver_shape"

    if _result_field(tool_metadata, "type") == "string" and not example:
        return False, "passthrough_result"

    if schema_claims_predictor:
        return True, "schema_prediction_shape"

    return False, "no_check_fired"
