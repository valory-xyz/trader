# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
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

"""This module contains the test for utils of decision maker"""

import pytest

from packages.valory.skills.decision_maker_abci.policy import (
    AccuracyInfo,
    ConsecutiveFailures,
    EGreedyPolicy,
)


@pytest.fixture
def e_greedy_policy_mock() -> EGreedyPolicy:
    """Mock the e greedy policy."""
    return EGreedyPolicy(
        eps=0.25,
        consecutive_failures_threshold=2,
        quarantine_duration=10800,
        accuracy_store={
            "claude-prediction-offline": AccuracyInfo(
                accuracy=0.57965, pending=-8, requests=521
            ),
            "claude-prediction-online": AccuracyInfo(
                accuracy=0.58541, pending=-2, requests=521
            ),
            "prediction-offline": AccuracyInfo(
                accuracy=0.60845, pending=-26, requests=521
            ),
            "prediction-online": AccuracyInfo(
                accuracy=0.62188, pending=-44, requests=521
            ),
            "prediction-online-sme": AccuracyInfo(
                accuracy=0.54894, pending=0, requests=521
            ),
            "prediction-request-rag": AccuracyInfo(
                accuracy=0.57965, pending=-6, requests=521
            ),
            "prediction-request-reasoning": AccuracyInfo(
                accuracy=0.66411, pending=-1, requests=521
            ),
        },
        consecutive_failures={
            "claude-prediction-offline": ConsecutiveFailures(
                n_failures=0, timestamp=1756130390
            ),
            "claude-prediction-online": ConsecutiveFailures(
                n_failures=0, timestamp=1755469100
            ),
            "prediction-offline": ConsecutiveFailures(
                n_failures=0, timestamp=1755900057
            ),
            "prediction-online": ConsecutiveFailures(
                n_failures=0, timestamp=1755707431
            ),
            "prediction-online-sme": ConsecutiveFailures(
                n_failures=0, timestamp=1755707833
            ),
            "prediction-request-rag": ConsecutiveFailures(
                n_failures=0, timestamp=1755708069
            ),
            "prediction-request-reasoning": ConsecutiveFailures(
                n_failures=0, timestamp=1756202233
            ),
        },
        weighted_accuracy={
            "claude-prediction-offline": 0.0137876404494382,
            "claude-prediction-online": 0.0138535497295048,
            "prediction-offline": 0.0141588014981273,
            "prediction-online": 0.0143402094603967,
            "prediction-online-sme": 0.013401568872243,
            "prediction-request-rag": 0.0137859065057567,
            "prediction-request-reasoning": 0.0148242876959356,
        },
        updated_ts=1756201545,
    )


def test_e_greedy_policy_select_tool_default(
    e_greedy_policy_mock: EGreedyPolicy,
) -> None:
    """Test the default tool selection. Selects the value with biggest weighted accuracy."""
    best_tool = e_greedy_policy_mock.best_tool
    assert best_tool == "prediction-request-reasoning"


def test_e_greedy_policy_select_tool_randomness(
    e_greedy_policy_mock: EGreedyPolicy,
) -> None:
    """Test the tool selection with randomness. Selects the value with biggest weighted accuracy."""
    randomness = 1234567890
    best_tool = e_greedy_policy_mock.select_tool(randomness)
    assert best_tool == "prediction-request-reasoning"


def test_e_greedy_policy_select_tool_weighted_accuracy_zero(
    e_greedy_policy_mock: EGreedyPolicy,
) -> None:
    """Test the tool selection with weighted accuracy near zero. Value would be selected regardles of other tools"""
    e_greedy_policy_mock.weighted_accuracy.update(
        {"prediction-request-reasoning": 0.00000000001}
    )
    e_greedy_policy_mock.update_weighted_accuracy()

    best_tool = e_greedy_policy_mock.best_tool
    assert best_tool == "prediction-request-reasoning"


def test_e_greedy_policy_select_tool_weighted_accuracy_biggest(
    e_greedy_policy_mock: EGreedyPolicy,
) -> None:
    """Test the tool selection with weighted accuracy biggest. Value would be selected regardles of other tools"""
    e_greedy_policy_mock.weighted_accuracy.update({"prediction-request-rag": 0.95})
    e_greedy_policy_mock.update_weighted_accuracy()

    best_tool = e_greedy_policy_mock.best_tool
    assert best_tool == "prediction-request-reasoning"


def test_e_greedy_policy_select_tool_weighted_accuracy_calls_increased(
    e_greedy_policy_mock: EGreedyPolicy,
) -> None:
    """Test the tool selection with weighted accuracy calls decreased. Value would be selected"""
    e_greedy_policy_mock.accuracy_store.update(
        {
            "prediction-request-rag": AccuracyInfo(
                accuracy=0.57965, pending=-6, requests=5021
            ),
            "prediction-request-reasoning": AccuracyInfo(
                accuracy=0.66411, pending=-6, requests=1021
            ),
        }
    )
    e_greedy_policy_mock.update_weighted_accuracy()

    best_tool = e_greedy_policy_mock.best_tool
    assert best_tool == "prediction-request-reasoning"


def test_e_greedy_policy_select_tool_weighted_accuracy_calls_decreased(
    e_greedy_policy_mock: EGreedyPolicy,
) -> None:
    """Test the tool selection with weighted accuracy calls decreased. Value would be selected"""
    e_greedy_policy_mock.accuracy_store.update(
        {
            "prediction-request-rag": AccuracyInfo(
                accuracy=0.57965, pending=-6, requests=5021
            ),
            "prediction-request-reasoning": AccuracyInfo(
                accuracy=0.66411, pending=-6, requests=521
            ),
        }
    )
    e_greedy_policy_mock.update_weighted_accuracy()

    best_tool = e_greedy_policy_mock.best_tool
    assert best_tool == "prediction-request-reasoning"
