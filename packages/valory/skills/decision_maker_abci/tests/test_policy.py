# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025-2026 Valory AG
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

import json
from time import time

import pytest

from packages.valory.skills.decision_maker_abci.policy import (
    AccuracyInfo,
    ConsecutiveFailures,
    DataclassEncoder,
    EGreedyPolicy,
    EGreedyPolicyDecoder,
    argmax,
    describe_tool_key,
    split_tool_key,
    tool_key,
)
from packages.valory.skills.decision_maker_abci.utils.scaling import scale_value

MECH = "0x" + "ab" * 20
OPERATOR = "www.valory.xyz"


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

    best_tool_result = e_greedy_policy_mock.best_tool
    assert best_tool_result == "prediction-request-reasoning"


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


def test_argmax() -> None:
    """Test the argmax function."""
    assert argmax([1, 3, 2]) == 1
    assert argmax([5, 1, 2]) == 0
    assert argmax([1, 2, 5]) == 2


def test_argmax_tuple() -> None:
    """Test the argmax function with tuple input."""
    assert argmax((10, 20, 5)) == 1


def test_dataclass_encoder() -> None:
    """Test the DataclassEncoder with a dataclass."""
    info = AccuracyInfo(requests=10, pending=2, accuracy=0.8)
    encoded = json.dumps(info, cls=DataclassEncoder)
    decoded = json.loads(encoded)
    assert decoded["requests"] == 10
    assert decoded["pending"] == 2
    assert decoded["accuracy"] == 0.8


def test_dataclass_encoder_non_dataclass() -> None:
    """Test the DataclassEncoder falls back for non-dataclass objects."""
    result = json.dumps({"key": "value"}, cls=DataclassEncoder)
    assert json.loads(result) == {"key": "value"}


def test_accuracy_info_defaults() -> None:
    """Test AccuracyInfo default values."""
    info = AccuracyInfo()
    assert info.requests == 0
    assert info.pending == 0
    assert info.accuracy == 0.0


def test_consecutive_failures_increase() -> None:
    """Test ConsecutiveFailures increase."""
    cf = ConsecutiveFailures()
    cf.increase(1000)
    assert cf.n_failures == 1
    assert cf.timestamp == 1000
    cf.increase(2000)
    assert cf.n_failures == 2
    assert cf.timestamp == 2000


def test_consecutive_failures_reset() -> None:
    """Test ConsecutiveFailures reset."""
    cf = ConsecutiveFailures(n_failures=5, timestamp=1000)
    cf.reset(2000)
    assert cf.n_failures == 0
    assert cf.timestamp == 2000


def test_consecutive_failures_update_status_failed() -> None:
    """Test ConsecutiveFailures update_status with failure."""
    cf = ConsecutiveFailures()
    cf.update_status(1000, has_failed=True)
    assert cf.n_failures == 1
    assert cf.timestamp == 1000


def test_consecutive_failures_update_status_success() -> None:
    """Test ConsecutiveFailures update_status with success."""
    cf = ConsecutiveFailures(n_failures=3, timestamp=1000)
    cf.update_status(2000, has_failed=False)
    assert cf.n_failures == 0
    assert cf.timestamp == 2000


def test_e_greedy_policy_invalid_eps() -> None:
    """Test that EGreedyPolicy raises for invalid epsilon."""
    with pytest.raises(ValueError, match="Cannot initialize the policy"):
        EGreedyPolicy(eps=1.5, consecutive_failures_threshold=2, quarantine_duration=10)

    with pytest.raises(ValueError, match="Cannot initialize the policy"):
        EGreedyPolicy(
            eps=-0.1, consecutive_failures_threshold=2, quarantine_duration=10
        )


def test_e_greedy_policy_serialize_deserialize(
    e_greedy_policy_mock: EGreedyPolicy,
) -> None:
    """Test serialization and deserialization round-trip."""
    serialized = e_greedy_policy_mock.serialize()
    deserialized = EGreedyPolicy.deserialize(serialized)
    assert deserialized.eps == e_greedy_policy_mock.eps
    assert (
        deserialized.consecutive_failures_threshold
        == e_greedy_policy_mock.consecutive_failures_threshold
    )
    assert set(deserialized.tools) == set(e_greedy_policy_mock.tools)


def test_e_greedy_policy_tools_property(
    e_greedy_policy_mock: EGreedyPolicy,
) -> None:
    """Test the tools property."""
    tools = e_greedy_policy_mock.tools
    assert len(tools) == 7
    assert "prediction-request-reasoning" in tools


def test_e_greedy_policy_n_tools(
    e_greedy_policy_mock: EGreedyPolicy,
) -> None:
    """Test the n_tools property."""
    assert e_greedy_policy_mock.n_tools == 7


