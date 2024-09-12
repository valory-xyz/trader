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

"""This package contains the tests for the PreTxSettlementRound of TxSettlementMultiplexerAbciApp."""

import json
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    Hashable,
    List,
    Mapping,
    Optional,
    Type,
)
from unittest.mock import MagicMock, patch

import pytest

from packages.valory.skills.abstract_round_abci.base import (
    CollectionRound,
    VotingRound,
    get_name,
)
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseVotingRoundTest,
)
from packages.valory.skills.decision_maker_abci.payloads import VotingPayload
from packages.valory.skills.tx_settlement_multiplexer_abci.rounds import (
    BetPlacementRound,
    CallCheckpointRound,
    ChecksPassedRound,
    Event,
    FailedMultiplexerRound,
    FinishedBetPlacementTxRound,
    FinishedMechRequestTxRound,
    FinishedRedeemingTxRound,
    FinishedStakingTxRound,
    FinishedSubscriptionTxRound,
    MechRequestRound,
    PostTxSettlementRound,
    PreTxSettlementRound,
    RedeemRound,
    SubscriptionRound,
    SynchronizedData,
    TxSettlementMultiplexerAbciApp,
)


DUMMY_PAYLOAD_DATA = {"example_key": "example_value"}


def get_participants() -> FrozenSet[str]:
    """Participants."""
    return frozenset([f"agent_{i}" for i in range(MAX_PARTICIPANTS)])


def get_participant_to_votes(
    participants: FrozenSet[str], vote: bool
) -> Dict[str, VotingPayload]:
    """participant_to_votes"""

    return {
        participant: VotingPayload(sender=participant, vote=vote)
        for participant in participants
    }


def get_participant_to_votes_serialized(
    participants: FrozenSet[str], vote: bool
) -> Dict[str, Dict[str, Any]]:
    """participant_to_votes"""

    return CollectionRound.serialize_collection(
        get_participant_to_votes(participants, vote)
    )


def get_payloads(
    payload_cls: Type[VotingPayload],
    data: Optional[str],
) -> Mapping[str, VotingPayload]:
    """Get payloads."""
    return {
        participant: payload_cls(participant, data is not None)
        for participant in get_participants()
    }


def get_dummy_tx_settlement_payload_serialized() -> str:
    """Dummy payload serialization"""
    return json.dumps(DUMMY_PAYLOAD_DATA, sort_keys=True)


@dataclass
class RoundTestCase:
    """RoundTestCase"""

    name: str
    initial_data: Dict[str, Hashable]
    payloads: Mapping[str, VotingPayload]
    final_data: Dict[str, Hashable]
    event: Event
    most_voted_payload: Any
    synchronized_data_attr_checks: List[Callable] = field(default_factory=list)


MAX_PARTICIPANTS: int = 4


class BasePreTxSettlementRoundTest(BaseVotingRoundTest):
    """Base test class for TxSettlementMultiplexer rounds derived from VotingRound."""

    test_class: Type[VotingRound]
    test_payload: Type[VotingPayload]

    def _test_voting_round(
        self, vote: bool, expected_event: Any, threshold_check: Callable
    ) -> None:
        """Helper method to test voting rounds with positive or negative votes."""

        test_round = self.test_class(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )

        self._complete_run(
            self._test_round(
                test_round=test_round,
                round_payloads=get_participant_to_votes(self.participants, vote=vote),
                synchronized_data_update_fn=lambda _synchronized_data, _: _synchronized_data.update(
                    participant_to_votes=get_participant_to_votes_serialized(
                        self.participants, vote=vote
                    )
                ),
                synchronized_data_attr_checks=[
                    lambda _synchronized_data: _synchronized_data.participant_to_votes.keys()
                ]
                if vote
                else [],
                exit_event=expected_event,
                threshold_check=threshold_check,
            )
        )

    def test_positive_votes(self) -> None:
        """Test PreTxSettlementRound for positive votes."""
        self._test_voting_round(
            vote=True,
            expected_event=Event.CHECKS_PASSED,
            threshold_check=lambda x: x.positive_vote_threshold_reached,
        )

    def test_negative_votes(self) -> None:
        """Test PreTxSettlementRound for negative votes."""
        self._test_voting_round(
            vote=False,
            expected_event=Event.REFILL_REQUIRED,
            threshold_check=lambda x: x.negative_vote_threshold_reached,
        )


