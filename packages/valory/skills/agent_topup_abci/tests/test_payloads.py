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

"""Tests for the payloads of the agent top-up skill."""

from packages.valory.skills.agent_topup_abci.payloads import AgentTopUpPayload


def test_payload_round_trips() -> None:
    """The payload keeps its fields through serialisation."""
    payload = AgentTopUpPayload(sender="sender", tx_submitter="submitter", tx_hash=None)

    assert payload.data == {"tx_submitter": "submitter", "tx_hash": None}
    assert AgentTopUpPayload.from_json(payload.json) == payload