def test_e_greedy_policy_n_requests(
    e_greedy_policy_mock: EGreedyPolicy,
) -> None:
    """Test the n_requests property."""
    n_requests = e_greedy_policy_mock.n_requests
    assert isinstance(n_requests, int)
    assert n_requests > 0


def test_e_greedy_policy_has_updated(
    e_greedy_policy_mock: EGreedyPolicy,
) -> None:
    """Test the has_updated property."""
    assert e_greedy_policy_mock.has_updated is True


def test_e_greedy_policy_has_updated_false() -> None:
    """Test the has_updated property when no requests have been made."""
    policy = EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=2,
        quarantine_duration=10,
        accuracy_store={"tool1": AccuracyInfo(requests=0, pending=0)},
    )
    assert policy.has_updated is False


def test_e_greedy_policy_random_tool(
    e_greedy_policy_mock: EGreedyPolicy,
) -> None:
    """Test the random_tool property returns a valid tool."""
    tool = e_greedy_policy_mock.random_tool
    assert tool in e_greedy_policy_mock.tools


def test_e_greedy_policy_is_quarantined_unknown_tool(
    e_greedy_policy_mock: EGreedyPolicy,
) -> None:
    """Test is_quarantined for a tool not in consecutive_failures."""
    assert e_greedy_policy_mock.is_quarantined("unknown_tool") is False


def test_e_greedy_policy_is_quarantined_true() -> None:
    """Test is_quarantined when a tool is actually quarantined."""
    current_time = int(time())
    policy = EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=2,
        quarantine_duration=10000,
        accuracy_store={"tool1": AccuracyInfo(requests=10)},
        consecutive_failures={
            "tool1": ConsecutiveFailures(n_failures=5, timestamp=current_time)
        },
    )
    assert policy.is_quarantined("tool1") is True


def test_e_greedy_policy_is_quarantined_expired() -> None:
    """Test is_quarantined when the quarantine has expired."""
    old_timestamp = 0  # Very old timestamp
    policy = EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=2,
        quarantine_duration=10,
        accuracy_store={"tool1": AccuracyInfo(requests=10)},
        consecutive_failures={
            "tool1": ConsecutiveFailures(n_failures=5, timestamp=old_timestamp)
        },
    )
    assert policy.is_quarantined("tool1") is False


def test_e_greedy_policy_valid_tools(
    e_greedy_policy_mock: EGreedyPolicy,
) -> None:
    """Test the valid_tools property."""
    valid = e_greedy_policy_mock.valid_tools
    assert len(valid) == 7


def test_e_greedy_policy_valid_weighted_accuracy_empty_raises() -> None:
    """Test valid_weighted_accuracy raises when weighted_accuracy is empty."""
    policy = EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=2,
        quarantine_duration=10,
    )
    with pytest.raises(ValueError, match="Weighted accuracy is empty"):
        _ = policy.valid_weighted_accuracy


def test_e_greedy_policy_select_tool_no_tools() -> None:
    """Test select_tool returns None when there are no tools."""
    policy = EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=2,
        quarantine_duration=10,
    )
    assert policy.select_tool() is None


def test_e_greedy_policy_tool_used(
    e_greedy_policy_mock: EGreedyPolicy,
) -> None:
    """Test tool_used increases the pending count."""
    tool = "prediction-request-reasoning"
    original_pending = e_greedy_policy_mock.accuracy_store[tool].pending
    e_greedy_policy_mock.tool_used(tool)
    assert e_greedy_policy_mock.accuracy_store[tool].pending == original_pending + 1


def test_e_greedy_policy_tool_responded(
    e_greedy_policy_mock: EGreedyPolicy,
) -> None:
    """Test tool_responded updates consecutive failures."""
    tool = "prediction-request-reasoning"
    e_greedy_policy_mock.tool_responded(tool, timestamp=999999, failed=True)
    assert e_greedy_policy_mock.consecutive_failures[tool].n_failures == 1


def test_e_greedy_policy_tool_responded_new_tool() -> None:
    """Test tool_responded for a tool not yet in consecutive_failures."""
    policy = EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=2,
        quarantine_duration=10,
        accuracy_store={"new_tool": AccuracyInfo(requests=1)},
    )
    policy.tool_responded("new_tool", timestamp=1000, failed=True)
    assert "new_tool" in policy.consecutive_failures
    assert policy.consecutive_failures["new_tool"].n_failures == 1


