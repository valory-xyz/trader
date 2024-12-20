# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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


"""This package contains the tests for Decision Maker"""

from typing import Dict, Optional
from unittest.mock import MagicMock

import pytest

from packages.valory.skills.abstract_round_abci.base import CollectionRound
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseCollectSameUntilThresholdRoundTest,
)
from packages.valory.skills.decision_maker_abci.payloads import HandleFailedTxPayload
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)
from packages.valory.skills.decision_maker_abci.states.handle_failed_tx import (
    HandleFailedTxRound,
)


class TestEstimateConsensusRound(BaseCollectSameUntilThresholdRoundTest):
    """Test EstimateConsensusRound."""

    _synchronized_data_class = SynchronizedData
    _event_class = Event

    def get_participant_to_handle(
        self, vote: Optional[bool]
    ) -> Dict[str, HandleFailedTxPayload]:
        """Map participants to votes."""
        return {
            participant: HandleFailedTxPayload(
                sender=participant, vote=vote, tx_submitter="tx_submitter"  # type: ignore
            )
            for participant in self.participants
        }

    @pytest.mark.parametrize(
        "vote, expected_event",
        (
            (True, HandleFailedTxRound.done_event),
            (False, HandleFailedTxRound.no_op_event),
        ),
    )
    def test_run(
        self,
        vote: Optional[bool],
        expected_event: Event,
    ) -> None:
        """Runs test."""

        test_round = HandleFailedTxRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        participant_to_handle = self.get_participant_to_handle(vote)
        self._complete_run(
            self._test_round(
                test_round=test_round,
                round_payloads=participant_to_handle,
                synchronized_data_update_fn=lambda _synchronized_data, _test_round: _synchronized_data.update(
                    participant_to_handle_failed_tx=CollectionRound.serialize_collection(
                        participant_to_handle
                    ),
                    most_voted_estimate=_test_round.most_voted_payload,
                ),
                synchronized_data_attr_checks=[
                    lambda _synchronized_data: _synchronized_data.participant_to_handle_failed_tx.keys()
                ],
                most_voted_payload=vote,
                exit_event=expected_event,
            )
        )
