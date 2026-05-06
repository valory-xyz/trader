# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2026 Valory AG
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

"""This package contains the tests for the CheckStopTradingAbciApp."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    Hashable,
    List,
    Mapping,
    Optional,
    Tuple,
    Type,
)
from unittest.mock import MagicMock, Mock, patch

import pytest

from packages.valory.skills.abstract_round_abci.base import (
    AbciAppDB,
    CollectionRound,
    VotingRound,
    get_name,
)
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseVotingRoundTest,
)
from packages.valory.skills.check_stop_trading_abci.payloads import (
    CheckStopTradingPayload,
)
from packages.valory.skills.check_stop_trading_abci.rounds import (
    CheckStopTradingAbciApp,
    CheckStopTradingRound,
    Event,
    FinishedCheckStopTradingRound,
    FinishedWithReviewBetsRound,
    FinishedWithSkipTradingRound,
    FinishedWithWithdrawalOmenRound,
    FinishedWithWithdrawalPolymarketRound,
    SynchronizedData,
)

DUMMY_PAYLOAD_DATA = {"example_key": "example_value"}


@pytest.fixture
def abci_app() -> CheckStopTradingAbciApp:
    """Fixture for CheckStopTradingAbciApp."""
    synchronized_data = Mock()
    logger = Mock()
    context = Mock()

    return CheckStopTradingAbciApp(
        synchronized_data=synchronized_data, logger=logger, context=context
    )


def get_participants() -> FrozenSet[str]:
    """Participants"""
    return frozenset([f"agent_{i}" for i in range(MAX_PARTICIPANTS)])


def get_participant_to_votes(
    participants: FrozenSet[str], vote: bool, review_bets_for_selling: bool
) -> Dict[str, CheckStopTradingPayload]:
    """participant_to_votes"""

    return {
        participant: CheckStopTradingPayload(
            sender=participant,
            vote=vote,
            review_bets_for_selling=review_bets_for_selling,
        )
        for participant in participants
    }


def get_participant_to_votes_serialized(
    participants: FrozenSet[str], vote: bool, review_bets_for_selling: bool
) -> Dict[str, Dict[str, Any]]:
    """participant_to_votes"""

    return CollectionRound.serialize_collection(
        get_participant_to_votes(participants, vote, review_bets_for_selling)
    )


def get_payloads(
    payload_cls: Type[CheckStopTradingPayload],
    data: Optional[str],
) -> Mapping[str, CheckStopTradingPayload]:
    """Get payloads."""
    return {
        participant: payload_cls(participant, data is not None)
        for participant in get_participants()
    }


def get_dummy_check_stop_trading_payload_serialized() -> str:
    """Dummy payload serialization"""
    return json.dumps(DUMMY_PAYLOAD_DATA, sort_keys=True)


@dataclass
class RoundTestCase:
    """RoundTestCase"""

    name: str
    initial_data: Dict[str, Hashable]
    payloads: Mapping[str, CheckStopTradingPayload]
    final_data: Dict[str, Hashable]
    event: Event
    most_voted_payload: Any
    synchronized_data_attr_checks: List[Callable] = field(default_factory=list)


MAX_PARTICIPANTS: int = 4


class BaseCheckStopTradingRoundTest(BaseVotingRoundTest):
    """Base Test Class for CheckStopTradingRound"""

    test_class: Type[VotingRound]
    test_payload: Type[CheckStopTradingPayload]

    def _test_voting_round(
        self,
        vote: bool,
        expected_event: Any,
        threshold_check: Callable,
        should_review_bets: bool = False,
    ) -> None:
        """Helper method to test voting rounds with positive or negative votes."""

        test_round = self.test_class(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        test_round.context.params.review_period_seconds = 60 * 60 * 24  # 1 day

        if should_review_bets:
            test_round.context.params.enable_position_review = True
            test_round.context.state.round_sequence.last_round_transition_timestamp = (
                datetime.now() - timedelta(seconds=10)
            )
            test_round.context.params.review_period_seconds = 10

        self._complete_run(
            self._test_round(
                test_round=test_round,
                round_payloads=get_participant_to_votes(
                    self.participants,
                    vote=vote,
                    review_bets_for_selling=should_review_bets,
                ),
                synchronized_data_update_fn=lambda _synchronized_data, _: _synchronized_data.update(
                    participant_to_votes=get_participant_to_votes_serialized(
                        self.participants,
                        vote=vote,
                        review_bets_for_selling=should_review_bets,
                    ),
                    review_bets_for_selling=should_review_bets,
                ),
                synchronized_data_attr_checks=(
                    [
                        lambda _synchronized_data: _synchronized_data.participant_to_votes.keys()
                    ]
                    if vote
                    else []
                ),
                exit_event=expected_event,
                threshold_check=threshold_check,
            )
        )

    def test_positive_votes(self) -> None:
        """Test ValidateRound for positive votes."""
        self._test_voting_round(
            vote=True,
            expected_event=self._event_class.SKIP_TRADING,
            threshold_check=lambda x: x.positive_vote_threshold_reached,
        )

    def test_review_bets(self) -> None:
        """Test ValidateRound for review bets."""
        self._test_voting_round(
            vote=True,
            expected_event=self._event_class.REVIEW_BETS,
            threshold_check=lambda x: x.positive_vote_threshold_reached,
            should_review_bets=True,
        )

    def test_negative_votes(self) -> None:
        """Test ValidateRound for negative votes."""
        self._test_voting_round(
            vote=False,
            expected_event=self._event_class.DONE,
            threshold_check=lambda x: x.negative_vote_threshold_reached,
        )


class TestCheckStopTradingRound(BaseCheckStopTradingRoundTest):
    """Tests for CheckStopTradingRound."""

    test_class = CheckStopTradingRound
    _event_class = Event
    _synchronized_data_class = SynchronizedData

    @pytest.mark.parametrize(
        "test_case",
        (
            RoundTestCase(
                name="Happy path",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=CheckStopTradingPayload,
                    data=get_dummy_check_stop_trading_payload_serialized(),
                ),
                final_data={},
                event=Event.SKIP_TRADING,
                most_voted_payload=get_dummy_check_stop_trading_payload_serialized(),
                synchronized_data_attr_checks=[
                    lambda sync_data: sync_data.db.get(
                        get_name(SynchronizedData.participant_to_votes)
                    )
                    == CollectionRound.deserialize_collection(
                        json.loads(get_dummy_check_stop_trading_payload_serialized())
                    )
                ],
            ),
            RoundTestCase(
                name="Review bets for selling",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=CheckStopTradingPayload,
                    data=get_dummy_check_stop_trading_payload_serialized(),
                ),
                final_data={},
                event=Event.REVIEW_BETS,
                most_voted_payload=get_dummy_check_stop_trading_payload_serialized(),
                synchronized_data_attr_checks=[
                    lambda sync_data: sync_data.db.get(
                        get_name(SynchronizedData.participant_to_votes)
                    )
                    == CollectionRound.deserialize_collection(
                        json.loads(get_dummy_check_stop_trading_payload_serialized())
                    )
                ],
            ),
            RoundTestCase(
                name="No majority",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=CheckStopTradingPayload,
                    data=get_dummy_check_stop_trading_payload_serialized(),
                ),
                final_data={},
                event=Event.NO_MAJORITY,
                most_voted_payload=get_dummy_check_stop_trading_payload_serialized(),
                synchronized_data_attr_checks=[],
            ),
        ),
    )
    def test_run(self, test_case: RoundTestCase) -> None:
        """Run tests."""
        if test_case.event == Event.SKIP_TRADING:
            self.test_positive_votes()
        elif test_case.event == Event.REVIEW_BETS:
            self.test_review_bets()
        elif test_case.event == Event.NO_MAJORITY:
            self.test_negative_votes()

    """Tests for FinishedCheckStopTradingRound."""

    def test_finished_check_stop_trading_round_initialization(self) -> None:
        """Test the initialization of FinishedCheckStopTradingRound."""
        round_ = FinishedCheckStopTradingRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        assert isinstance(round_, FinishedCheckStopTradingRound)


class TestFinishedWithSkipTradingRound:
    """Tests for FinishedWithSkipTradingRound."""

    def test_finished_with_skip_trading_round_initialization(self) -> None:
        """Test the initialization of FinishedWithSkipTradingRound."""
        round_ = FinishedWithSkipTradingRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        assert isinstance(round_, FinishedWithSkipTradingRound)


def test_abci_app_initialization(abci_app: CheckStopTradingAbciApp) -> None:
    """Test the initialization of CheckStopTradingAbciApp."""
    assert abci_app.initial_round_cls is CheckStopTradingRound
    assert abci_app.final_states == {
        FinishedCheckStopTradingRound,
        FinishedWithSkipTradingRound,
        FinishedWithReviewBetsRound,
        FinishedWithWithdrawalPolymarketRound,
        FinishedWithWithdrawalOmenRound,
    }
    assert abci_app.transition_function == {
        CheckStopTradingRound: {
            Event.DONE: FinishedCheckStopTradingRound,
            Event.REVIEW_BETS: FinishedWithReviewBetsRound,
            Event.NONE: CheckStopTradingRound,
            Event.ROUND_TIMEOUT: CheckStopTradingRound,
            Event.NO_MAJORITY: CheckStopTradingRound,
            Event.SKIP_TRADING: FinishedWithSkipTradingRound,
            Event.WITHDRAW_POLYMARKET: FinishedWithWithdrawalPolymarketRound,
            Event.WITHDRAW_OMEN: FinishedWithWithdrawalOmenRound,
        },
        FinishedCheckStopTradingRound: {},
        FinishedWithSkipTradingRound: {},
        FinishedWithReviewBetsRound: {},
        FinishedWithWithdrawalPolymarketRound: {},
        FinishedWithWithdrawalOmenRound: {},
    }
    assert abci_app.event_to_timeout == {Event.ROUND_TIMEOUT: 30.0}
    assert abci_app.db_pre_conditions == {CheckStopTradingRound: set()}
    assert abci_app.db_post_conditions == {
        FinishedCheckStopTradingRound: set(),
        FinishedWithSkipTradingRound: set(),
        FinishedWithReviewBetsRound: set(),
        FinishedWithWithdrawalPolymarketRound: set(),
        FinishedWithWithdrawalOmenRound: set(),
    }


def test_synchronized_data_initialization() -> None:
    """Test the initialization and attributes of SynchronizedData."""
    data = SynchronizedData(db=AbciAppDB(setup_data={"test": ["test"]}))
    assert data.db._data == {0: {"test": ["test"]}}


class TestSynchronizedDataProperties:
    """Tests for SynchronizedData property methods."""

    def test_get_deserialized(self) -> None:
        """_get_deserialized calls db.get_strict and deserializes."""
        mock_db = MagicMock()
        mock_db.get_strict.return_value = {"agent_0": {"some": "data"}}
        data = SynchronizedData(db=mock_db)
        expected = {"agent_0": MagicMock()}
        with patch(
            "packages.valory.skills.check_stop_trading_abci.rounds.CollectionRound.deserialize_collection",
            return_value=expected,
        ):
            result = data._get_deserialized("votes")
        mock_db.get_strict.assert_called_once_with("votes")
        assert result is expected

    def test_is_staking_kpi_met_default(self) -> None:
        """is_staking_kpi_met defaults to False."""
        data = SynchronizedData(db=AbciAppDB(setup_data={}))
        assert data.is_staking_kpi_met is False

    def test_is_staking_kpi_met_true(self) -> None:
        """is_staking_kpi_met returns True when set."""
        data = SynchronizedData(db=AbciAppDB(setup_data={"is_staking_kpi_met": [True]}))
        assert data.is_staking_kpi_met is True

    def test_review_bets_for_selling_default(self) -> None:
        """review_bets_for_selling defaults to False when not set."""
        data = SynchronizedData(db=AbciAppDB(setup_data={}))
        assert data.review_bets_for_selling is False

    def test_review_bets_for_selling_non_bool(self) -> None:
        """review_bets_for_selling returns False when value is not bool."""
        data = SynchronizedData(
            db=AbciAppDB(setup_data={"review_bets_for_selling": ["yes"]})
        )
        assert data.review_bets_for_selling is False

    def test_review_bets_for_selling_true(self) -> None:
        """review_bets_for_selling returns True when bool True is stored."""
        data = SynchronizedData(
            db=AbciAppDB(setup_data={"review_bets_for_selling": [True]})
        )
        assert data.review_bets_for_selling is True


class TestCheckStopTradingRoundShouldReviewBets:
    """Tests for CheckStopTradingRound.should_review_bets."""

    def test_not_kpi_met(self) -> None:
        """When KPI is not met, should not review bets."""
        round_ = CheckStopTradingRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        assert round_.should_review_bets(is_staking_kpi_met=False) is False

    def test_kpi_met_review_disabled(self) -> None:
        """When KPI met but position review disabled, should not review."""
        round_ = CheckStopTradingRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        round_.context.params.enable_position_review = False
        assert round_.should_review_bets(is_staking_kpi_met=True) is False


# ---------------------------------------------------------------------------
# Withdrawal gate (D14, §6.1)
# ---------------------------------------------------------------------------


class TestWithdrawalEventEnum:
    """Tests for the Event enum extension."""

    def test_withdraw_polymarket_event_exists(self) -> None:
        """The Event enum must include WITHDRAW_POLYMARKET."""
        assert hasattr(Event, "WITHDRAW_POLYMARKET")

    def test_withdraw_omen_event_exists(self) -> None:
        """The Event enum must include WITHDRAW_OMEN."""
        assert hasattr(Event, "WITHDRAW_OMEN")


class TestWithdrawalDegenerateRounds:
    """Tests for the degenerate rounds reached via the withdrawal events."""

    def test_finished_with_withdrawal_polymarket_round_initialization(
        self,
    ) -> None:
        """FinishedWithWithdrawalPolymarketRound is constructable."""
        round_ = FinishedWithWithdrawalPolymarketRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        assert isinstance(round_, FinishedWithWithdrawalPolymarketRound)

    def test_finished_with_withdrawal_omen_round_initialization(self) -> None:
        """FinishedWithWithdrawalOmenRound is constructable."""
        round_ = FinishedWithWithdrawalOmenRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        assert isinstance(round_, FinishedWithWithdrawalOmenRound)


class TestAbciAppWithdrawalWiring:
    """The AbciApp transition function and final-state set must include withdrawal."""

    def test_done_event_routes_through_withdrawal_when_armed(self) -> None:
        """The transition function must include WITHDRAW_POLYMARKET / WITHDRAW_OMEN entries."""
        tx_function = CheckStopTradingAbciApp.transition_function
        assert (
            tx_function[CheckStopTradingRound][Event.WITHDRAW_POLYMARKET]
            is FinishedWithWithdrawalPolymarketRound
        )
        assert (
            tx_function[CheckStopTradingRound][Event.WITHDRAW_OMEN]
            is FinishedWithWithdrawalOmenRound
        )

    def test_final_states_include_withdrawal_terminals(self) -> None:
        """The final_states set must include the two withdrawal terminals."""
        assert (
            FinishedWithWithdrawalPolymarketRound
            in CheckStopTradingAbciApp.final_states
        )
        assert FinishedWithWithdrawalOmenRound in CheckStopTradingAbciApp.final_states

    def test_db_post_conditions_include_withdrawal_terminals(self) -> None:
        """The db_post_conditions map must include the new degenerate rounds."""
        assert (
            FinishedWithWithdrawalPolymarketRound
            in CheckStopTradingAbciApp.db_post_conditions
        )
        assert (
            FinishedWithWithdrawalOmenRound
            in CheckStopTradingAbciApp.db_post_conditions
        )


def _make_round_with_disk_flag(
    *,
    is_polymarket: bool,
    withdrawal_mode: bool,
    withdrawal_state: str,
) -> CheckStopTradingRound:
    """Construct a CheckStopTradingRound wired for end_block branching tests.

    The super().end_block() return value is controlled by patching
    VotingRound.end_block in the test itself; this helper only sets up the
    context params and the disk-flag helper.
    """
    sync_data = MagicMock()
    context = MagicMock()
    context.params.is_running_on_polymarket = is_polymarket
    context.params.enable_position_review = False
    context.params.review_period_seconds = 60 * 60 * 24
    context.params.store_path = "/dev/null"
    round_ = CheckStopTradingRound(synchronized_data=sync_data, context=context)
    round_._read_withdrawal_flag = MagicMock(  # type: ignore[method-assign]
        return_value=(withdrawal_mode, withdrawal_state)
    )
    return round_


class TestEndBlockWithdrawalBranching:
    """Tests for the new withdrawal branch in CheckStopTradingRound.end_block."""

    def _run_end_block(
        self,
        round_: CheckStopTradingRound,
        super_event: Optional[Event],
        *,
        kpi_met: bool = False,
    ) -> Optional[Tuple[Any, Event]]:
        """Run end_block while patching super().end_block() and the KPI property."""
        from unittest.mock import PropertyMock

        if super_event is None:
            super_value = None
        else:
            sync = MagicMock()
            sync.update = MagicMock(return_value=sync)
            super_value = (sync, super_event)

        with (
            patch.object(VotingRound, "end_block", return_value=super_value),
            patch.object(
                VotingRound,
                "positive_vote_threshold_reached",
                new_callable=PropertyMock,
                return_value=kpi_met,
            ),
        ):
            return round_.end_block()  # type: ignore[return-value]

    def test_done_with_polymarket_flag_emits_withdraw_polymarket(self) -> None:
        """flag=True + venue=polymarket + super=DONE → WITHDRAW_POLYMARKET."""
        round_ = _make_round_with_disk_flag(
            is_polymarket=True,
            withdrawal_mode=True,
            withdrawal_state="armed",
        )
        result = self._run_end_block(round_, Event.DONE)

        assert result is not None
        _, event = result
        assert event == Event.WITHDRAW_POLYMARKET

    def test_done_with_omen_flag_emits_withdraw_omen(self) -> None:
        """flag=True + venue=omen + super=DONE → WITHDRAW_OMEN."""
        round_ = _make_round_with_disk_flag(
            is_polymarket=False,
            withdrawal_mode=True,
            withdrawal_state="armed",
        )
        result = self._run_end_block(round_, Event.DONE)

        assert result is not None
        _, event = result
        assert event == Event.WITHDRAW_OMEN

    def test_done_with_flag_off_emits_done(self) -> None:
        """flag=False + super=DONE → DONE (existing behaviour preserved)."""
        round_ = _make_round_with_disk_flag(
            is_polymarket=True,
            withdrawal_mode=False,
            withdrawal_state="idle",
        )
        result = self._run_end_block(round_, Event.DONE)

        assert result is not None
        _, event = result
        assert event == Event.DONE

    def test_complete_state_does_not_re_enter_withdrawal(self) -> None:
        """flag=True + state=complete → DONE (don't re-trigger after completion)."""
        round_ = _make_round_with_disk_flag(
            is_polymarket=True,
            withdrawal_mode=True,
            withdrawal_state="complete",
        )
        result = self._run_end_block(round_, Event.DONE)

        assert result is not None
        _, event = result
        assert event == Event.DONE

    def test_skip_trading_takes_priority_over_withdrawal(self) -> None:
        """flag=True + super=SKIP_TRADING → SKIP_TRADING (skip trumps withdraw)."""
        round_ = _make_round_with_disk_flag(
            is_polymarket=True,
            withdrawal_mode=True,
            withdrawal_state="armed",
        )
        result = self._run_end_block(round_, Event.SKIP_TRADING, kpi_met=True)

        assert result is not None
        _, event = result
        assert event == Event.SKIP_TRADING

    def test_super_returns_none_returns_none(self) -> None:
        """If super().end_block returns None (no consensus), pass through None."""
        round_ = _make_round_with_disk_flag(
            is_polymarket=True,
            withdrawal_mode=True,
            withdrawal_state="armed",
        )
        result = self._run_end_block(round_, None)

        assert result is None


class TestReadWithdrawalFlag:
    """Tests for the disk-read helper that the gate uses."""

    def test_missing_file_returns_off_idle(self, tmp_path: Any) -> None:
        """A missing chatui_param_store.json returns (False, 'idle')."""
        round_ = CheckStopTradingRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        mode, state = round_._read_withdrawal_flag(tmp_path)
        assert mode is False
        assert state == "idle"

    def test_invalid_json_returns_off_idle(self, tmp_path: Any) -> None:
        """An unparseable JSON file returns (False, 'idle') without crashing."""
        store_file = tmp_path / "chatui_param_store.json"
        store_file.write_text("not-valid-json{{{")

        round_ = CheckStopTradingRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        mode, state = round_._read_withdrawal_flag(tmp_path)
        assert mode is False
        assert state == "idle"

    def test_valid_json_returns_persisted_values(self, tmp_path: Any) -> None:
        """Valid JSON roundtrips its withdrawal_mode and withdrawal_state."""
        store_file = tmp_path / "chatui_param_store.json"
        store_file.write_text(
            json.dumps({"withdrawal_mode": True, "withdrawal_state": "armed"})
        )

        round_ = CheckStopTradingRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        mode, state = round_._read_withdrawal_flag(tmp_path)
        assert mode is True
        assert state == "armed"

    def test_missing_keys_default_to_off_idle(self, tmp_path: Any) -> None:
        """A JSON store without the withdrawal keys returns (False, 'idle')."""
        store_file = tmp_path / "chatui_param_store.json"
        store_file.write_text(json.dumps({"trading_strategy": "kelly_criterion"}))

        round_ = CheckStopTradingRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        mode, state = round_._read_withdrawal_flag(tmp_path)
        assert mode is False
        assert state == "idle"


class TestCheckStopTradingParamsIsRunningOnPolymarket:
    """Tests for the is_running_on_polymarket attribute on CheckStopTradingParams."""

    def test_param_loaded_true(self) -> None:
        """is_running_on_polymarket=True flows through __init__."""
        from packages.valory.skills.check_stop_trading_abci.models import (
            CheckStopTradingParams,
        )

        params = object.__new__(CheckStopTradingParams)
        kwargs = {"is_running_on_polymarket": True}
        # Use the private helper directly to avoid wiring the full param chain.
        # The implementation must read this kwarg into the attribute.
        CheckStopTradingParams._read_polymarket_flag(params, kwargs)  # type: ignore[attr-defined]
        assert params.is_running_on_polymarket is True

    def test_param_loaded_false(self) -> None:
        """is_running_on_polymarket=False flows through __init__."""
        from packages.valory.skills.check_stop_trading_abci.models import (
            CheckStopTradingParams,
        )

        params = object.__new__(CheckStopTradingParams)
        kwargs = {"is_running_on_polymarket": False}
        CheckStopTradingParams._read_polymarket_flag(params, kwargs)  # type: ignore[attr-defined]
        assert params.is_running_on_polymarket is False