def test_e_greedy_policy_update_accuracy_store_winning(
    e_greedy_policy_mock: EGreedyPolicy,
) -> None:
    """Test update_accuracy_store with a winning outcome."""
    tool = "prediction-request-reasoning"
    original_requests = e_greedy_policy_mock.accuracy_store[tool].requests
    e_greedy_policy_mock.update_accuracy_store(tool, winning=True)
    assert e_greedy_policy_mock.accuracy_store[tool].requests == original_requests + 1


def test_e_greedy_policy_update_accuracy_store_losing(
    e_greedy_policy_mock: EGreedyPolicy,
) -> None:
    """Test update_accuracy_store with a losing outcome."""
    tool = "prediction-request-reasoning"
    original_requests = e_greedy_policy_mock.accuracy_store[tool].requests
    e_greedy_policy_mock.update_accuracy_store(tool, winning=False)
    assert e_greedy_policy_mock.accuracy_store[tool].requests == original_requests + 1


def test_e_greedy_policy_stats_report(
    e_greedy_policy_mock: EGreedyPolicy,
) -> None:
    """Test stats_report when policy has been updated."""
    report = e_greedy_policy_mock.stats_report()
    assert "Policy statistics so far" in report
    assert "prediction-request-reasoning" in report


def test_e_greedy_policy_stats_report_no_updates() -> None:
    """Test stats_report when policy has never been updated."""
    policy = EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=2,
        quarantine_duration=10,
        accuracy_store={"tool1": AccuracyInfo(requests=0, pending=0)},
    )
    report = policy.stats_report()
    assert report == "No policy statistics available."


def test_e_greedy_policy_best_tool_all_quarantined() -> None:
    """Test best_tool fallback when all tools are quarantined."""
    current_time = int(time())
    policy = EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=0,
        quarantine_duration=100000,
        accuracy_store={
            "tool1": AccuracyInfo(requests=10, accuracy=0.5),
            "tool2": AccuracyInfo(requests=10, accuracy=0.8),
        },
        consecutive_failures={
            "tool1": ConsecutiveFailures(n_failures=5, timestamp=current_time),
            "tool2": ConsecutiveFailures(n_failures=5, timestamp=current_time),
        },
    )
    # Should fall back to all tools since all are quarantined
    best = policy.best_tool
    assert best in ("tool1", "tool2")


def test_egreedy_policy_decoder_hook_accuracy_info() -> None:
    """Test EGreedyPolicyDecoder hook decodes AccuracyInfo."""
    data = {"requests": 10, "pending": 2, "accuracy": 0.8}
    result = EGreedyPolicyDecoder.hook(data)
    assert isinstance(result, AccuracyInfo)
    assert result.requests == 10


def test_egreedy_policy_decoder_hook_consecutive_failures() -> None:
    """Test EGreedyPolicyDecoder hook decodes ConsecutiveFailures."""
    data = {"n_failures": 3, "timestamp": 1000}
    result = EGreedyPolicyDecoder.hook(data)
    assert isinstance(result, ConsecutiveFailures)
    assert result.n_failures == 3


def test_egreedy_policy_decoder_hook_unknown_data() -> None:
    """Test EGreedyPolicyDecoder hook returns raw dict for unknown data."""
    data = {"unknown_key": "value"}
    result = EGreedyPolicyDecoder.hook(data)
    assert isinstance(result, dict)
    assert result == {"unknown_key": "value"}


def test_dataclass_encoder_non_dataclass_non_serializable() -> None:
    """Test that DataclassEncoder.default falls back to super().default for non-dataclass, non-serializable objects."""

    class CustomObj:
        """A non-serializable, non-dataclass object."""

    with pytest.raises(TypeError):
        json.dumps(CustomObj(), cls=DataclassEncoder)


def test_e_greedy_policy_select_tool_not_updated_returns_random() -> None:
    """Test select_tool returns a random tool when the policy has not been updated."""
    policy = EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=2,
        quarantine_duration=10,
        accuracy_store={
            "tool1": AccuracyInfo(requests=0, pending=0),
            "tool2": AccuracyInfo(requests=0, pending=0),
        },
    )
    # has_updated is False because n_requests == 0, so random_tool is returned
    tool = policy.select_tool(randomness=42)
    assert tool in ("tool1", "tool2")


def test_e_greedy_policy_select_tool_random_less_than_eps() -> None:
    """Test select_tool returns a random tool when random value is less than epsilon."""
    policy = EGreedyPolicy(
        eps=1.0,  # epsilon = 1.0 guarantees random selection
        consecutive_failures_threshold=2,
        quarantine_duration=10,
        accuracy_store={
            "tool1": AccuracyInfo(requests=10, pending=0, accuracy=0.5),
            "tool2": AccuracyInfo(requests=10, pending=0, accuracy=0.9),
        },
    )
    # has_updated is True (n_requests > 0), random.random() < 1.0 is always True
    tool = policy.select_tool(randomness=42)
    assert tool in ("tool1", "tool2")


