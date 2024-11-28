# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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
"""This module contains the transaction payloads for the decision maker abci."""
from typing import Dict, Type

import pytest

from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.decision_maker_abci.payloads import (
    BlacklistingPayload,
    ClaimPayload,
    DecisionReceivePayload,
    DecisionRequestPayload,
    MultisigTxPayload,
    RedeemPayload,
    SamplingPayload,
    SubscriptionPayload,
    ToolSelectionPayload,
    VotingPayload,
)


@pytest.mark.parametrize(
    "payload_class, payload_kwargs",
    [
        (
            DecisionReceivePayload,
            {
                "bets_hash": "dummy bets hash",
                "is_profitable": True,
                "vote": True,
                "confidence": 0.90,
                "bet_amount": 1,
                "next_mock_data_row": 1,
            },
        ),
        (
            SamplingPayload,
            {
                "index": 1,
                "bets_hash": "dummy_bets_hash",
                "benchmarking_finished": False,
                "day_increased": False,
            },
        ),
        (
            MultisigTxPayload,
            {
                "tx_submitter": "dummy tx submitter",
                "tx_hash": "dummy tx hash",
                "mocking_mode": True,
            },
        ),
        (
            RedeemPayload,
            {
                "tx_submitter": "dummy tx submitter",
                "tx_hash": "dummy tx hash",
                "mocking_mode": True,
                "mech_tools": "dummy mech tools",
                "policy": "dummy policy",
                "utilized_tools": "dummy utilized tools",
                "redeemed_condition_ids": "dummy redeemed condition ids",
                "payout_so_far": 1,
            },
        ),
        (
            DecisionRequestPayload,
            {
                "mech_requests": "dummy mech requests",
                "mocking_mode": True,
            },
        ),
        (
            SubscriptionPayload,
            {
                "agreement_id": "",
                "tx_submitter": "dummy tx submitter",
                "tx_hash": "dummy tx hash",
                "mocking_mode": True,
            },
        ),
        (
            ClaimPayload,
            {"vote": True},
        ),
        (
            VotingPayload,
            {"vote": True},
        ),
        (
            BlacklistingPayload,
            {"policy": "dummy policy", "bets_hash": "dummy bets hash"},
        ),
        (
            ToolSelectionPayload,
            {
                "mech_tools": "dummy mech tools",
                "policy": "dummy policy",
                "utilized_tools": "dummy utilized tools",
                "selected_tool": "dummy selected tool",
            },
        ),
    ],
)
def test_payload(payload_class: Type[BaseTxPayload], payload_kwargs: Dict) -> None:
    """Test payloads."""
    payload = payload_class(sender="sender", **payload_kwargs)

    for key, value in payload_kwargs.items():
        assert getattr(payload, key) == value

    assert payload.sender == "sender"
    assert payload.data == payload_kwargs
    assert payload_class.from_json(payload.json) == payload
