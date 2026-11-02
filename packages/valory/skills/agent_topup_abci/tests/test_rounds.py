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

from packages.valory.skills.abstract_round_abci.base import AbciAppDB
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseCollectSameUntilThresholdRoundTest,
)
from packages.valory.skills.agent_topup_abci.payloads import AgentTopUpPayload
from packages.valory.skills.agent_topup_abci.rounds import (
    AgentTopUpRound,
    Event,
    FinishedAgentTopUpRound,
    SynchronizedData,
)

SUBMITTER = AgentTopUpRound.auto_round_id()
PARTICIPANTS = frozenset(f"agent_{i}" for i in range(4))


def _payloads(tx_hash: Optional[str]) -> Mapping[str, AgentTopUpPayload]:
    """Build one payload per participant."""
    tx_submitter = None if tx_hash is None else SUBMITTER
    return {
        participant: AgentTopUpPayload(participant, tx_submitter, tx_hash)
        for participant in PARTICIPANTS
    }


class TestAgentTopUpRound(BaseCollectSameUntilThresholdRoundTest):
    """Tests for AgentTopUpRound."""

    _synchronized_data_class = SynchronizedData
    _event_class = Event

    def _run(
        self,
        tx_hash: Optional[str],
        expected_submitter: Optional[str],
        event: Event,
    ) -> None:
        """Run the round on one payload per participant."""
        test_round = AgentTopUpRound(
            synchronized_data=self.synchronized_data, context=mock.MagicMock()
        )

        self._complete_run(
            self._test_round(
                test_round=test_round,
                round_payloads=_payloads(tx_hash),
                synchronized_data_update_fn=lambda data, _: data.update(
                    tx_submitter=expected_submitter
                ),
                synchronized_data_attr_checks=[
                    lambda data: data.db.get("tx_submitter", None),
                ],
                most_voted_payload=None if tx_hash is None else SUBMITTER,
                exit_event=event,
            )
        )

    def test_prepared_tx_goes_to_settlement(self) -> None:
        """A prepared tx is recorded with its submitter and sent to settlement."""
        self._run("0xhash", SUBMITTER, Event.PREPARE_TX)

    def test_no_tx_writes_no_submitter(self) -> None:
        """A visit that sends nothing leaves the period without a tx submitter."""
        self._run(None, None, Event.DONE)

    def test_no_tx_after_a_topup_tx_releases_the_submitter(self) -> None:
        """Once the check is over, a later failure in the period is not a top-up one."""
        self.synchronized_data = self.synchronized_data.update(
            tx_submitter=SUBMITTER, most_voted_tx_hash="0xsettled"
        )
        self._run(None, FinishedAgentTopUpRound.auto_round_id(), Event.DONE)

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


def test_tx_submitter() -> None:
    """The submitter of the last tx is read from the db."""
    data = SynchronizedData(
        AbciAppDB(setup_data=AbciAppDB.data_to_lists({"tx_submitter": SUBMITTER}))
    )

    assert data.tx_submitter == SUBMITTER