def test_e_greedy_policy_select_tool_no_randomness_arg() -> None:
    """Test select_tool without the randomness argument to cover the None branch."""
    policy = EGreedyPolicy(
        eps=0.0,  # epsilon = 0.0 ensures best_tool is always selected
        consecutive_failures_threshold=2,
        quarantine_duration=10,
        accuracy_store={
            "tool1": AccuracyInfo(requests=10, pending=0, accuracy=0.5),
            "tool2": AccuracyInfo(requests=10, pending=0, accuracy=0.9),
        },
    )
    # randomness is None (default), has_updated is True, random.random() >= 0.0 always
    tool = policy.select_tool()
    assert tool == "tool2"


def test_random_tool_excludes_quarantined() -> None:
    """Quarantined tools should never be returned by random_tool."""
    current_time = int(time())
    policy = EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=0,
        quarantine_duration=100000,
        accuracy_store={
            "good": AccuracyInfo(requests=10, accuracy=0.8),
            "bad": AccuracyInfo(requests=10, accuracy=0.5),
        },
        consecutive_failures={
            "bad": ConsecutiveFailures(n_failures=5, timestamp=current_time),
        },
    )
    for _ in range(100):
        assert policy.random_tool != "bad"


def test_random_tool_falls_back_when_all_quarantined() -> None:
    """When all tools are quarantined, fall back to full set."""
    current_time = int(time())
    policy = EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=0,
        quarantine_duration=100000,
        accuracy_store={
            "t1": AccuracyInfo(requests=10),
            "t2": AccuracyInfo(requests=10),
        },
        consecutive_failures={
            "t1": ConsecutiveFailures(n_failures=5, timestamp=current_time),
            "t2": ConsecutiveFailures(n_failures=5, timestamp=current_time),
        },
    )
    assert policy.random_tool in ("t1", "t2")


def test_update_accuracy_store_pending_floor_at_zero() -> None:
    """Pending must never go below zero during update_accuracy_store."""
    policy = EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=2,
        quarantine_duration=10,
        accuracy_store={"tool1": AccuracyInfo(requests=5, pending=0, accuracy=0.5)},
    )
    policy.update_accuracy_store("tool1", winning=True)
    assert policy.accuracy_store["tool1"].pending >= 0
    assert policy.accuracy_store["tool1"].requests == 6


@pytest.mark.parametrize(
    "identity, tool, expected",
    [
        (MECH, "prediction-online", f"{MECH}::prediction-online"),
        (MECH.upper(), "prediction-online", f"{MECH}::prediction-online"),
        (OPERATOR, "prediction-online", f"{OPERATOR}::prediction-online"),
        ("WWW.Valory.XYZ", "prediction-online", f"{OPERATOR}::prediction-online"),
        (None, "prediction-online", "prediction-online"),
        ("", "prediction-online", "prediction-online"),
    ],
)
def test_tool_key(identity: str, tool: str, expected: str) -> None:
    """The key joins the lowercase identity and the tool; none yields the bare tool."""
    assert tool_key(identity, tool) == expected


@pytest.mark.parametrize(
    "key, expected",
    [
        (f"{MECH}::prediction-online", (MECH, "prediction-online")),
        (f"{MECH.upper()}::prediction-online", (MECH, "prediction-online")),
        (f"{MECH}::odd::tool", (MECH, "odd::tool")),
        (f"{OPERATOR}::prediction-online", (OPERATOR, "prediction-online")),
        ("WWW.Valory.xyz::prediction-online", (OPERATOR, "prediction-online")),
        ("https://www.valory.xyz::tool", (None, "https://www.valory.xyz::tool")),
        ("localhost::tool", (None, "localhost::tool")),
        ("prediction-online", (None, "prediction-online")),
        ("not-an-address::tool", (None, "not-an-address::tool")),
        ("0x1234::tool", (None, "0x1234::tool")),
        ("", (None, "")),
    ],
)
def test_split_tool_key(key: str, expected: tuple) -> None:
    """Only an address or a bare hostname before the separator counts as an identity."""
    assert split_tool_key(key) == expected


def test_tool_key_round_trips() -> None:
    """Splitting a built key gives back its parts."""
    assert split_tool_key(tool_key(MECH, "tool")) == (MECH, "tool")
    assert split_tool_key(tool_key(OPERATOR, "tool")) == (OPERATOR, "tool")
    assert split_tool_key(tool_key(None, "tool")) == (None, "tool")