class TestPreTxSettlementRound(BasePreTxSettlementRoundTest):
    """Tests for PreTxSettlementRound."""

    test_class = PreTxSettlementRound
    _event_class = Event
    _synchronized_data_class = SynchronizedData

    @pytest.mark.parametrize(
        "test_case",
        (
            RoundTestCase(
                name="Happy path",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=VotingPayload,
                    data=get_dummy_tx_settlement_payload_serialized(),
                ),
                final_data={},
                event=Event.CHECKS_PASSED,
                most_voted_payload=get_dummy_tx_settlement_payload_serialized(),
                synchronized_data_attr_checks=[
                    lambda sync_data: sync_data.db.get(
                        get_name(SynchronizedData.participant_to_votes)
                    )
                    == CollectionRound.deserialize_collection(
                        json.loads(get_dummy_tx_settlement_payload_serialized())
                    )
                ],
            ),
            RoundTestCase(
                name="Negative votes",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=VotingPayload,
                    data=get_dummy_tx_settlement_payload_serialized(),
                ),
                final_data={},
                event=Event.REFILL_REQUIRED,
                most_voted_payload=get_dummy_tx_settlement_payload_serialized(),
                synchronized_data_attr_checks=[],
            ),
        ),
    )
    def test_run(self, test_case: RoundTestCase) -> None:
        """Run tests."""
        if test_case.event == Event.CHECKS_PASSED:
            self.test_positive_votes()
        elif test_case.event == Event.REFILL_REQUIRED:
            self.test_negative_votes()


class TestPostTxSettlementRound:
    """Tests for PostTxSettlementRound."""

    def setup_method(self) -> None:
        """Setup the synchronized_data for each test."""
        self.synchronized_data = MagicMock()
        self.synchronized_data.db = MagicMock()
        self.synchronized_data.policy = MagicMock()
        self.synchronized_data.utilized_tools = {}
        self.synchronized_data.mech_tool = "tool_2"
        self.synchronized_data.final_tx_hash = "hash_123"

    def test_end_block_unknown(self) -> None:
        """Test the end_block logic for unknown tx_submitter."""
        # Arrange
        self.synchronized_data.tx_submitter = "unknown_submitter"
        round_ = PostTxSettlementRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        # Act
        result = round_.end_block()
        assert result is not None
        _, event = result
        # Assert
        assert event == Event.UNRECOGNIZED

    def test_mech_requesting_done_event_updates_policy(self) -> None:
        """Test the MECH_REQUESTING_DONE event updates policy."""
        # Arrange
        event = Event.MECH_REQUESTING_DONE

        with patch.object(self.synchronized_data.policy, "tool_used") as mock_tool_used:
            with patch.object(
                self.synchronized_data.policy, "serialize"
            ) as mock_serialize:
                if event == Event.MECH_REQUESTING_DONE:
                    self.synchronized_data.policy.tool_used(
                        self.synchronized_data.mech_tool
                    )
                    serialized_policy = self.synchronized_data.policy.serialize()
                    self.synchronized_data.update(policy=serialized_policy)

                mock_tool_used.assert_called_once_with(self.synchronized_data.mech_tool)
                mock_serialize.assert_called_once()

    def test_bet_placement_done_event_updates_policy(self) -> None:
        """Test the BET_PLACEMENT_DONE event updates policy."""
        # Arrange
        event = Event.BET_PLACEMENT_DONE

        with patch.object(self.synchronized_data.policy, "tool_used") as mock_tool_used:
            with patch.object(
                self.synchronized_data.policy, "serialize"
            ) as mock_serialize:
                if event == Event.BET_PLACEMENT_DONE:
                    self.synchronized_data.policy.tool_used(
                        self.synchronized_data.mech_tool
                    )
                    serialized_policy = self.synchronized_data.policy.serialize()
                    self.synchronized_data.update(policy=serialized_policy)

                mock_tool_used.assert_called_once_with(self.synchronized_data.mech_tool)
                mock_serialize.assert_called_once()

    def test_end_block_mech_requesting_done(self) -> None:
        """Test the end_block logic for MECH_REQUESTING_DONE event."""
        # Arrange

        self.synchronized_data.tx_submitter = MechRequestRound.auto_round_id()
        round_ = PostTxSettlementRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        # Act
        result = round_.end_block()
        assert result is not None
        _, event = result
        # Assert
        if self.synchronized_data.tx_submitter in [
            MechRequestRound.auto_round_id(),
            BetPlacementRound.auto_round_id(),
            RedeemRound.auto_round_id(),
            CallCheckpointRound.auto_round_id(),
            SubscriptionRound.auto_round_id(),
        ]:
            assert event == Event.UNRECOGNIZED

    def test_end_block_bet_placement_done(self) -> None:
        """Test the end_block logic for BET_PLACEMENT_DONE event."""
        # Arrange
        self.synchronized_data.tx_submitter = BetPlacementRound.auto_round_id()
        round_ = PostTxSettlementRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        # Act
        result = round_.end_block()
        assert result is not None
        _, event = result
        # Assert
        if self.synchronized_data.tx_submitter in [
            MechRequestRound.auto_round_id(),
            BetPlacementRound.auto_round_id(),
            RedeemRound.auto_round_id(),
            CallCheckpointRound.auto_round_id(),
            SubscriptionRound.auto_round_id(),
        ]:
            assert event == Event.UNRECOGNIZED


