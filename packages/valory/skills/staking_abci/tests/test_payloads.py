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
"""This module contains the transaction payloads for the staking abci."""
import pytest

from packages.valory.skills.staking_abci.payloads import MultisigTxPayload, CallCheckpointPayload


@pytest.mark.parametrize(
    "payload_class, payload_kwargs",
    [
        (
            MultisigTxPayload,
            {
                "tx_submitter": "dummy tx submitter",
                "tx_hash": "dummy tx hash"
            }
        ),
        (
            CallCheckpointPayload,
            {
                "service_staking_state": 1,
                "tx_submitter": "dummy tx submitter",
                "tx_hash": "dummy tx hash"
            }
        )
    ]
)
def test_payload(payload_class, payload_kwargs):
    """Test payloads."""
    payload = payload_class(sender="sender", **payload_kwargs)

    # Check each attribute in expected_data
    for key, value in payload_kwargs.items():
        assert getattr(payload, key) == value

    assert payload.sender == "sender"
    assert payload.data == payload_kwargs
    assert payload_class.from_json(payload.json) == payload