def test_describe_tool_key() -> None:
    """Keys render as ``tool @ mech`` and bare tools as themselves."""
    assert describe_tool_key(tool_key(MECH, "tool")) == f"tool @ {MECH}"
    assert describe_tool_key(tool_key(OPERATOR, "tool")) == f"tool @ {OPERATOR}"
    assert describe_tool_key("tool") == "tool"


def test_same_tool_on_two_mechs_has_two_records() -> None:
    """Mechs serving the same tool never share accuracy or quarantine state."""
    other = "0x" + "cd" * 20
    key_a, key_b = tool_key(MECH, "tool"), tool_key(other, "tool")
    policy = EGreedyPolicy(
        eps=0.0,
        consecutive_failures_threshold=0,
        quarantine_duration=100000,
        accuracy_store={
            key_a: AccuracyInfo(requests=10, accuracy=0.9),
            key_b: AccuracyInfo(requests=10, accuracy=0.9),
        },
    )
    policy.update_accuracy_store(key_a, winning=False)
    policy.tool_responded(key_b, timestamp=int(time()), failed=True)

    assert policy.accuracy_store[key_a].requests == 11
    assert policy.accuracy_store[key_b].requests == 10
    assert policy.is_quarantined(key_b) is True
    assert policy.is_quarantined(key_a) is False
    assert policy.select_tool() == key_a


def test_tool_used_starts_a_record_for_an_unknown_key() -> None:
    """A delivery by a mech other than the requested one gets its own record."""
    policy = EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=2,
        quarantine_duration=10,
        accuracy_store={tool_key(MECH, "tool"): AccuracyInfo(requests=1)},
    )
    new_key = tool_key("0x" + "cd" * 20, "tool")
    policy.tool_used(new_key)
    assert policy.accuracy_store[new_key] == AccuracyInfo(requests=0, pending=1)
    assert new_key in policy.weighted_accuracy


def test_update_accuracy_store_rejects_an_unknown_key() -> None:
    """Outcomes are only credited to pairs that have a record."""
    policy = EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=2,
        quarantine_duration=10,
        accuracy_store={tool_key(MECH, "tool"): AccuracyInfo(requests=1)},
    )
    with pytest.raises(KeyError):
        policy.update_accuracy_store("tool", winning=True)


def test_stats_report_names_the_mech_of_each_key() -> None:
    """The report renders keys as ``tool @ mech``."""
    key = tool_key(MECH, "tool")
    policy = EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=2,
        quarantine_duration=10,
        accuracy_store={key: AccuracyInfo(requests=3, accuracy=0.5)},
    )
    report = policy.stats_report()
    assert f"tool @ {MECH} tool:" in report
    assert f"Best non-quarantined tool so far is 'tool @ {MECH}'." in report


def _percent_era_weight(
    accuracy_percent: float, requests: int, n_requests: int
) -> float:
    """The weight a percent-scale record got before accuracy became a fraction."""
    return scale_value(
        accuracy_percent + (requests / n_requests) * 0.1, (-0.5, 80.5), (0, 1)
    )


def test_fraction_weights_equal_the_percent_era_weights() -> None:
    """Converting a seeded record to a fraction leaves its weight unchanged."""
    policy = EGreedyPolicy(
        eps=0.0,
        consecutive_failures_threshold=2,
        quarantine_duration=10,
        accuracy_store={
            "a": AccuracyInfo(requests=300, accuracy=0.66),
            "b": AccuracyInfo(requests=700, accuracy=0.57),
        },
    )
    assert policy.weighted_accuracy["a"] == pytest.approx(
        _percent_era_weight(66.0, 300, 1000)
    )
    assert policy.weighted_accuracy["b"] == pytest.approx(
        _percent_era_weight(57.0, 700, 1000)
    )


@pytest.mark.parametrize(
    "high_volume_accuracy, expected_best",
    [
        # one accuracy point is not outweighed by a hundredfold traffic gap
        (0.65, "low_volume"),
        # at equal accuracy the busier tool wins
        (0.66, "high_volume"),
    ],
)
def test_accuracy_dominates_volume_in_the_ranking(
    high_volume_accuracy: float, expected_best: str
) -> None:
    """Volume only separates tools of near-equal accuracy."""
    policy = EGreedyPolicy(
        eps=0.0,
        consecutive_failures_threshold=2,
        quarantine_duration=10,
        accuracy_store={
            "low_volume": AccuracyInfo(requests=100, accuracy=0.66),
            "high_volume": AccuracyInfo(requests=10000, accuracy=high_volume_accuracy),
        },
    )
    assert policy.best_tool == expected_best
