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

"""Tests for the rounds of the agent top-up skill."""

from typing import Mapping, Optional
from unittest import mock

import pytest

from packages.valory.skills.abstract_round_abci.base import AbciAppDB
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseCollectSameUntilThresholdRoundTest,
)
from packages.valory.skills.agent_topup_abci.payloads import AgentTopUpPayload
from packages.valory.skills.agent_topup_abci.rounds import (
    AgentTopUpRound,
    Event,
    SynchronizedData,
)

SUBMITTER = AgentTopUpRound.auto_round_id()
PARTICIPANTS = frozenset(f"agent_{i}" for i in range(4))


def _payloads(tx_hash: Optional[str]) -> Mapping[str, AgentTopUpPayload]:
    """Build one payload per participant."""
    return {
        participant: AgentTopUpPayload(participant, SUBMITTER, tx_hash)
        for participant in PARTICIPANTS
    }


class TestAgentTopUpRound(BaseCollectSameUntilThresholdRoundTest):
    """Tests for AgentTopUpRound."""

    _synchronized_data_class = SynchronizedData
    _event_class = Event

    @pytest.mark.parametrize(
        "tx_hash, event",
        [(None, Event.DONE), ("0xhash", Event.PREPARE_TX)],
    )
    def test_end_block(self, tx_hash: Optional[str], event: Event) -> None:
        """A prepared tx goes to settlement, no tx ends the check."""
        test_round = AgentTopUpRound(
            synchronized_data=self.synchronized_data, context=mock.MagicMock()
        )

        self._complete_run(
            self._test_round(
                test_round=test_round,
                round_payloads=_payloads(tx_hash),
                synchronized_data_update_fn=lambda data, _: data.update(
                    tx_submitter=SUBMITTER, most_voted_tx_hash=tx_hash
                ),
                synchronized_data_attr_checks=[
                    lambda data: data.tx_submitter,
                    lambda data: data.db.get("most_voted_tx_hash"),
                ],
                most_voted_payload=SUBMITTER,
                exit_event=event,
            )
        )

    def test_no_majority(self) -> None:
        """Split payloads are reported as no majority."""
        test_round = AgentTopUpRound(
            synchronized_data=self.synchronized_data, context=mock.MagicMock()
        )
        self._test_no_majority_event(test_round)


def test_participant_to_topup() -> None:
    """The collection of the round is deserialised from the db."""
    payload = AgentTopUpPayload("agent_0", SUBMITTER, None)
    data = SynchronizedData(
        AbciAppDB(
            setup_data=AbciAppDB.data_to_lists(
                {
                    "participant_to_topup": AgentTopUpRound.serialize_collection(
                        {"agent_0": payload}
                    )
                }
            )
        )
    )

    assert data.participant_to_topup == {"agent_0": payload}