def test_tx_settlement_abci_app_initialization() -> None:
    """Test the initialization of TxSettlementMultiplexerAbciApp."""
    abci_app = TxSettlementMultiplexerAbciApp(
        synchronized_data=MagicMock(), logger=MagicMock(), context=MagicMock()
    )
    assert abci_app.initial_round_cls is PreTxSettlementRound
    assert abci_app.final_states == {
        ChecksPassedRound,
        FinishedMechRequestTxRound,
        FinishedBetPlacementTxRound,
        FinishedRedeemingTxRound,
        FinishedStakingTxRound,
        FinishedSubscriptionTxRound,
        FailedMultiplexerRound,
    }
    assert abci_app.transition_function == {
        PreTxSettlementRound: {
            Event.CHECKS_PASSED: ChecksPassedRound,
            Event.REFILL_REQUIRED: PreTxSettlementRound,
            Event.NO_MAJORITY: PreTxSettlementRound,
            Event.ROUND_TIMEOUT: PreTxSettlementRound,
        },
        PostTxSettlementRound: {
            Event.MECH_REQUESTING_DONE: FinishedMechRequestTxRound,
            Event.BET_PLACEMENT_DONE: FinishedBetPlacementTxRound,
            Event.REDEEMING_DONE: FinishedRedeemingTxRound,
            Event.STAKING_DONE: FinishedStakingTxRound,
            Event.SUBSCRIPTION_DONE: FinishedSubscriptionTxRound,
            Event.ROUND_TIMEOUT: PostTxSettlementRound,
            Event.UNRECOGNIZED: FailedMultiplexerRound,
        },
        ChecksPassedRound: {},
        FinishedMechRequestTxRound: {},
        FinishedBetPlacementTxRound: {},
        FinishedRedeemingTxRound: {},
        FinishedStakingTxRound: {},
        FinishedSubscriptionTxRound: {},
        FailedMultiplexerRound: {},
    }
    assert abci_app.event_to_timeout == {Event.ROUND_TIMEOUT: 30.0}
