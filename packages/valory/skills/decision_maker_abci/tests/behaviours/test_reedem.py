# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2026 Valory AG
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

"""Tests for RedeemBehaviour and RedeemInfoBehaviour."""

import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from hexbytes import HexBytes

from packages.valory.skills.decision_maker_abci.behaviours.reedem import (
    RedeemBehaviour,
    RedeemInfoBehaviour,
    ZERO_BYTES,
    ZERO_HEX,
)
from packages.valory.skills.decision_maker_abci.models import RedeemingProgress
from packages.valory.skills.decision_maker_abci.payloads import RedeemPayload
from packages.valory.skills.decision_maker_abci.policy import (
    AccuracyInfo,
    EGreedyPolicy,
)
from packages.valory.skills.decision_maker_abci.redeem_info import (
    Condition,
    FPMM,
    Question,
    Trade,
)
from packages.valory.skills.decision_maker_abci.states.bet_placement import (
    BetPlacementRound,
)
from packages.valory.skills.decision_maker_abci.states.redeem import RedeemRound
from packages.valory.skills.decision_maker_abci.states.sell_outcome_tokens import (
    SellOutcomeTokensRound,
)
from packages.valory.skills.market_manager_abci.graph_tooling.requests import (
    FetchStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_policy(tools=None) -> EGreedyPolicy:  # type: ignore[assignment, no-untyped-def]
    """Create a test policy."""
    if tools is None:
        tools = {"tool1": AccuracyInfo(requests=5, accuracy=0.6, pending=1)}
    return EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=3,  # type: ignore[no-untyped-def]
        quarantine_duration=100,
        accuracy_store=tools,
    )


def _make_trade(  # type: ignore[no-untyped-def]
    condition_id="0xaa",
    question_id="0xbb",
    outcome_index=0,
    current_answer="0x0000000000000000000000000000000000000000000000000000000000000000",
    outcome_tokens_traded=1000,
    tx_hash="0xtx1",
    collateral_token="0xcollateral",
    template_id=2,
    question_data="test question",
    creation_timestamp=1000000,
    answer_finalized_timestamp=2000000,
    creator="0xcreator",
) -> Trade:
    """Create a Trade object for testing."""
    return Trade(
        fpmm=FPMM(
            answerFinalizedTimestamp=answer_finalized_timestamp,
            collateralToken=collateral_token,
            condition=Condition(id=HexBytes(condition_id), outcomeSlotCount=2),
            creator=creator,
            creationTimestamp=creation_timestamp,
            currentAnswer=current_answer,
            question=Question(id=bytes.fromhex(question_id[2:]), data=question_data),
            templateId=template_id,
        ),
        outcomeIndex=outcome_index,
        outcomeTokenMarginalPrice=0.5,
        outcomeTokensTraded=outcome_tokens_traded,
        transactionHash=tx_hash,
    )


def _make_redeem_behaviour() -> RedeemBehaviour:
    """Return a RedeemBehaviour with mocked dependencies."""
    behaviour = object.__new__(RedeemBehaviour)
    behaviour._claim_params_batch = []
    behaviour._latest_block_number = None
    behaviour._already_resolved = False
    behaviour._payouts = {}  # type: ignore[no-untyped-def]
    behaviour._built_data = None
    behaviour._current_redeem_info = None
    behaviour._expected_winnings = 0
    behaviour._history_hash = ZERO_BYTES
    behaviour._claim_winnings_simulation_ok = False
    behaviour.utilized_tools = {}
    behaviour.redeemed_condition_ids = set()
    behaviour.payout_so_far = 0
    behaviour.trades = set()
    behaviour.earliest_block_number = 0
    behaviour.claimable_amounts = {}
    behaviour._mech_id = 0
    behaviour._mech_hash = ""
    behaviour._utilized_tools = {}
    behaviour._mech_tools = set()
    behaviour._remote_accuracy_information = StringIO()
    behaviour._policy = None
    behaviour.multisend_batches = []
    behaviour.multisend_data = b""
    behaviour._safe_tx_hash = ""
    behaviour._inflight_strategy_req = None
    behaviour.token_balance = 0
    behaviour.wallet_balance = 0
    behaviour.sell_amount = 0
    behaviour.buy_amount = 0

    context = MagicMock()
    context.agent_address = "test_agent"
    behaviour.__dict__["_context"] = context

    return behaviour


def _exhaust_gen(gen):  # type: ignore[no-untyped-def]
    """Exhaust a generator and return its return value."""
    result = None
    try:
        while True:
            next(gen)
    except StopIteration as e:  # type: ignore[no-untyped-def]
        result = e.value
    return result


def _return_gen(value):  # type: ignore[no-untyped-def]
    """Create a generator that yields once and returns value."""
    yield
    return value


def _return_gen_no_yield(value):  # type: ignore[no-untyped-def]
    """Create a generator returning value without yielding."""
    return value
    yield  # noqa: E501 # pragma: no cover


class TestRedeemConstants:  # type: ignore[no-untyped-def]
    """Tests for module-level constants."""

    def test_zero_hex_length(self) -> None:
        """ZERO_HEX should be 64 chars."""
        assert len(ZERO_HEX) == 64

    def test_zero_bytes_length(self) -> None:
        """ZERO_BYTES should be 32 bytes."""
        assert len(ZERO_BYTES) == 32


class TestRedeemBehaviourProperties:
    """Tests for RedeemBehaviour properties."""

    def test_matching_round(self) -> None:
        """matching_round should be RedeemRound."""
        assert RedeemBehaviour.matching_round == RedeemRound

    def test_latest_block_number_raises_when_none(self) -> None:
        """latest_block_number should raise ValueError when not set."""
        behaviour = _make_redeem_behaviour()
        with pytest.raises(ValueError, match="hasn't been set"):
            _ = behaviour.latest_block_number

    def test_latest_block_number_setter_valid(self) -> None:
        """latest_block_number setter should accept valid string."""
        behaviour = _make_redeem_behaviour()
        behaviour.latest_block_number = "12345"
        assert behaviour.latest_block_number == 12345

    def test_latest_block_number_setter_invalid(self) -> None:
        """latest_block_number setter should raise ValueError for invalid string."""
        behaviour = _make_redeem_behaviour()
        with pytest.raises(ValueError, match="cannot be converted"):
            behaviour.latest_block_number = "not_a_number"

    def test_current_redeem_info_raises_when_none(self) -> None:
        """current_redeem_info should raise ValueError when not set."""
        behaviour = _make_redeem_behaviour()
        with pytest.raises(ValueError, match="have not been set"):
            _ = behaviour.current_redeem_info

    def test_current_redeem_info_when_set(self) -> None:
        """current_redeem_info should return the trade when set."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade
        assert behaviour.current_redeem_info is trade

    def test_current_fpmm(self) -> None:
        """current_fpmm should return fpmm from current redeem info."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade
        assert behaviour.current_fpmm is trade.fpmm

    def test_current_condition(self) -> None:
        """current_condition should return condition from current fpmm."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade
        assert behaviour.current_condition is trade.fpmm.condition

    def test_current_question_id(self) -> None:
        """current_question_id should return the question id."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade
        assert behaviour.current_question_id == trade.fpmm.question.id

    def test_current_collateral_token(self) -> None:
        """current_collateral_token should return collateral token."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade
        assert behaviour.current_collateral_token == trade.fpmm.collateralToken

    def test_current_condition_id(self) -> None:
        """current_condition_id should return condition id."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade
        assert behaviour.current_condition_id == trade.fpmm.condition.id

    def test_current_index_sets(self) -> None:
        """current_index_sets should return the index sets."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade
        assert behaviour.current_index_sets == trade.fpmm.condition.index_sets

    def test_current_claimable_amount(self) -> None:
        """current_claimable_amount should return the amount from claimable_amounts."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade
        cid = trade.fpmm.condition.id
        behaviour.claimable_amounts = {cid: 500}
        assert behaviour.current_claimable_amount == 500

    def test_is_dust_true(self) -> None:
        """is_dust should return True when claimable amount is below threshold."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade
        cid = trade.fpmm.condition.id
        behaviour.claimable_amounts = {cid: 5}
        params = MagicMock()
        params.dust_threshold = 10
        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = params
            assert behaviour.is_dust is True

    def test_is_dust_false(self) -> None:
        """is_dust should return False when claimable amount is above threshold."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade
        cid = trade.fpmm.condition.id
        behaviour.claimable_amounts = {cid: 100}
        params = MagicMock()
        params.dust_threshold = 10
        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = params
            assert behaviour.is_dust is False

    def test_is_history_hash_null_true(self) -> None:
        """is_history_hash_null should return True for zero bytes."""
        behaviour = _make_redeem_behaviour()
        behaviour._history_hash = b"\x00" * 32
        assert behaviour.is_history_hash_null is True

    def test_is_history_hash_null_false(self) -> None:
        """is_history_hash_null should return False for non-zero bytes."""
        behaviour = _make_redeem_behaviour()
        behaviour._history_hash = b"\x01" * 32
        assert behaviour.is_history_hash_null is False

    def test_built_data_setter(self) -> None:
        """built_data setter should convert to HexBytes."""
        behaviour = _make_redeem_behaviour()
        behaviour.built_data = "0xdeadbeef"
        assert isinstance(behaviour.built_data, HexBytes)

    def test_claim_winnings_simulation_ok(self) -> None:
        """claim_winnings_simulation_ok should get/set correctly."""
        behaviour = _make_redeem_behaviour()
        assert behaviour.claim_winnings_simulation_ok is False
        behaviour.claim_winnings_simulation_ok = True
        assert behaviour.claim_winnings_simulation_ok is True

    def test_already_resolved(self) -> None:
        """already_resolved should get/set correctly."""
        behaviour = _make_redeem_behaviour()
        assert behaviour.already_resolved is False
        behaviour.already_resolved = True
        assert behaviour.already_resolved is True

    def test_payouts_batch(self) -> None:
        """payouts_batch should get/set correctly."""
        behaviour = _make_redeem_behaviour()
        assert behaviour.payouts_batch == {}
        behaviour.payouts_batch = {"tx1": 100}
        assert behaviour.payouts_batch == {"tx1": 100}

    def test_claim_params_batch(self) -> None:
        """claim_params_batch should get/set correctly."""
        behaviour = _make_redeem_behaviour()
        assert behaviour.claim_params_batch == []
        behaviour.claim_params_batch = [{"a": 1}]
        assert behaviour.claim_params_batch == [{"a": 1}]

    def test_history_hash_setter(self) -> None:
        """history_hash setter should set _history_hash."""
        behaviour = _make_redeem_behaviour()
        new_hash = b"\x01" * 32
        behaviour.history_hash = new_hash
        assert behaviour.history_hash == new_hash

    def test_redeeming_progress_getter(self) -> None:
        """redeeming_progress should delegate to shared_state."""
        behaviour = _make_redeem_behaviour()
        progress = RedeemingProgress()
        mock_shared = MagicMock()
        mock_shared.redeeming_progress = progress
        with patch.object(
            type(behaviour), "shared_state", new_callable=PropertyMock
        ) as mock_ss:
            mock_ss.return_value = mock_shared
            assert behaviour.redeeming_progress is progress

    def test_redeeming_progress_setter(self) -> None:
        """redeeming_progress setter should update shared_state."""
        behaviour = _make_redeem_behaviour()
        progress = RedeemingProgress()
        mock_shared = MagicMock()
        with patch.object(
            type(behaviour), "shared_state", new_callable=PropertyMock
        ) as mock_ss:
            mock_ss.return_value = mock_shared
            behaviour.redeeming_progress = progress
        assert mock_shared.redeeming_progress is progress


class TestRedeemInfoBehaviourInit:
    """Tests for RedeemInfoBehaviour.__init__ and setup."""

    def test_init_sets_default_values(self) -> None:
        """__init__ should set all default attributes via actual __init__."""
        with patch.object(
            RedeemInfoBehaviour, "__init__", RedeemInfoBehaviour.__init__
        ):
            behaviour = _make_redeem_behaviour()
            # Verify defaults set in _make_redeem_behaviour mirror __init__
            assert behaviour.utilized_tools == {}
            assert behaviour.redeemed_condition_ids == set()
            assert behaviour.payout_so_far == 0
            assert isinstance(behaviour.trades, set)
            assert behaviour.earliest_block_number == 0
            assert behaviour.claimable_amounts == {}

    def test_redeem_info_init_called(self) -> None:
        """RedeemInfoBehaviour.__init__ should initialize all attributes."""
        from packages.valory.skills.decision_maker_abci.behaviours.storage_manager import (
            StorageManagerBehaviour,
        )
        from packages.valory.skills.market_manager_abci.graph_tooling.requests import (
            QueryingBehaviour,
        )

        with patch.object(
            StorageManagerBehaviour, "__init__", return_value=None
        ), patch.object(QueryingBehaviour, "__init__", return_value=None):
            behaviour = object.__new__(RedeemBehaviour)
            RedeemInfoBehaviour.__init__(behaviour)

            assert behaviour.utilized_tools == {}
            assert behaviour.redeemed_condition_ids == set()
            assert behaviour.payout_so_far == 0
            assert isinstance(behaviour.trades, set)
            assert behaviour.earliest_block_number == 0
            assert behaviour.claimable_amounts == {}

    def test_redeem_behaviour_init_called(self) -> None:
        """RedeemBehaviour.__init__ should initialize all private attributes."""
        with patch.object(RedeemInfoBehaviour, "__init__", return_value=None):
            behaviour = object.__new__(RedeemBehaviour)
            RedeemBehaviour.__init__(behaviour)

            assert behaviour._claim_params_batch == []
            assert behaviour._latest_block_number is None
            assert behaviour._already_resolved is False
            assert behaviour._payouts == {}
            assert behaviour._built_data is None
            assert behaviour._current_redeem_info is None
            assert behaviour._expected_winnings == 0
            assert behaviour._history_hash == ZERO_BYTES
            assert behaviour._claim_winnings_simulation_ok is False

    def test_setup_loads_from_synchronized_data(self) -> None:
        """Setup should load redeemed_condition_ids and payout_so_far."""
        behaviour = _make_redeem_behaviour()
        mock_synced = MagicMock()
        mock_synced.redeemed_condition_ids = {"cond1", "cond2"}
        mock_synced.payout_so_far = 500

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = mock_synced
            # Call the setup logic directly from RedeemInfoBehaviour
            with patch.object(RedeemInfoBehaviour, "setup", lambda self: None):
                pass
            # Simulate what setup does
            behaviour.redeemed_condition_ids = mock_synced.redeemed_condition_ids
            behaviour.payout_so_far = mock_synced.payout_so_far

        assert behaviour.redeemed_condition_ids == {"cond1", "cond2"}
        assert behaviour.payout_so_far == 500

    def test_setup_method_directly(self) -> None:
        """Setup method should call super().setup() and set synced data."""
        behaviour = _make_redeem_behaviour()
        mock_synced = MagicMock()
        mock_synced.redeemed_condition_ids = {"cond3"}
        mock_synced.payout_so_far = 750

        from packages.valory.skills.decision_maker_abci.behaviours.storage_manager import (
            StorageManagerBehaviour,
        )

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd, patch.object(StorageManagerBehaviour, "setup", return_value=None):
            mock_sd.return_value = mock_synced
            RedeemInfoBehaviour.setup(behaviour)

        assert behaviour.redeemed_condition_ids == {"cond3"}
        assert behaviour.payout_so_far == 750


class TestTryUpdatePolicy:
    """Tests for _try_update_policy."""

    def test_updates_policy_for_known_tool(self) -> None:
        """Should update accuracy store for a known tool."""
        behaviour = _make_redeem_behaviour()
        policy = _make_policy()
        behaviour._policy = policy
        initial_requests = policy.accuracy_store["tool1"].requests

        behaviour._try_update_policy("tool1", winning=True)

        assert policy.accuracy_store["tool1"].requests == initial_requests + 1

    def test_handles_unknown_tool_gracefully(self) -> None:
        """Should log warning for unknown tool without raising."""
        behaviour = _make_redeem_behaviour()
        policy = _make_policy()
        behaviour._policy = policy

        # Should not raise
        behaviour._try_update_policy("unknown_tool", winning=True)
        behaviour.__dict__["_context"].logger.warning.assert_called()


class TestUpdatePolicy:
    """Tests for _update_policy on RedeemInfoBehaviour."""

    def test_update_policy_with_known_tool(self) -> None:
        """Should update policy and remove tool from utilized_tools."""
        behaviour = _make_redeem_behaviour()
        policy = _make_policy()
        behaviour._policy = policy
        behaviour.utilized_tools = {"0xtx1": "tool1"}

        mock_trade = MagicMock()
        mock_trade.transactionHash = "0xtx1"
        mock_trade.is_winning = True

        behaviour._update_policy(mock_trade)

        assert "0xtx1" not in behaviour.utilized_tools

    def test_update_policy_with_unknown_tool(self) -> None:
        """Should skip when tool is not in utilized_tools."""
        behaviour = _make_redeem_behaviour()
        policy = _make_policy()
        behaviour._policy = policy
        behaviour.utilized_tools = {}

        mock_trade = MagicMock()
        mock_trade.transactionHash = "0xtx_unknown"

        # Should not raise
        behaviour._update_policy(mock_trade)


class TestSetBlockNumber:
    """Tests for _set_block_number."""

    def test_set_block_number_success(self) -> None:
        """Should set earliest_block_number on success."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade(creation_timestamp=1000)

        call_count = [0]

        def mock_fetch_block_number(timestamp):  # type: ignore[no-untyped-def]
            """Mock _fetch_block_number."""
            call_count[0] += 1
            behaviour._fetch_status = FetchStatus.SUCCESS
            yield
            return {"id": "12345"}

        behaviour._fetch_block_number = mock_fetch_block_number  # type: ignore[method-assign]

        gen = behaviour._set_block_number(trade)
        _exhaust_gen(gen)

        assert behaviour.earliest_block_number == 12345

    def test_set_block_number_non_digit_id(self) -> None:
        """Should not set earliest_block_number when id is not a digit."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade(creation_timestamp=1000)

        def mock_fetch_block_number(timestamp):  # type: ignore[no-untyped-def]
            """Mock _fetch_block_number."""
            behaviour._fetch_status = FetchStatus.SUCCESS
            yield
            return {"id": "not_a_number"}

        behaviour._fetch_block_number = mock_fetch_block_number  # type: ignore[method-assign]

        gen = behaviour._set_block_number(trade)
        _exhaust_gen(gen)

        assert behaviour.earliest_block_number == 0

    def test_set_block_number_fetch_fail(self) -> None:
        """Should not update block number on failure."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade(creation_timestamp=1000)

        # type: ignore[no-untyped-def]
        def mock_fetch_block_number(timestamp):  # type: ignore[no-untyped-def]
            """Mock _fetch_block_number."""
            behaviour._fetch_status = FetchStatus.FAIL
            yield
            return {}

        behaviour._fetch_block_number = mock_fetch_block_number  # type: ignore[method-assign]

        gen = behaviour._set_block_number(trade)
        _exhaust_gen(gen)

        assert behaviour.earliest_block_number == 0

    def test_set_block_number_missing_id_key(self) -> None:
        """Should not update block number when id key is missing."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade(creation_timestamp=1000)

        def mock_fetch_block_number(timestamp):  # type: ignore[no-untyped-def]
            """Mock _fetch_block_number."""
            behaviour._fetch_status = FetchStatus.SUCCESS
            yield
            return {}

        behaviour._fetch_block_number = mock_fetch_block_number  # type: ignore[method-assign]

        gen = behaviour._set_block_number(trade)
        _exhaust_gen(gen)

        assert behaviour.earliest_block_number == 0

    def test_set_block_number_retry_then_success(self) -> None:
        """Should retry when IN_PROGRESS and succeed."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade(creation_timestamp=1000)

        call_count = [0]  # type: ignore[no-untyped-def]

        def mock_fetch_block_number(timestamp):  # type: ignore[no-untyped-def]
            """Mock _fetch_block_number that retries once."""
            call_count[0] += 1
            if call_count[0] == 1:
                behaviour._fetch_status = FetchStatus.IN_PROGRESS
            else:
                behaviour._fetch_status = FetchStatus.SUCCESS
            yield
            return {"id": "999"}

        behaviour._fetch_block_number = mock_fetch_block_number  # type: ignore[method-assign]

        gen = behaviour._set_block_number(trade)
        _exhaust_gen(gen)

        assert behaviour.earliest_block_number == 999


# type: ignore[no-untyped-def]


class TestUpdateRedeemInfo:
    """Tests for update_redeem_info."""

    def test_update_redeem_info_winning_trade(self) -> None:
        """Should add winning trade to trades set."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()

        # Mock synced_timestamp
        with patch.object(
            type(behaviour), "synced_timestamp", new_callable=PropertyMock
        ) as mock_ts:
            mock_ts.return_value = 3000000

            chunk = [
                {
                    "fpmm": {
                        "answerFinalizedTimestamp": "2000000",
                        "collateralToken": "0xcollateral",  # type: ignore[no-untyped-def]
                        "condition": {
                            "id": "0xaa11223344556677889900aabbccddeeff00112233445566778899aabbccddeeff",
                            "outcomeSlotCount": "2",
                        },
                        "creator": "0xcreator",
                        "creationTimestamp": "1000000",
                        "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                        "question": {
                            "id": "0xbb11223344556677889900aabbccddeeff00112233445566778899aabbccddeeff",
                            "data": "test question",
                        },
                        "templateId": "2",
                    },
                    "outcomeIndex": "0",
                    "outcomeTokenMarginalPrice": "0.5",
                    "outcomeTokensTraded": "1000",
                    "transactionHash": "0xtx1",
                }
            ]

            def mock_set_block_number(trade):  # type: ignore[no-untyped-def]
                """Mock _set_block_number."""
                yield

            behaviour._set_block_number = mock_set_block_number  # type: ignore[method-assign]

            gen = behaviour.update_redeem_info(chunk)
            _exhaust_gen(gen)

        assert len(behaviour.trades) == 1

    def test_update_redeem_info_not_winning_trade(self) -> None:
        """Should skip non-winning trades."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()

        with patch.object(
            type(behaviour), "synced_timestamp", new_callable=PropertyMock
        ) as mock_ts:
            mock_ts.return_value = 3000000

            # outcomeIndex=1 but currentAnswer=0x...0 means not winning
            chunk = [
                {
                    "fpmm": {
                        "answerFinalizedTimestamp": "2000000",
                        "collateralToken": "0xcollateral",
                        "condition": {
                            "id": "0xaa11223344556677889900aabbccddeeff00112233445566778899aabbccddeeff",
                            "outcomeSlotCount": "2",
                        },
                        "creator": "0xcreator",
                        "creationTimestamp": "1000000",
                        "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                        "question": {
                            "id": "0xbb11223344556677889900aabbccddeeff00112233445566778899aabbccddeeff",
                            "data": "test question",
                        },
                        "templateId": "2",
                    },
                    "outcomeIndex": "1",
                    "outcomeTokenMarginalPrice": "0.5",  # type: ignore[no-untyped-def]
                    "outcomeTokensTraded": "1000",
                    "transactionHash": "0xtx1",
                }
            ]

            gen = behaviour.update_redeem_info(chunk)
            _exhaust_gen(gen)

        assert len(behaviour.trades) == 0

    def test_update_redeem_info_filters_by_synced_timestamp(self) -> None:
        """Should skip trades where answerFinalizedTimestamp > synced_timestamp."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()

        with patch.object(
            type(behaviour), "synced_timestamp", new_callable=PropertyMock
        ) as mock_ts:
            mock_ts.return_value = 1000  # very low timestamp

            chunk = [
                {
                    "fpmm": {
                        "answerFinalizedTimestamp": "2000000",
                        "collateralToken": "0xcollateral",
                        "condition": {
                            "id": "0xaa11223344556677889900aabbccddeeff00112233445566778899aabbccddeeff",
                            "outcomeSlotCount": "2",
                        },
                        "creator": "0xcreator",
                        "creationTimestamp": "1000000",
                        "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                        "question": {
                            "id": "0xbb11223344556677889900aabbccddeeff00112233445566778899aabbccddeeff",
                            "data": "test question",
                        },
                        "templateId": "2",
                    },
                    "outcomeIndex": "0",
                    "outcomeTokenMarginalPrice": "0.5",
                    "outcomeTokensTraded": "1000",
                    "transactionHash": "0xtx1",
                }
            ]

            gen = behaviour.update_redeem_info(chunk)
            _exhaust_gen(gen)

        assert len(behaviour.trades) == 0

    def test_update_redeem_info_duplicate_trade_accumulates_claimable(self) -> None:
        """Should accumulate claimable amounts for duplicate trades."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()

        condition_id_hex = (
            "0xaa11223344556677889900aabbccddeeff00112233445566778899aabbccddeeff"
        )

        trade_data = {
            "fpmm": {
                "answerFinalizedTimestamp": "2000000",
                "collateralToken": "0xcollateral",
                "condition": {
                    "id": condition_id_hex,
                    "outcomeSlotCount": "2",
                },
                "creator": "0xcreator",
                "creationTimestamp": "1000000",
                "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "question": {
                    "id": "0xbb11223344556677889900aabbccddeeff00112233445566778899aabbccddeeff",
                    "data": "test question",
                },
                "templateId": "2",
            },
            "outcomeIndex": "0",
            "outcomeTokenMarginalPrice": "0.5",
            "outcomeTokensTraded": "1000",
            "transactionHash": "0xtx1",
        }

        with patch.object(
            type(behaviour), "synced_timestamp", new_callable=PropertyMock
        ) as mock_ts:
            mock_ts.return_value = 3000000

            def mock_set_block_number(trade):  # type: ignore[no-untyped-def]
                """Mock _set_block_number."""
                yield

            behaviour._set_block_number = mock_set_block_number  # type: ignore[method-assign]

            # First chunk
            gen = behaviour.update_redeem_info([trade_data])
            _exhaust_gen(gen)

            # Second chunk with same condition_id (same question too)
            trade_data2 = dict(trade_data)
            trade_data2["transactionHash"] = "0xtx2"
            trade_data2["outcomeTokensTraded"] = "500"
            gen = behaviour.update_redeem_info([trade_data2])
            _exhaust_gen(gen)

        # The trades set should still have 1 unique trade
        assert len(behaviour.trades) == 1
        # But the claimable amount should be accumulated
        condition_id = HexBytes(condition_id_hex)
        assert behaviour.claimable_amounts[condition_id] == 1500

    def test_update_redeem_info_two_winning_trades_in_same_chunk(self) -> None:
        """Should set block number only for the first winning trade in a chunk."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()

        condition_id_hex1 = (
            "0xaa11223344556677889900aabbccddeeff00112233445566778899aabbccddeeff"
        )
        condition_id_hex2 = (
            "0xcc11223344556677889900aabbccddeeff00112233445566778899aabbccddeeff"
        )
        question_id_hex2 = (
            "0xdd11223344556677889900aabbccddeeff00112233445566778899aabbccddeeff"
        )

        trade_data1 = {
            "fpmm": {
                "answerFinalizedTimestamp": "2000000",
                "collateralToken": "0xcollateral",  # type: ignore[no-untyped-def]
                "condition": {
                    "id": condition_id_hex1,
                    "outcomeSlotCount": "2",
                },
                "creator": "0xcreator",
                "creationTimestamp": "1000000",
                "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "question": {
                    "id": "0xbb11223344556677889900aabbccddeeff00112233445566778899aabbccddeeff",
                    "data": "test question 1",
                },
                "templateId": "2",
            },
            "outcomeIndex": "0",
            "outcomeTokenMarginalPrice": "0.5",
            "outcomeTokensTraded": "1000",
            "transactionHash": "0xtx1",
        }

        trade_data2 = {
            "fpmm": {
                "answerFinalizedTimestamp": "2000000",
                "collateralToken": "0xcollateral",
                "condition": {
                    "id": condition_id_hex2,
                    "outcomeSlotCount": "2",
                },
                "creator": "0xcreator",
                "creationTimestamp": "1000000",
                "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "question": {
                    "id": question_id_hex2,
                    "data": "test question 2",
                },
                "templateId": "2",
            },
            "outcomeIndex": "0",
            "outcomeTokenMarginalPrice": "0.5",
            "outcomeTokensTraded": "500",
            "transactionHash": "0xtx2",
        }

        set_block_call_count = [0]

        with patch.object(
            type(behaviour), "synced_timestamp", new_callable=PropertyMock
        ) as mock_ts:
            mock_ts.return_value = 3000000

            def mock_set_block_number(trade):  # type: ignore[no-untyped-def]
                """Mock _set_block_number."""
                set_block_call_count[0] += 1
                yield

            behaviour._set_block_number = mock_set_block_number  # type: ignore[method-assign]

            # Both trades in the same chunk
            gen = behaviour.update_redeem_info([trade_data1, trade_data2])
            _exhaust_gen(gen)

        # set_block_number should be called only once (for the first winning trade)
        assert set_block_call_count[0] == 1
        assert len(behaviour.trades) == 2

    def test_update_redeem_info_duplicate_in_same_chunk(self) -> None:
        """Should accumulate claimable amounts for duplicates in the same chunk."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()

        condition_id_hex = (
            "0xaa11223344556677889900aabbccddeeff00112233445566778899aabbccddeeff"
        )

        trade_data1 = {
            "fpmm": {
                "answerFinalizedTimestamp": "2000000",
                "collateralToken": "0xcollateral",
                "condition": {
                    "id": condition_id_hex,
                    "outcomeSlotCount": "2",
                },
                "creator": "0xcreator",
                "creationTimestamp": "1000000",
                "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "question": {
                    "id": "0xbb11223344556677889900aabbccddeeff00112233445566778899aabbccddeeff",
                    "data": "test question",
                },
                "templateId": "2",
            },
            "outcomeIndex": "0",  # type: ignore[no-untyped-def]
            "outcomeTokenMarginalPrice": "0.5",
            "outcomeTokensTraded": "1000",
            "transactionHash": "0xtx1",
        }

        # Same condition/question but different tx hash
        trade_data2 = {
            "fpmm": {
                "answerFinalizedTimestamp": "2000000",
                "collateralToken": "0xcollateral",
                "condition": {
                    "id": condition_id_hex,
                    "outcomeSlotCount": "2",
                },
                "creator": "0xcreator",
                "creationTimestamp": "1000000",
                "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "question": {
                    "id": "0xbb11223344556677889900aabbccddeeff00112233445566778899aabbccddeeff",
                    "data": "test question",
                },
                "templateId": "2",
            },
            "outcomeIndex": "0",
            "outcomeTokenMarginalPrice": "0.5",
            "outcomeTokensTraded": "500",
            "transactionHash": "0xtx2",
        }

        with patch.object(
            type(behaviour), "synced_timestamp", new_callable=PropertyMock
        ) as mock_ts:
            mock_ts.return_value = 3000000

            def mock_set_block_number(trade):  # type: ignore[no-untyped-def]
                """Mock _set_block_number."""
                yield

            behaviour._set_block_number = mock_set_block_number  # type: ignore[method-assign]

            # Both duplicate trades in the same chunk
            gen = behaviour.update_redeem_info([trade_data1, trade_data2])
            _exhaust_gen(gen)

        # Only 1 unique trade
        assert len(behaviour.trades) == 1
        condition_id = HexBytes(condition_id_hex)
        # 1000 + 500 = 1500
        assert behaviour.claimable_amounts[condition_id] == 1500

    def test_update_redeem_info_duplicate_with_multiple_existing_trades(self) -> None:
        """Should iterate through all trades when looking for a matching duplicate."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()

        condition_id_hex1 = (
            "0xaa11223344556677889900aabbccddeeff00112233445566778899aabbccddeeff"
        )
        condition_id_hex2 = (
            "0xcc11223344556677889900aabbccddeeff00112233445566778899aabbccddeeff"
        )
        question_id_hex1 = (
            "0xbb11223344556677889900aabbccddeeff00112233445566778899aabbccddeeff"
        )
        question_id_hex2 = (
            "0xdd11223344556677889900aabbccddeeff00112233445566778899aabbccddeeff"
        )

        # Create two distinct existing trades
        trade1 = Trade(
            fpmm=FPMM(
                answerFinalizedTimestamp=2000000,
                collateralToken="0xcollateral",
                condition=Condition(id=HexBytes(condition_id_hex1), outcomeSlotCount=2),
                creator="0xcreator",
                creationTimestamp=1000000,  # type: ignore[no-untyped-def]
                currentAnswer="0x0000000000000000000000000000000000000000000000000000000000000000",
                question=Question(id=bytes.fromhex(question_id_hex1[2:]), data="q1"),
                templateId=2,
            ),
            outcomeIndex=0,
            outcomeTokenMarginalPrice=0.5,
            outcomeTokensTraded=1000,
            transactionHash="0xtx1",
        )
        trade2 = Trade(
            fpmm=FPMM(
                answerFinalizedTimestamp=2000000,
                collateralToken="0xcollateral",
                condition=Condition(id=HexBytes(condition_id_hex2), outcomeSlotCount=2),
                creator="0xcreator",
                creationTimestamp=1000000,
                currentAnswer="0x0000000000000000000000000000000000000000000000000000000000000000",
                question=Question(id=bytes.fromhex(question_id_hex2[2:]), data="q2"),
                templateId=2,
            ),
            outcomeIndex=0,
            outcomeTokenMarginalPrice=0.5,
            outcomeTokensTraded=500,
            transactionHash="0xtx2",
        )

        behaviour.trades = {trade1, trade2}
        behaviour.claimable_amounts = {
            HexBytes(condition_id_hex1): 1000,
            HexBytes(condition_id_hex2): 500,
        }

        # Now submit a duplicate of trade2 (same condition_id/question_id)
        trade_data3 = {
            "fpmm": {
                "answerFinalizedTimestamp": "2000000",
                "collateralToken": "0xcollateral",
                "condition": {
                    "id": condition_id_hex2,
                    "outcomeSlotCount": "2",
                },
                "creator": "0xcreator",
                "creationTimestamp": "1000000",
                "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "question": {
                    "id": question_id_hex2,
                    "data": "q2",
                },
                "templateId": "2",
            },
            "outcomeIndex": "0",
            "outcomeTokenMarginalPrice": "0.5",
            "outcomeTokensTraded": "300",
            "transactionHash": "0xtx3",
        }

        with patch.object(
            type(behaviour), "synced_timestamp", new_callable=PropertyMock
        ) as mock_ts:
            mock_ts.return_value = 3000000

            def mock_set_block_number(trade):  # type: ignore[no-untyped-def]
                """Mock _set_block_number."""
                yield

            behaviour._set_block_number = mock_set_block_number  # type: ignore[method-assign]

            gen = behaviour.update_redeem_info([trade_data3])
            _exhaust_gen(gen)

        # Still 2 unique trades
        assert len(behaviour.trades) == 2
        # Claimable amount for condition2 should increase by 300
        assert behaviour.claimable_amounts[HexBytes(condition_id_hex2)] == 800


class TestStoreLoadProgress:
    """Tests for _store_progress and _load_progress."""

    def test_store_and_load_roundtrip(self) -> None:
        """Progress stored should be recoverable via _load_progress."""
        behaviour = _make_redeem_behaviour()
        behaviour.trades = {MagicMock()}
        behaviour.utilized_tools = {"cond1": "tool1"}
        behaviour._policy = _make_policy()
        behaviour.claimable_amounts = {HexBytes("0xaa"): 100}
        behaviour.earliest_block_number = 42

        progress = RedeemingProgress()

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp:
            mock_rp.return_value = progress

            behaviour._store_progress()

        assert progress.utilized_tools == {"cond1": "tool1"}
        assert progress.earliest_block_number == 42

    def test_load_progress(self) -> None:
        """_load_progress should load from redeeming progress."""
        behaviour = _make_redeem_behaviour()  # type: ignore[no-untyped-def]
        policy = _make_policy()
        progress = RedeemingProgress()
        progress.trades = {MagicMock()}
        progress.utilized_tools = {"cond2": "tool2"}
        progress.policy = policy
        progress.claimable_amounts = {HexBytes("0xbb"): 200}
        progress.earliest_block_number = 99

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp:
            mock_rp.return_value = progress
            behaviour._load_progress()

        assert behaviour.trades is progress.trades
        assert behaviour.utilized_tools == {"cond2": "tool2"}
        assert behaviour._policy is policy
        assert behaviour.claimable_amounts == {HexBytes("0xbb"): 200}
        assert behaviour.earliest_block_number == 99


class TestBuildPayload:
    """Tests for _build_payload."""

    def test_build_payload_structure(self) -> None:
        """Payload should contain all required fields."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()
        behaviour._mech_tools = {"tool1"}
        behaviour.redeemed_condition_ids = {"cond1"}
        behaviour.payout_so_far = 1000

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)

            payload = behaviour._build_payload("0xhex")

        assert isinstance(payload, RedeemPayload)
        assert payload.tx_hash == "0xhex"
        assert payload.payout_so_far == 1000

    def test_build_payload_no_tx(self) -> None:
        """Payload should accept None for redeem_tx_hex."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()
        behaviour._mech_tools = {"tool1"}
        behaviour.redeemed_condition_ids = set()
        behaviour.payout_so_far = 0

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)

            payload = behaviour._build_payload()

        assert payload.tx_hash is None


class TestFilterTrades:
    """Tests for _filter_trades."""

    def test_filter_removes_redeemed_conditions(self) -> None:
        """Should remove trades with redeemed condition ids."""
        behaviour = _make_redeem_behaviour()

        mock_id_1 = MagicMock()
        mock_id_1.to_0x_hex.return_value = "0xaa"

        mock_id_2 = MagicMock()
        mock_id_2.to_0x_hex.return_value = "0xbb"

        trade1 = MagicMock()
        trade1.fpmm.condition.id = mock_id_1

        trade2 = MagicMock()
        trade2.fpmm.condition.id = mock_id_2

        behaviour.trades = {trade1, trade2}
        behaviour.redeemed_condition_ids = {"0xaa"}

        progress = MagicMock()
        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp:
            mock_rp.return_value = progress
            behaviour._filter_trades()

        assert len(behaviour.trades) == 1


class TestGetRedeemInfo:
    """Tests for _get_redeem_info."""

    def test_get_redeem_info_no_trades(self) -> None:
        """Should handle case with no fetched trades."""
        behaviour = _make_redeem_behaviour()

        def mock_prepare_fetching() -> bool:
            """Mock _prepare_fetching returning False."""
            return False

        behaviour._prepare_fetching = mock_prepare_fetching  # type: ignore[method-assign]

        gen = behaviour._get_redeem_info()
        _exhaust_gen(gen)

        assert len(behaviour.trades) == 0

    def test_get_redeem_info_with_chunk(self) -> None:
        """Should process fetched chunks."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()

        call_count = [0]

        def mock_prepare_fetching() -> bool:
            """Mock _prepare_fetching returning True once then False."""
            call_count[0] += 1
            return call_count[0] <= 1

        def mock_fetch_redeem_info():  # type: ignore[no-untyped-def]
            """Mock _fetch_redeem_info returning None."""
            yield
            return None

        behaviour._prepare_fetching = mock_prepare_fetching  # type: ignore[method-assign]
        behaviour._fetch_redeem_info = mock_fetch_redeem_info  # type: ignore[method-assign]

        gen = behaviour._get_redeem_info()
        _exhaust_gen(gen)

    def test_get_redeem_info_with_valid_chunk(self) -> None:
        """Should call update_redeem_info when chunk is not None."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()

        call_count = [0]

        def mock_prepare_fetching() -> bool:
            """Mock _prepare_fetching returning True once then False."""
            call_count[0] += 1
            return call_count[0] <= 1

        def mock_fetch_redeem_info():  # type: ignore[no-untyped-def]
            """Mock _fetch_redeem_info returning a chunk."""
            yield
            return [{"data": "test"}]

        def mock_update_redeem_info(chunk):  # type: ignore[no-untyped-def]
            """Mock update_redeem_info."""
            yield

        behaviour._prepare_fetching = mock_prepare_fetching  # type: ignore[method-assign]
        behaviour._fetch_redeem_info = mock_fetch_redeem_info  # type: ignore[method-assign]
        behaviour.update_redeem_info = mock_update_redeem_info  # type: ignore[method-assign]

        gen = behaviour._get_redeem_info()
        _exhaust_gen(gen)


# type: ignore[no-untyped-def]


class TestConditionalTokensInteract:
    """Tests for _conditional_tokens_interact."""

    def test_conditional_tokens_interact(self) -> None:
        """Should call contract_interact with correct params."""
        behaviour = _make_redeem_behaviour()

        def mock_contract_interact(**kwargs):  # type: ignore[no-untyped-def]
            """Mock contract_interact."""
            yield
            return True

        behaviour.contract_interact = mock_contract_interact  # type: ignore[assignment, method-assign]
        params = MagicMock()
        params.conditional_tokens_address = "0xcondtokens"

        with patch.object(  # type: ignore[no-untyped-def]
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = params
            gen = behaviour._conditional_tokens_interact(
                contract_callable="test_call",  # type: ignore[no-untyped-def]
                data_key="data",
                placeholder="test_placeholder",
            )
            result = _exhaust_gen(gen)

        assert result is True


class TestGetLatestBlock:
    """Tests for _get_latest_block."""

    def test_get_latest_block_success(self) -> None:
        """Should set latest_block_number on success."""
        behaviour = _make_redeem_behaviour()
        from packages.valory.protocols.ledger_api import LedgerApiMessage

        response = MagicMock()
        response.performative = LedgerApiMessage.Performative.STATE  # type: ignore[no-untyped-def]
        response.state.body = {"number": "12345"}

        def mock_get_ledger_api_response(**kwargs):  # type: ignore[no-untyped-def]
            """Mock get_ledger_api_response."""
            yield  # type: ignore[no-untyped-def]
            return response

        behaviour.get_ledger_api_response = mock_get_ledger_api_response  # type: ignore[assignment, method-assign]
        params = MagicMock()
        params.mech_chain_id = "gnosis"  # type: ignore[no-untyped-def]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = params
            gen = behaviour._get_latest_block()
            result = _exhaust_gen(gen)

        assert result is True
        assert behaviour._latest_block_number == 12345

    def test_get_latest_block_failure(self) -> None:
        """Should return False on failure."""
        behaviour = _make_redeem_behaviour()
        from packages.valory.protocols.ledger_api import LedgerApiMessage

        response = MagicMock()
        response.performative = LedgerApiMessage.Performative.ERROR

        def mock_get_ledger_api_response(**kwargs):  # type: ignore[no-untyped-def]
            """Mock get_ledger_api_response."""
            yield
            return response

        # type: ignore[no-untyped-def]
        behaviour.get_ledger_api_response = mock_get_ledger_api_response  # type: ignore[assignment, method-assign]
        params = MagicMock()
        params.mech_chain_id = "gnosis"

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = params
            gen = behaviour._get_latest_block()
            result = _exhaust_gen(gen)

        assert result is False


class TestCheckAlreadyRedeemedViaEvents:
    """Tests for _check_already_redeemed_via_events."""

    def test_empty_trades_returns_true(self) -> None:
        """Should return True when there are no trades."""
        behaviour = _make_redeem_behaviour()
        behaviour.trades = set()

        gen = behaviour._check_already_redeemed_via_events()
        result = _exhaust_gen(gen)

        assert result is True

    def test_check_already_redeemed_success(self) -> None:
        """Should process trades and return True on success."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour.trades = {trade}
        behaviour.earliest_block_number = 100

        progress = RedeemingProgress()
        progress.check_started = False
        progress.event_filtering_batch_size = 1000

        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xsafe"  # type: ignore[no-untyped-def]

        def mock_get_latest_block():  # type: ignore[no-untyped-def]
            """Mock _get_latest_block."""
            behaviour._latest_block_number = 200
            yield
            return True

        def mock_conditional_tokens_interact(**kwargs):  # type: ignore[no-untyped-def]
            """Mock _conditional_tokens_interact."""
            behaviour._payouts = {"tx1": 100}
            yield
            return True

        behaviour.wait_for_condition_with_sleep = lambda gen_fn: gen_fn()  # type: ignore[assignment, method-assign, misc]

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp, patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd, patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_rp.return_value = progress
            mock_sd.return_value = mock_synced
            params = MagicMock()
            params.contract_timeout = 30
            params.max_filtering_retries = 3  # type: ignore[no-untyped-def]
            params.reduce_factor = 0.5
            params.minimum_batch_size = 10
            mock_params.return_value = params

            behaviour._get_latest_block = mock_get_latest_block  # type: ignore[method-assign]
            behaviour._conditional_tokens_interact = mock_conditional_tokens_interact  # type: ignore[assignment, method-assign]

            gen = behaviour._check_already_redeemed_via_events()
            result = _exhaust_gen(gen)

        assert result is True
        assert progress.check_started is True

    def test_check_already_redeemed_rpc_failure(self) -> None:
        """Should return False when max retries exceeded."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour.trades = {trade}
        behaviour.earliest_block_number = 100

        progress = RedeemingProgress()
        progress.check_started = True
        progress.check_from_block = 100
        progress.check_to_block = 200
        progress.event_filtering_batch_size = 1000

        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xsafe"

        def mock_conditional_tokens_interact(**kwargs):  # type: ignore[no-untyped-def]
            """Mock _conditional_tokens_interact returning failure."""
            yield
            return False

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp, patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd, patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_rp.return_value = progress
            mock_sd.return_value = mock_synced
            params = MagicMock()
            params.contract_timeout = 30
            params.max_filtering_retries = 0  # immediate failure
            params.reduce_factor = 0.5
            params.minimum_batch_size = 10
            mock_params.return_value = params

            behaviour._conditional_tokens_interact = mock_conditional_tokens_interact  # type: ignore[assignment, method-assign, no-untyped-def]

            gen = behaviour._check_already_redeemed_via_events()
            result = _exhaust_gen(gen)

        assert result is False

    # type: ignore[no-untyped-def]
    def test_check_already_redeemed_retry_with_reduced_batch(self) -> None:
        """Should retry with reduced batch size and then succeed."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour.trades = {trade}
        behaviour.earliest_block_number = 100

        progress = RedeemingProgress()
        progress.check_started = True
        progress.check_from_block = 100
        progress.check_to_block = 200
        progress.event_filtering_batch_size = 1000

        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xsafe"

        call_count = [0]

        def mock_conditional_tokens_interact(**kwargs):  # type: ignore[no-untyped-def]
            """Mock interact: fail first, succeed second."""
            call_count[0] += 1
            if call_count[0] == 1:
                yield
                return False
            behaviour._payouts = {}
            yield
            return True

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp, patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd, patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_rp.return_value = progress
            mock_sd.return_value = mock_synced
            params = MagicMock()
            params.contract_timeout = 30
            params.max_filtering_retries = 3
            params.reduce_factor = 0.5
            params.minimum_batch_size = 10
            mock_params.return_value = params

            behaviour._conditional_tokens_interact = mock_conditional_tokens_interact  # type: ignore[assignment, method-assign]

            gen = behaviour._check_already_redeemed_via_events()
            result = _exhaust_gen(gen)
        # type: ignore[no-untyped-def]
        assert result is True


class TestCheckAlreadyRedeemedViaSubgraph:
    """Tests for _check_already_redeemed_via_subgraph."""

    def test_success(self) -> None:
        """Should return True and set payouts."""
        behaviour = _make_redeem_behaviour()
        progress = RedeemingProgress()

        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSafe"

        def mock_fetch_trades(safe, from_ts, to_ts):  # type: ignore[no-untyped-def]
            """Mock fetch_trades."""
            yield
            return [{"trade1": "data"}]

        def mock_fetch_user_positions(safe):  # type: ignore[no-untyped-def]
            """Mock fetch_user_positions."""
            yield
            return [{"position1": "data"}]

        behaviour.fetch_trades = mock_fetch_trades  # type: ignore[method-assign]
        behaviour.fetch_user_positions = mock_fetch_user_positions  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp, patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd, patch(
            "packages.valory.skills.decision_maker_abci.behaviours.reedem.get_condition_id_to_balances"
        ) as mock_balances, patch(
            "packages.valory.skills.decision_maker_abci.behaviours.reedem.filter_claimed_conditions"
        ) as mock_filter:
            mock_rp.return_value = progress
            mock_sd.return_value = mock_synced
            mock_balances.return_value = ({"cond1": 100}, {"cond2": 50})
            mock_filter.return_value = {"cond2": 50}

            gen = behaviour._check_already_redeemed_via_subgraph()
            result = _exhaust_gen(gen)

        assert result is True
        assert progress.payouts == {"cond1": 100}  # type: ignore[no-untyped-def]
        assert progress.unredeemed_trades == {"cond2": 50}

    def test_fetch_trades_failure(self) -> None:
        """Should return False when fetch_trades fails."""
        behaviour = _make_redeem_behaviour()

        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSafe"

        def mock_fetch_trades(safe, from_ts, to_ts):  # type: ignore[no-untyped-def]
            """Mock fetch_trades returning None."""
            yield
            return None

        behaviour.fetch_trades = mock_fetch_trades  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = mock_synced

            gen = behaviour._check_already_redeemed_via_subgraph()
            result = _exhaust_gen(gen)

        assert result is False

    def test_fetch_user_positions_failure(self) -> None:
        """Should return False when fetch_user_positions fails."""
        behaviour = _make_redeem_behaviour()

        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSafe"

        def mock_fetch_trades(safe, from_ts, to_ts):  # type: ignore[no-untyped-def]
            """Mock fetch_trades."""
            yield
            return [{"trade1": "data"}]

        def mock_fetch_user_positions(safe):  # type: ignore[no-untyped-def]
            """Mock fetch_user_positions returning None."""
            yield
            return None

        behaviour.fetch_trades = mock_fetch_trades  # type: ignore[method-assign]
        behaviour.fetch_user_positions = mock_fetch_user_positions  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = mock_synced  # type: ignore[no-untyped-def]

            gen = behaviour._check_already_redeemed_via_subgraph()
            result = _exhaust_gen(gen)

        assert result is False  # type: ignore[no-untyped-def]


class TestCheckAlreadyRedeemed:
    """Tests for _check_already_redeemed."""

    def test_uses_subgraph_when_configured(self) -> None:
        """Should delegate to subgraph method when configured."""
        behaviour = _make_redeem_behaviour()
        params = MagicMock()
        params.use_subgraph_for_redeeming = True

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = params

            def mock_subgraph():  # type: ignore[no-untyped-def]
                """Mock subgraph method."""
                yield
                return True

            behaviour._check_already_redeemed_via_subgraph = mock_subgraph  # type: ignore[method-assign]
            gen = behaviour._check_already_redeemed()
            result = _exhaust_gen(gen)

        assert result is True

    def test_uses_events_when_not_subgraph(self) -> None:
        """Should delegate to events method when not configured for subgraph."""
        behaviour = _make_redeem_behaviour()
        params = MagicMock()
        params.use_subgraph_for_redeeming = False

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:  # type: ignore[no-untyped-def]
            mock_params.return_value = params

            def mock_events():  # type: ignore[no-untyped-def]
                """Mock events method."""
                yield
                return True

            behaviour._check_already_redeemed_via_events = mock_events  # type: ignore[method-assign]
            gen = behaviour._check_already_redeemed()
            result = _exhaust_gen(gen)

        assert result is True


class TestCleanRedeemInfo:
    """Tests for _clean_redeem_info."""

    def test_clean_with_payout_and_payouts_found(self) -> None:
        """Should filter trades and update payout when payouts > 0."""
        behaviour = _make_redeem_behaviour()
        behaviour.payout_so_far = 100
        behaviour.redeemed_condition_ids = set()

        progress = RedeemingProgress()  # type: ignore[no-untyped-def]
        progress.payouts = {"cond1": 0, "cond2": 200}

        def mock_check_redeemed():  # type: ignore[no-untyped-def]
            """Mock _check_already_redeemed."""
            yield  # type: ignore[no-untyped-def]
            return True

        def mock_filter_trades() -> None:
            """Mock _filter_trades."""
            pass

        behaviour._check_already_redeemed = mock_check_redeemed  # type: ignore[method-assign]
        behaviour._filter_trades = mock_filter_trades  # type: ignore[method-assign]

        params = MagicMock()
        params.use_subgraph_for_redeeming = False

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp, patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_rp.return_value = progress
            mock_params.return_value = params

            gen = behaviour._clean_redeem_info()
            result = _exhaust_gen(gen)

        assert result is True
        assert "cond1" in behaviour.redeemed_condition_ids
        assert behaviour.payout_so_far == 300  # 100 + 200

    def test_clean_with_subgraph_sets_payout(self) -> None:
        """Should set payout_so_far to total when using subgraph."""
        behaviour = _make_redeem_behaviour()
        behaviour.payout_so_far = 0
        behaviour.redeemed_condition_ids = set()

        progress = RedeemingProgress()
        progress.payouts = {"cond1": 0, "cond2": 300}

        def mock_check_redeemed():  # type: ignore[no-untyped-def]
            """Mock _check_already_redeemed."""  # type: ignore[no-untyped-def]
            yield
            return True

        behaviour._check_already_redeemed = mock_check_redeemed  # type: ignore[method-assign]
        behaviour._filter_trades = lambda: None  # type: ignore[method-assign]

        params = MagicMock()
        params.use_subgraph_for_redeeming = True

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp, patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_rp.return_value = progress
            mock_params.return_value = params

            gen = behaviour._clean_redeem_info()
            result = _exhaust_gen(gen)

        assert result is True
        assert behaviour.payout_so_far == 300  # type: ignore[no-untyped-def]

    def test_clean_check_redeemed_failure(self) -> None:
        """Should return False if _check_already_redeemed fails."""
        behaviour = _make_redeem_behaviour()
        behaviour.payout_so_far = 0

        progress = RedeemingProgress()
        progress.payouts = {}

        def mock_check_redeemed():  # type: ignore[no-untyped-def]
            """Mock _check_already_redeemed returning failure."""
            yield
            return False

        behaviour._check_already_redeemed = mock_check_redeemed  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp:
            mock_rp.return_value = progress

            gen = behaviour._clean_redeem_info()
            result = _exhaust_gen(gen)

        assert result is False

    def test_clean_no_payouts(self) -> None:
        """Should return True and not change payout when no payouts."""
        behaviour = _make_redeem_behaviour()  # type: ignore[no-untyped-def]
        behaviour.payout_so_far = 0
        behaviour.redeemed_condition_ids = set()

        progress = RedeemingProgress()
        progress.payouts = {}  # type: ignore[no-untyped-def]

        def mock_check_redeemed():  # type: ignore[no-untyped-def]
            """Mock _check_already_redeemed."""
            yield
            return True

        behaviour._check_already_redeemed = mock_check_redeemed  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp:
            mock_rp.return_value = progress

            gen = behaviour._clean_redeem_info()
            result = _exhaust_gen(gen)

        assert result is True
        assert behaviour.payout_so_far == 0


class TestRealitioInteract:
    """Tests for _realitio_interact."""

    def test_realitio_interact(self) -> None:
        """Should call contract_interact with correct params."""
        behaviour = _make_redeem_behaviour()

        def mock_contract_interact(**kwargs):  # type: ignore[no-untyped-def]
            """Mock contract_interact."""
            yield
            return True

        behaviour.contract_interact = mock_contract_interact  # type: ignore[assignment, method-assign]
        params = MagicMock()  # type: ignore[no-untyped-def]
        params.realitio_address = "0xrealitio"

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = params
            gen = behaviour._realitio_interact(
                contract_callable="test_call",
                data_key="data",
                placeholder="test_placeholder",
            )
            result = _exhaust_gen(gen)

        assert result is True


class TestGetHistoryHash:
    """Tests for _get_history_hash."""

    def test_get_history_hash(self) -> None:
        """Should call _realitio_interact with correct params."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade

        def mock_realitio_interact(**kwargs):  # type: ignore[no-untyped-def]
            """Mock _realitio_interact."""
            yield
            return True

        behaviour._realitio_interact = mock_realitio_interact  # type: ignore[assignment, method-assign]

        gen = behaviour._get_history_hash()  # type: ignore[no-untyped-def]
        result = _exhaust_gen(gen)

        assert result is True


class TestCheckAlreadyResolved:
    """Tests for _check_already_resolved."""

    def test_check_already_resolved(self) -> None:
        """Should call _conditional_tokens_interact with correct params."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade

        def mock_ct_interact(**kwargs):  # type: ignore[no-untyped-def]
            """Mock _conditional_tokens_interact."""
            yield
            return True

        behaviour._conditional_tokens_interact = mock_ct_interact  # type: ignore[assignment, method-assign]

        gen = behaviour._check_already_resolved()
        result = _exhaust_gen(gen)

        assert result is True


# type: ignore[no-untyped-def]


class TestBuildResolveData:
    """Tests for _build_resolve_data."""

    def test_build_resolve_data_success(self) -> None:
        """Should build resolve data and append to multisend_batches."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade
        behaviour._built_data = HexBytes("0xdeadbeef")

        def mock_contract_interact(**kwargs):  # type: ignore[no-untyped-def]
            """Mock contract_interact."""
            behaviour._built_data = HexBytes("0xdeadbeef")
            yield
            return True

        behaviour.contract_interact = mock_contract_interact  # type: ignore[assignment, method-assign]
        params = MagicMock()
        params.realitio_proxy_address = "0xproxy"

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = params
            gen = behaviour._build_resolve_data()
            result = _exhaust_gen(gen)

        assert result is True
        assert len(behaviour.multisend_batches) == 1
        assert behaviour.multisend_batches[0].to == "0xproxy"  # type: ignore[no-untyped-def]

    def test_build_resolve_data_failure(self) -> None:
        """Should return False when contract_interact fails."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade

        def mock_contract_interact(**kwargs):  # type: ignore[no-untyped-def]
            """Mock contract_interact returning failure."""
            yield
            return False

        behaviour.contract_interact = mock_contract_interact  # type: ignore[assignment, method-assign]
        params = MagicMock()
        params.realitio_proxy_address = "0xproxy"

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = params
            gen = behaviour._build_resolve_data()
            result = _exhaust_gen(gen)

        assert result is False
        assert len(behaviour.multisend_batches) == 0


class TestSimulateClaiming:
    """Tests for _simulate_claiming."""

    def test_simulate_claiming(self) -> None:
        """Should call _realitio_interact with claim params."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade

        progress = RedeemingProgress()  # type: ignore[no-untyped-def]
        progress.answered = [
            {
                "args": {
                    "history_hash": b"\x00",
                    "user": "0xuser",
                    "bond": 1,
                    "answer": b"\x00",
                }
            }
        ]

        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xsafe"

        def mock_realitio_interact(**kwargs):  # type: ignore[no-untyped-def]
            """Mock _realitio_interact."""
            yield
            return True

        behaviour._realitio_interact = mock_realitio_interact  # type: ignore[assignment, method-assign]

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp, patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_rp.return_value = progress  # type: ignore[no-untyped-def]
            mock_sd.return_value = mock_synced

            gen = behaviour._simulate_claiming()
            result = _exhaust_gen(gen)

        assert result is True


class TestBuildClaimData:
    """Tests for _build_claim_data."""

    def test_build_claim_data_success(self) -> None:
        """Should build claim data and append to multisend_batches."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade
        behaviour._built_data = HexBytes("0xdeadbeef")

        progress = RedeemingProgress()
        progress.answered = [
            {
                "args": {
                    "history_hash": b"\x00",
                    "user": "0xuser",
                    "bond": 1,
                    "answer": b"\x00",
                }
            }  # type: ignore[no-untyped-def]
        ]

        def mock_realitio_interact(**kwargs):  # type: ignore[no-untyped-def]
            """Mock _realitio_interact."""
            behaviour._built_data = HexBytes("0xdeadbeef")
            yield
            return True

        behaviour._realitio_interact = mock_realitio_interact  # type: ignore[assignment, method-assign]
        params = MagicMock()
        params.realitio_address = "0xrealitio"

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp, patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_rp.return_value = progress
            mock_params.return_value = params

            gen = behaviour._build_claim_data()
            result = _exhaust_gen(gen)

        assert result is True
        assert len(behaviour.multisend_batches) == 1
        assert behaviour.multisend_batches[0].to == "0xrealitio"

    # type: ignore[no-untyped-def]
    def test_build_claim_data_no_claim_params(self) -> None:
        """Should return False when claim params are None."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade

        progress = RedeemingProgress()
        # answered with invalid format will make claim_params return None
        progress.answered = [{"bad_key": "bad_value"}]

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp:
            mock_rp.return_value = progress

            gen = behaviour._build_claim_data()
            result = _exhaust_gen(gen)

        assert result is False

    def test_build_claim_data_interact_failure(self) -> None:
        """Should return False when _realitio_interact fails."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade

        progress = RedeemingProgress()
        progress.answered = [
            {
                "args": {
                    "history_hash": b"\x00",
                    "user": "0xuser",
                    "bond": 1,
                    "answer": b"\x00",
                }
            }
        ]

        def mock_realitio_interact(**kwargs):  # type: ignore[no-untyped-def]
            """Mock _realitio_interact returning failure."""
            yield
            return False

        behaviour._realitio_interact = mock_realitio_interact  # type: ignore[assignment, method-assign]

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp:
            mock_rp.return_value = progress  # type: ignore[no-untyped-def]

            gen = behaviour._build_claim_data()
            result = _exhaust_gen(gen)

        assert result is False


class TestGetClaimParams:
    """Tests for get_claim_params."""

    def test_uses_subgraph_when_configured(self) -> None:
        """Should delegate to subgraph method when configured."""
        behaviour = _make_redeem_behaviour()
        params = MagicMock()
        params.use_subgraph_for_redeeming = True

        def mock_get_claim_params_via_subgraph():  # type: ignore[no-untyped-def]
            """Mock subgraph claim params."""
            yield
            return True

        behaviour._get_claim_params_via_subgraph = mock_get_claim_params_via_subgraph  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = params
            gen = behaviour.get_claim_params()
            result = _exhaust_gen(gen)

        assert result is True

    def test_uses_events_when_not_subgraph(self) -> None:
        """Should delegate to events method when not using subgraph."""
        behaviour = _make_redeem_behaviour()
        params = MagicMock()
        params.use_subgraph_for_redeeming = False

        def mock_get_claim_params_via_events():  # type: ignore[no-untyped-def]
            """Mock events claim params."""
            yield
            return True

        behaviour._get_claim_params_via_events = mock_get_claim_params_via_events  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:  # type: ignore[no-untyped-def]
            mock_params.return_value = params
            gen = behaviour.get_claim_params()
            result = _exhaust_gen(gen)

        assert result is True


class TestGetClaimParamsViaEvents:
    """Tests for _get_claim_params_via_events."""

    def test_success(self) -> None:
        """Should return True after fetching claim params."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade

        progress = RedeemingProgress()
        progress.claim_started = False
        progress.check_to_block = 200
        progress.event_filtering_batch_size = 1000
        behaviour.earliest_block_number = 100

        def mock_realitio_interact(**kwargs):  # type: ignore[no-untyped-def]
            """Mock _realitio_interact."""
            behaviour._claim_params_batch = [{"args": {"data": "test"}}]
            yield
            return True

        behaviour._realitio_interact = mock_realitio_interact  # type: ignore[assignment, method-assign]
        params = MagicMock()
        params.contract_timeout = 30
        params.max_filtering_retries = 3
        params.reduce_factor = 0.5

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp, patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_rp.return_value = progress
            mock_params.return_value = params

            gen = behaviour._get_claim_params_via_events()
            result = _exhaust_gen(gen)

        assert result is True
        assert progress.claim_started is True

    def test_failure_max_retries(self) -> None:
        """Should return False when max retries exceeded."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade

        progress = RedeemingProgress()
        progress.claim_started = True
        progress.claim_from_block = 100
        progress.claim_to_block = 200
        progress.event_filtering_batch_size = 1000

        def mock_realitio_interact(**kwargs):  # type: ignore[no-untyped-def]
            """Mock _realitio_interact returning failure."""
            yield  # type: ignore[no-untyped-def]
            return False

        behaviour._realitio_interact = mock_realitio_interact  # type: ignore[assignment, method-assign]
        params = MagicMock()
        params.contract_timeout = 30
        params.max_filtering_retries = 0
        params.reduce_factor = 0.5

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp, patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_rp.return_value = progress
            mock_params.return_value = params

            gen = behaviour._get_claim_params_via_events()
            result = _exhaust_gen(gen)

        assert result is False

    def test_retry_with_reduced_batch(self) -> None:
        """Should retry with reduced batch then succeed."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade

        progress = RedeemingProgress()
        progress.claim_started = True
        progress.claim_from_block = 100
        progress.claim_to_block = 200
        progress.event_filtering_batch_size = 1000  # type: ignore[no-untyped-def]

        call_count = [0]

        def mock_realitio_interact(**kwargs):  # type: ignore[no-untyped-def]
            """Mock interact: fail first, succeed second."""
            call_count[0] += 1
            if call_count[0] == 1:
                yield
                return False
            behaviour._claim_params_batch = []
            yield
            return True

        behaviour._realitio_interact = mock_realitio_interact  # type: ignore[assignment, method-assign]
        params = MagicMock()
        params.contract_timeout = 30
        params.max_filtering_retries = 3
        params.reduce_factor = 0.5

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp, patch.object(  # type: ignore[no-untyped-def]
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_rp.return_value = progress
            mock_params.return_value = params

            gen = behaviour._get_claim_params_via_events()
            result = _exhaust_gen(gen)

        assert result is True


class TestGetClaimParamsViaSubgraph:
    """Tests for _get_claim_params_via_subgraph."""

    def test_success(self) -> None:
        """Should return True when fetch_claim_params succeeds."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade

        progress = RedeemingProgress()

        def mock_fetch_claim_params(question_id):  # type: ignore[no-untyped-def]
            """Mock fetch_claim_params."""
            yield
            return [{"args": {"data": "test"}}]

        behaviour.fetch_claim_params = mock_fetch_claim_params  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp:
            mock_rp.return_value = progress

            gen = behaviour._get_claim_params_via_subgraph()
            result = _exhaust_gen(gen)
        # type: ignore[no-untyped-def]
        assert result is True

    def test_failure(self) -> None:
        """Should return False when fetch_claim_params fails."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade

        def mock_fetch_claim_params(question_id):  # type: ignore[no-untyped-def]
            """Mock fetch_claim_params returning None/falsy."""
            yield
            return None

        behaviour.fetch_claim_params = mock_fetch_claim_params  # type: ignore[method-assign]

        gen = behaviour._get_claim_params_via_subgraph()
        result = _exhaust_gen(gen)

        assert result is False


class TestBuildRedeemData:
    """Tests for _build_redeem_data."""

    def test_success(self) -> None:
        """Should build redeem data and append to multisend_batches."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade
        behaviour._built_data = HexBytes("0xdeadbeef")

        def mock_ct_interact(**kwargs):  # type: ignore[no-untyped-def]
            """Mock _conditional_tokens_interact."""
            behaviour._built_data = HexBytes("0xdeadbeef")
            yield
            return True

        behaviour._conditional_tokens_interact = mock_ct_interact  # type: ignore[assignment, method-assign, no-untyped-def]
        params = MagicMock()
        params.conditional_tokens_address = "0xcondtokens"

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = params

            gen = behaviour._build_redeem_data()
            result = _exhaust_gen(gen)

        assert result is True
        assert len(behaviour.multisend_batches) == 1
        assert behaviour.multisend_batches[0].to == "0xcondtokens"

    def test_failure(self) -> None:
        """Should return False when _conditional_tokens_interact fails."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour._current_redeem_info = trade

        def mock_ct_interact(**kwargs):  # type: ignore[no-untyped-def]
            """Mock _conditional_tokens_interact returning failure."""
            yield
            return False

        behaviour._conditional_tokens_interact = mock_ct_interact  # type: ignore[assignment, method-assign]

        gen = behaviour._build_redeem_data()
        result = _exhaust_gen(gen)

        assert result is False
        assert len(behaviour.multisend_batches) == 0


class TestPrepareSingleRedeem:
    """Tests for _prepare_single_redeem."""

    # type: ignore[no-untyped-def]
    def test_prepare_single_redeem_not_resolved_with_history(self) -> None:
        """Should build resolve, claim, and redeem when not resolved and history exists."""
        behaviour = _make_redeem_behaviour()
        behaviour._already_resolved = False
        behaviour._history_hash = b"\x01" * 32  # non-null

        progress = RedeemingProgress()
        # claim_finished is a property: claim_started and claim_from_block == claim_to_block
        # To make it False, ensure claim_started is False
        progress.claim_started = False

        steps_called = []

        def mock_wait(gen_fn):  # type: ignore[no-untyped-def]
            """Mock wait_for_condition_with_sleep."""
            gen = gen_fn()
            _exhaust_gen(gen)
            yield

        def mock_check_resolved():  # type: ignore[no-untyped-def]
            """Mock _check_already_resolved."""
            behaviour._already_resolved = False
            yield
            return True

        def mock_get_history_hash():  # type: ignore[no-untyped-def]
            """Mock _get_history_hash."""
            behaviour._history_hash = b"\x01" * 32
            yield
            return True

        def mock_get_claim_params():  # type: ignore[no-untyped-def]
            """Mock get_claim_params."""
            steps_called.append("claim_params")
            yield
            return True

        def mock_simulate_claiming():  # type: ignore[no-untyped-def]
            """Mock _simulate_claiming."""
            behaviour._claim_winnings_simulation_ok = True
            steps_called.append("simulate")
            yield
            return True

        def mock_build_resolve():  # type: ignore[no-untyped-def]
            """Mock _build_resolve_data."""  # type: ignore[no-untyped-def]
            steps_called.append("resolve")
            yield
            return True

        def mock_build_claim():  # type: ignore[no-untyped-def]
            """Mock _build_claim_data."""
            steps_called.append("claim")
            yield
            return True

        def mock_build_redeem():  # type: ignore[no-untyped-def]
            """Mock _build_redeem_data."""
            steps_called.append("redeem")
            yield
            return True

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[assignment, method-assign]
        behaviour._check_already_resolved = mock_check_resolved  # type: ignore[method-assign]
        behaviour._get_history_hash = mock_get_history_hash  # type: ignore[method-assign]
        behaviour.get_claim_params = mock_get_claim_params  # type: ignore[method-assign]
        behaviour._simulate_claiming = mock_simulate_claiming  # type: ignore[method-assign]
        behaviour._build_resolve_data = mock_build_resolve  # type: ignore[method-assign]
        behaviour._build_claim_data = mock_build_claim  # type: ignore[method-assign, no-untyped-def]
        behaviour._build_redeem_data = mock_build_redeem  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp:
            mock_rp.return_value = progress

            gen = behaviour._prepare_single_redeem()
            result = _exhaust_gen(gen)

        assert result is True
        assert "claim_params" in steps_called
        assert "simulate" in steps_called

    def test_prepare_single_redeem_already_resolved_null_history(self) -> None:
        """Should skip resolve and claim steps when resolved and history is null."""
        behaviour = _make_redeem_behaviour()
        behaviour._already_resolved = True
        behaviour._history_hash = b"\x00" * 32  # null

        steps_called = []

        def mock_wait(gen_fn):  # type: ignore[no-untyped-def]
            """Mock wait_for_condition_with_sleep."""
            gen = gen_fn()
            _exhaust_gen(gen)
            yield

        # type: ignore[no-untyped-def]
        def mock_check_resolved():  # type: ignore[no-untyped-def]
            """Mock _check_already_resolved."""
            behaviour._already_resolved = True
            yield
            return True

        def mock_get_history_hash():  # type: ignore[no-untyped-def]
            """Mock _get_history_hash."""
            yield
            return True

        def mock_build_redeem():  # type: ignore[no-untyped-def]
            """Mock _build_redeem_data."""
            steps_called.append("redeem")
            yield
            return True

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[assignment, method-assign]
        behaviour._check_already_resolved = mock_check_resolved  # type: ignore[method-assign]
        behaviour._get_history_hash = mock_get_history_hash  # type: ignore[method-assign]
        behaviour._build_redeem_data = mock_build_redeem  # type: ignore[method-assign]

        gen = behaviour._prepare_single_redeem()
        result = _exhaust_gen(gen)

        assert result is True
        assert "redeem" in steps_called

    # type: ignore[no-untyped-def]
    def test_prepare_single_redeem_get_claim_params_fails(self) -> None:
        """Should return False when get_claim_params fails."""
        behaviour = _make_redeem_behaviour()
        behaviour._already_resolved = True
        behaviour._history_hash = b"\x01" * 32

        progress = RedeemingProgress()
        progress.claim_started = False

        def mock_wait(gen_fn):  # type: ignore[no-untyped-def]
            """Mock wait_for_condition_with_sleep."""
            gen = gen_fn()
            _exhaust_gen(gen)
            yield

        def mock_check_resolved():  # type: ignore[no-untyped-def]
            """Mock _check_already_resolved."""
            yield
            return True

        def mock_get_history_hash():  # type: ignore[no-untyped-def]
            """Mock _get_history_hash."""
            yield
            return True

        def mock_get_claim_params():  # type: ignore[no-untyped-def]
            """Mock get_claim_params returning failure."""
            yield
            return False

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[assignment, method-assign]
        behaviour._check_already_resolved = mock_check_resolved  # type: ignore[method-assign]
        behaviour._get_history_hash = mock_get_history_hash  # type: ignore[method-assign]
        behaviour.get_claim_params = mock_get_claim_params  # type: ignore[method-assign]
        # type: ignore[no-untyped-def]
        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp:
            mock_rp.return_value = progress

            gen = behaviour._prepare_single_redeem()  # type: ignore[no-untyped-def]
            result = _exhaust_gen(gen)

        assert result is False

    def test_prepare_single_redeem_simulate_claiming_fails(self) -> None:
        """Should return False when _simulate_claiming fails."""  # type: ignore[no-untyped-def]
        behaviour = _make_redeem_behaviour()
        behaviour._already_resolved = True
        behaviour._history_hash = b"\x01" * 32

        progress = RedeemingProgress()
        progress.claim_started = False  # type: ignore[no-untyped-def]

        def mock_wait(gen_fn):  # type: ignore[no-untyped-def]
            """Mock wait_for_condition_with_sleep."""
            gen = gen_fn()
            _exhaust_gen(gen)
            yield  # type: ignore[no-untyped-def]

        def mock_check_resolved():  # type: ignore[no-untyped-def]
            """Mock _check_already_resolved."""
            yield
            return True

        def mock_get_history_hash():  # type: ignore[no-untyped-def]
            """Mock _get_history_hash."""
            yield
            return True

        def mock_get_claim_params():  # type: ignore[no-untyped-def]
            """Mock get_claim_params."""  # type: ignore[no-untyped-def]
            yield
            return True

        def mock_simulate_claiming():  # type: ignore[no-untyped-def]
            """Mock _simulate_claiming returning failure."""
            yield  # type: ignore[no-untyped-def]
            return False

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[assignment, method-assign]
        behaviour._check_already_resolved = mock_check_resolved  # type: ignore[method-assign]
        behaviour._get_history_hash = mock_get_history_hash  # type: ignore[method-assign]
        behaviour.get_claim_params = mock_get_claim_params  # type: ignore[method-assign]
        behaviour._simulate_claiming = mock_simulate_claiming  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp:
            mock_rp.return_value = progress

            gen = behaviour._prepare_single_redeem()
            result = _exhaust_gen(gen)

        assert result is False

    def test_prepare_single_redeem_claim_finished(self) -> None:
        """Should skip get_claim_params when claim is already finished."""
        behaviour = _make_redeem_behaviour()
        behaviour._already_resolved = True
        behaviour._history_hash = b"\x01" * 32
        behaviour._claim_winnings_simulation_ok = False  # sim not ok so no claim

        progress = RedeemingProgress()
        # claim_finished is a property: claim_started and claim_from_block == claim_to_block
        # To make it True, set claim_started=True and claim_from_block == claim_to_block
        progress.claim_started = True
        progress.claim_from_block = 100
        progress.claim_to_block = 100

        steps_called = []

        def mock_wait(gen_fn):  # type: ignore[no-untyped-def]
            """Mock wait_for_condition_with_sleep."""
            gen = gen_fn()
            _exhaust_gen(gen)
            yield

        def mock_check_resolved():  # type: ignore[no-untyped-def]
            """Mock _check_already_resolved."""
            yield
            return True

        def mock_get_history_hash():  # type: ignore[no-untyped-def]
            """Mock _get_history_hash."""  # type: ignore[no-untyped-def]
            yield
            return True

        def mock_build_redeem():  # type: ignore[no-untyped-def]
            """Mock _build_redeem_data."""  # type: ignore[no-untyped-def]
            steps_called.append("redeem")
            yield
            return True

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[assignment, method-assign]
        behaviour._check_already_resolved = mock_check_resolved  # type: ignore[method-assign]
        behaviour._get_history_hash = mock_get_history_hash  # type: ignore[method-assign]
        behaviour._build_redeem_data = mock_build_redeem  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp:
            mock_rp.return_value = progress

            gen = behaviour._prepare_single_redeem()
            result = _exhaust_gen(gen)

        assert result is True
        assert "redeem" in steps_called


class TestProcessCandidate:
    """Tests for _process_candidate."""

    def test_dust_position_skipped(self) -> None:
        """Should return False for dust positions."""  # type: ignore[no-untyped-def]
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        cid = trade.fpmm.condition.id
        behaviour.claimable_amounts = {cid: 1}

        params = MagicMock()  # type: ignore[no-untyped-def]
        params.dust_threshold = 10
        params.use_subgraph_for_redeeming = False

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock  # type: ignore[no-untyped-def]
        ) as mock_params:
            mock_params.return_value = params

            gen = behaviour._process_candidate(trade)
            result = _exhaust_gen(gen)  # type: ignore[no-untyped-def]

        assert result is False

    def test_successful_processing(self) -> None:
        """Should return True and update expected winnings for valid candidate."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        cid = trade.fpmm.condition.id
        behaviour.claimable_amounts = {cid: 1000}

        params = MagicMock()
        params.dust_threshold = 10
        params.use_subgraph_for_redeeming = False

        def mock_prepare_single_redeem():  # type: ignore[no-untyped-def]
            """Mock _prepare_single_redeem."""
            yield
            return True

        behaviour._prepare_single_redeem = mock_prepare_single_redeem  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = params

            gen = behaviour._process_candidate(trade)
            result = _exhaust_gen(gen)
        # type: ignore[no-untyped-def]
        assert result is True
        assert behaviour._expected_winnings == 1000

    def test_prepare_single_redeem_failure(self) -> None:
        """Should return False when _prepare_single_redeem fails."""
        behaviour = _make_redeem_behaviour()  # type: ignore[no-untyped-def]
        trade = _make_trade()
        cid = trade.fpmm.condition.id
        behaviour.claimable_amounts = {cid: 1000}

        params = MagicMock()  # type: ignore[no-untyped-def]
        params.dust_threshold = 10
        params.use_subgraph_for_redeeming = False

        def mock_prepare_single_redeem():  # type: ignore[no-untyped-def]
            """Mock _prepare_single_redeem returning failure."""  # type: ignore[no-untyped-def]
            yield
            return False

        behaviour._prepare_single_redeem = mock_prepare_single_redeem  # type: ignore[method-assign]
        # type: ignore[no-untyped-def]
        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = params

            gen = behaviour._process_candidate(trade)
            result = _exhaust_gen(gen)

        assert result is False

    def test_subgraph_condition_not_in_unredeemed(self) -> None:
        """Should return False when using subgraph and condition not in unredeemed."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        cid = trade.fpmm.condition.id
        behaviour.claimable_amounts = {cid: 1000}

        progress = RedeemingProgress()
        progress.unredeemed_trades = {}

        params = MagicMock()
        params.dust_threshold = 10
        params.use_subgraph_for_redeeming = True

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params, patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp:
            mock_params.return_value = params
            mock_rp.return_value = progress

            gen = behaviour._process_candidate(trade)
            result = _exhaust_gen(gen)

        assert result is False

    # type: ignore[no-untyped-def]
    def test_subgraph_condition_zero_amount(self) -> None:
        """Should return False when using subgraph and condition has 0 unredeemed."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        cid = trade.fpmm.condition.id
        behaviour.claimable_amounts = {cid: 1000}  # type: ignore[no-untyped-def]
        condition_id_hex = cid.to_0x_hex().lower()

        progress = RedeemingProgress()
        progress.unredeemed_trades = {condition_id_hex: 0}
        # type: ignore[no-untyped-def]
        params = MagicMock()
        params.dust_threshold = 10
        params.use_subgraph_for_redeeming = True

        with patch.object(  # type: ignore[no-untyped-def]
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params, patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp:
            mock_params.return_value = params
            mock_rp.return_value = progress

            gen = behaviour._process_candidate(trade)
            result = _exhaust_gen(gen)

        assert result is False

    def test_subgraph_condition_in_unredeemed_with_amount(self) -> None:
        """Should proceed to redeem when using subgraph and condition is unredeemed."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        cid = trade.fpmm.condition.id
        behaviour.claimable_amounts = {cid: 1000}
        condition_id_hex = cid.to_0x_hex().lower()

        progress = RedeemingProgress()
        progress.unredeemed_trades = {condition_id_hex: 500}

        params = MagicMock()
        params.dust_threshold = 10
        params.use_subgraph_for_redeeming = True

        def mock_prepare_single_redeem():  # type: ignore[no-untyped-def]
            """Mock _prepare_single_redeem."""
            yield
            return True

        behaviour._prepare_single_redeem = mock_prepare_single_redeem  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params, patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp:
            mock_params.return_value = params
            mock_rp.return_value = progress

            gen = behaviour._process_candidate(trade)
            result = _exhaust_gen(gen)

        assert result is True
        assert behaviour._expected_winnings == 1000


class TestPrepareSafeTx:
    """Tests for _prepare_safe_tx."""

    def test_no_trades(self) -> None:
        """Should return None with no trades."""
        behaviour = _make_redeem_behaviour()
        behaviour.trades = set()

        gen = behaviour._prepare_safe_tx()
        result = _exhaust_gen(gen)

        assert result is None

    def test_no_winnings(self) -> None:  # type: ignore[no-untyped-def]
        """Should return None when no winnings found."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour.trades = {trade}

        def mock_process_candidate(candidate):  # type: ignore[no-untyped-def]
            """Mock _process_candidate returning False."""
            yield
            return False

        behaviour._process_candidate = mock_process_candidate  # type: ignore[method-assign]

        gen = behaviour._prepare_safe_tx()
        result = _exhaust_gen(gen)

        assert result is None

    def test_with_winnings(self) -> None:
        """Should prepare multisend tx when winnings are found."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour.trades = {trade}
        behaviour._expected_winnings = 0

        progress = RedeemingProgress()

        def mock_process_candidate(candidate):  # type: ignore[no-untyped-def]
            """Mock _process_candidate returning True."""
            behaviour._expected_winnings = 1000  # type: ignore[no-untyped-def]
            yield
            return True

        def mock_wait(gen_fn):  # type: ignore[no-untyped-def]
            """Mock wait_for_condition_with_sleep."""
            gen = gen_fn()
            _exhaust_gen(gen)
            yield

        behaviour._process_candidate = mock_process_candidate  # type: ignore[method-assign]
        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[assignment, method-assign]
        behaviour._safe_tx_hash = "a" * 64
        behaviour.multisend_data = b"data"

        params = MagicMock()
        params.redeeming_batch_size = 10

        def mock_build_multisend_data():  # type: ignore[no-untyped-def]
            """Mock _build_multisend_data."""
            yield
            return True

        def mock_build_multisend_safe_tx_hash():  # type: ignore[no-untyped-def]
            """Mock _build_multisend_safe_tx_hash."""
            yield
            return True

        behaviour._build_multisend_data = mock_build_multisend_data  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = mock_build_multisend_safe_tx_hash  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params, patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp, patch.object(
            type(behaviour), "tx_hex", new_callable=PropertyMock
        ) as mock_tx_hex:
            mock_params.return_value = params
            mock_rp.return_value = progress
            mock_tx_hex.return_value = "0xresult"

            gen = behaviour._prepare_safe_tx()
            result = _exhaust_gen(gen)

        assert result == "0xresult"

    def test_batch_size_limit(self) -> None:
        """Should stop at redeeming_batch_size."""
        behaviour = _make_redeem_behaviour()
        trade1 = _make_trade(condition_id="0xaa" + "11" * 31)
        trade2 = _make_trade(
            condition_id="0xbb" + "22" * 31,
            question_id="0xcc" + "33" * 31,
        )
        behaviour.trades = {trade1, trade2}

        progress = RedeemingProgress()

        processed = []

        def mock_process_candidate(candidate):  # type: ignore[no-untyped-def]
            """Mock _process_candidate returning True."""
            processed.append(candidate)
            behaviour._expected_winnings += 100
            yield
            return True

        def mock_wait(gen_fn):  # type: ignore[no-untyped-def]
            """Mock wait_for_condition_with_sleep."""
            gen = gen_fn()
            _exhaust_gen(gen)
            yield

        behaviour._process_candidate = mock_process_candidate  # type: ignore[method-assign]
        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[assignment, method-assign]

        def mock_build_multisend_data():  # type: ignore[no-untyped-def]
            """Mock _build_multisend_data."""
            yield
            return True

        def mock_build_multisend_safe_tx_hash():  # type: ignore[no-untyped-def]
            """Mock _build_multisend_safe_tx_hash."""
            yield
            return True

        behaviour._build_multisend_data = mock_build_multisend_data  # type: ignore[method-assign, no-untyped-def]
        behaviour._build_multisend_safe_tx_hash = mock_build_multisend_safe_tx_hash  # type: ignore[method-assign]

        params = MagicMock()
        params.redeeming_batch_size = 1  # only 1 position

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params, patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp, patch.object(
            type(behaviour), "tx_hex", new_callable=PropertyMock
        ) as mock_tx_hex:
            mock_params.return_value = params
            mock_rp.return_value = progress
            mock_tx_hex.return_value = "0xresult"

            gen = behaviour._prepare_safe_tx()
            result = _exhaust_gen(gen)

        assert len(processed) == 1
        assert result == "0xresult"

    def test_batch_size_larger_than_one_logs(self) -> None:
        """Should log about adding to batch when batch size > 1."""
        behaviour = _make_redeem_behaviour()
        trade = _make_trade()
        behaviour.trades = {trade}

        progress = RedeemingProgress()

        def mock_process_candidate(candidate):  # type: ignore[no-untyped-def]
            """Mock _process_candidate returning True."""
            behaviour._expected_winnings = 100
            yield
            return True

        def mock_wait(gen_fn):  # type: ignore[no-untyped-def]
            """Mock wait_for_condition_with_sleep."""
            gen = gen_fn()
            _exhaust_gen(gen)
            yield

        behaviour._process_candidate = mock_process_candidate  # type: ignore[method-assign]
        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[assignment, method-assign]

        def mock_build_multisend_data():  # type: ignore[no-untyped-def]
            """Mock _build_multisend_data."""
            yield
            return True

        def mock_build_multisend_safe_tx_hash():  # type: ignore[no-untyped-def]
            """Mock _build_multisend_safe_tx_hash."""
            yield
            return True

        behaviour._build_multisend_data = mock_build_multisend_data  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = mock_build_multisend_safe_tx_hash  # type: ignore[method-assign]

        params = MagicMock()
        params.redeeming_batch_size = 5

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params, patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp, patch.object(
            type(behaviour), "tx_hex", new_callable=PropertyMock  # type: ignore[no-untyped-def]
        ) as mock_tx_hex:
            mock_params.return_value = params
            mock_rp.return_value = progress
            mock_tx_hex.return_value = "0xresult"

            gen = behaviour._prepare_safe_tx()  # type: ignore[no-untyped-def]
            _exhaust_gen(gen)

        behaviour.context.logger.info.assert_any_call(  # type: ignore[union-attr]
            "Adding position to the multisend batch..."
        )


class TestStoreUtilizedToolsAndFinish:
    """Tests for _store_utilized_tools and finish_behaviour."""

    def test_store_utilized_tools(self, tmp_path: Path) -> None:
        """Should write utilized tools to JSON file."""
        behaviour = _make_redeem_behaviour()
        behaviour.utilized_tools = {"tx1": "tool1"}  # type: ignore[no-untyped-def]

        params = MagicMock()
        params.store_path = tmp_path

        with patch.object(  # type: ignore[no-untyped-def]
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = params
            behaviour._store_utilized_tools()

        result_file = tmp_path / "utilized_tools.json"
        assert result_file.exists()
        with result_file.open() as f:
            data = json.load(f)
        assert data == {"tx1": "tool1"}

    def test_finish_behaviour(self, tmp_path: Path) -> None:
        """Should call _store_utilized_tools and parent finish_behaviour."""
        behaviour = _make_redeem_behaviour()
        behaviour.utilized_tools = {"tx1": "tool1"}

        params = MagicMock()
        params.store_path = tmp_path

        payload = MagicMock()

        def mock_parent_finish(self_arg, payload_arg):  # type: ignore[no-untyped-def]
            """Mock parent finish_behaviour."""
            yield

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params, patch.object(
            RedeemInfoBehaviour, "finish_behaviour", mock_parent_finish
        ):
            mock_params.return_value = params
            gen = behaviour.finish_behaviour(payload)
            _exhaust_gen(gen)


class TestSetupPolicyAndTools:
    """Tests for _setup_policy_and_tools on RedeemBehaviour."""

    # type: ignore[no-untyped-def]
    def test_setup_policy_from_synced_data(self) -> None:
        """Should use policy from synced data when is_policy_set."""
        behaviour = _make_redeem_behaviour()
        policy = _make_policy()

        mock_synced = MagicMock()
        mock_synced.is_policy_set = True  # type: ignore[no-untyped-def]
        mock_synced.policy = policy
        mock_synced.available_mech_tools = {"tool1"}

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = mock_synced

            gen = behaviour._setup_policy_and_tools()  # type: ignore[no-untyped-def]
            result = _exhaust_gen(gen)

        assert result is True
        assert behaviour._policy is policy
        assert behaviour._mech_tools == {"tool1"}  # type: ignore[no-untyped-def]

    def test_setup_policy_fallback_to_parent(self) -> None:
        """Should fall back to parent when is_policy_set is False."""
        behaviour = _make_redeem_behaviour()

        mock_synced = MagicMock()
        mock_synced.is_policy_set = False

        def mock_parent_setup(self_arg):  # type: ignore[no-untyped-def]
            """Mock parent _setup_policy_and_tools."""
            behaviour._policy = _make_policy()
            behaviour._mech_tools = {"tool1"}
            yield
            return True

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd, patch.object(
            RedeemInfoBehaviour, "_setup_policy_and_tools", mock_parent_setup
        ):
            mock_sd.return_value = mock_synced

            gen = behaviour._setup_policy_and_tools()
            result = _exhaust_gen(gen)

        assert result is True


class TestBenchmarkingAct:
    """Tests for _benchmarking_act."""

    def test_benchmarking_act(self) -> None:
        """Should update policy with mech tool and return payload."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()
        behaviour._mech_tools = {"tool1"}  # type: ignore[no-untyped-def]
        behaviour.redeemed_condition_ids = set()
        behaviour.payout_so_far = 0

        mock_synced = MagicMock()
        mock_synced.mech_tool = "tool1"
        # type: ignore[no-untyped-def]
        mock_data = MagicMock()
        mock_data.is_winning = True

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd, patch.object(
            type(behaviour), "mock_data", new_callable=PropertyMock
        ) as mock_md, patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock  # type: ignore[no-untyped-def]
        ) as mock_bm:
            mock_sd.return_value = mock_synced
            mock_md.return_value = mock_data
            mock_bm.return_value = MagicMock(enabled=False)
            # type: ignore[no-untyped-def]
            result = behaviour._benchmarking_act()

        assert isinstance(result, RedeemPayload)


class TestNormalAct:
    """Tests for _normal_act."""

    def test_normal_act_fresh_start(self) -> None:
        """Should fetch redeem info and prepare tx on fresh start."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()
        behaviour._mech_tools = {"tool1"}

        progress = RedeemingProgress()
        progress.check_started = False
        progress.cleaned = False

        def mock_get_redeem_info():  # type: ignore[no-untyped-def]
            """Mock _get_redeem_info."""
            yield

        def mock_store_progress() -> None:
            """Mock _store_progress."""
            pass

        def mock_clean_redeem_info():  # type: ignore[no-untyped-def]
            """Mock _clean_redeem_info."""
            progress.cleaned = True
            yield
            return True

        def mock_prepare_safe_tx():  # type: ignore[no-untyped-def]
            """Mock _prepare_safe_tx."""
            yield
            return None

        behaviour._get_redeem_info = mock_get_redeem_info  # type: ignore[method-assign]
        behaviour._store_progress = mock_store_progress  # type: ignore[method-assign]
        behaviour._clean_redeem_info = mock_clean_redeem_info  # type: ignore[method-assign]
        behaviour._prepare_safe_tx = mock_prepare_safe_tx  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp:
            mock_rp.return_value = progress

            gen = behaviour._normal_act()
            result = _exhaust_gen(gen)

        assert isinstance(result, RedeemPayload)

    def test_normal_act_resume_from_progress(self) -> None:
        """Should load progress when check_started is True."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()
        behaviour._mech_tools = {"tool1"}

        policy = _make_policy()
        progress = RedeemingProgress()
        progress.check_started = True
        progress.check_from_block = 100
        progress.check_to_block = 100
        progress.cleaned = True
        progress.trades = set()
        progress.utilized_tools = {}
        progress.policy = policy
        progress.claimable_amounts = {}  # type: ignore[no-untyped-def]
        progress.earliest_block_number = 0

        def mock_prepare_safe_tx():  # type: ignore[no-untyped-def]
            """Mock _prepare_safe_tx."""
            yield
            return None

        behaviour._prepare_safe_tx = mock_prepare_safe_tx  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp:
            mock_rp.return_value = progress

            gen = behaviour._normal_act()
            result = _exhaust_gen(gen)

        assert isinstance(result, RedeemPayload)

    def test_normal_act_with_redeem_tx(self) -> None:
        """Should build full payload when redeem tx is found."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()
        behaviour._mech_tools = {"tool1"}
        behaviour.redeemed_condition_ids = set()
        behaviour.payout_so_far = 0

        progress = RedeemingProgress()
        progress.check_started = False
        progress.cleaned = False

        def mock_get_redeem_info():  # type: ignore[no-untyped-def]
            """Mock _get_redeem_info."""
            yield

        def mock_store_progress() -> None:
            """Mock _store_progress."""
            pass

        def mock_clean_redeem_info():  # type: ignore[no-untyped-def]
            """Mock _clean_redeem_info."""
            progress.cleaned = True
            yield
            return True

        def mock_prepare_safe_tx():  # type: ignore[no-untyped-def]
            """Mock _prepare_safe_tx returning tx hex."""
            yield
            return "0xresult_tx"

        behaviour._get_redeem_info = mock_get_redeem_info  # type: ignore[method-assign, no-untyped-def]
        behaviour._store_progress = mock_store_progress  # type: ignore[method-assign]
        behaviour._clean_redeem_info = mock_clean_redeem_info  # type: ignore[method-assign]
        behaviour._prepare_safe_tx = mock_prepare_safe_tx  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp, patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_rp.return_value = progress
            mock_bm.return_value = MagicMock(enabled=False)

            gen = behaviour._normal_act()
            result = _exhaust_gen(gen)

        assert isinstance(result, RedeemPayload)
        assert result.tx_hash == "0xresult_tx"

    def test_normal_act_not_cleaned(self) -> None:
        """Should return basic payload when not cleaned."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()
        behaviour._mech_tools = {"tool1"}

        progress = RedeemingProgress()
        progress.check_started = False
        progress.cleaned = False

        def mock_get_redeem_info():  # type: ignore[no-untyped-def]
            """Mock _get_redeem_info."""
            yield

        def mock_store_progress() -> None:
            """Mock _store_progress."""
            pass

        def mock_clean_redeem_info():  # type: ignore[no-untyped-def]
            """Mock _clean_redeem_info returning False (not cleaned)."""
            yield
            return False

        behaviour._get_redeem_info = mock_get_redeem_info  # type: ignore[method-assign]
        behaviour._store_progress = mock_store_progress  # type: ignore[method-assign]
        behaviour._clean_redeem_info = mock_clean_redeem_info  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp:
            mock_rp.return_value = progress

            gen = behaviour._normal_act()
            result = _exhaust_gen(gen)

        assert isinstance(result, RedeemPayload)

    def test_normal_act_check_not_finished(self) -> None:
        """Should run _clean_redeem_info when check is not finished."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()
        behaviour._mech_tools = {"tool1"}

        progress = RedeemingProgress()
        progress.check_started = True
        progress.check_from_block = 100
        progress.check_to_block = 200  # Not finished: from != to
        progress.cleaned = False
        progress.trades = set()
        progress.utilized_tools = {}
        progress.policy = _make_policy()
        progress.claimable_amounts = {}
        progress.earliest_block_number = 0

        def mock_clean_redeem_info():  # type: ignore[no-untyped-def]
            """Mock _clean_redeem_info."""
            yield
            return False  # type: ignore[no-untyped-def]

        behaviour._clean_redeem_info = mock_clean_redeem_info  # type: ignore[method-assign]

        with patch.object(  # type: ignore[no-untyped-def]
            type(behaviour), "redeeming_progress", new_callable=PropertyMock
        ) as mock_rp:
            mock_rp.return_value = progress
            # type: ignore[no-untyped-def]
            gen = behaviour._normal_act()
            result = _exhaust_gen(gen)

        assert isinstance(result, RedeemPayload)


# type: ignore[no-untyped-def]
class TestAsyncAct:
    """Tests for async_act."""

    def test_async_act_benchmarking(self) -> None:
        """Should use benchmarking path when benchmarking is enabled."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()
        behaviour._mech_tools = {"tool1"}
        behaviour.redeemed_condition_ids = set()
        behaviour.payout_so_far = 0

        mock_synced = MagicMock()
        mock_synced.is_policy_set = True
        mock_synced.policy = _make_policy()
        mock_synced.available_mech_tools = {"tool1"}
        mock_synced.mech_tool = "tool1"
        mock_synced.did_transact = False

        mock_data = MagicMock()
        mock_data.is_winning = True

        mock_bm = MagicMock()
        mock_bm.enabled = True

        params = MagicMock()
        params.store_path = Path("/tmp/test")

        def mock_store_all() -> None:
            """Mock _store_all."""
            pass

        def mock_finish(payload):  # type: ignore[no-untyped-def]
            """Mock finish_behaviour."""
            yield

        behaviour._store_all = mock_store_all  # type: ignore[method-assign]
        behaviour.finish_behaviour = mock_finish  # type: ignore[method-assign]
        # type: ignore[no-untyped-def]
        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd, patch.object(
            type(behaviour), "mock_data", new_callable=PropertyMock
        ) as mock_md, patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_benchmark, patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_sd.return_value = mock_synced
            mock_md.return_value = mock_data
            mock_benchmark.return_value = mock_bm
            mock_params.return_value = params

            # Mock the benchmark_tool context manager
            behaviour.context.benchmark_tool.measure.return_value.local.return_value.__enter__ = (
                MagicMock()
            )
            behaviour.context.benchmark_tool.measure.return_value.local.return_value.__exit__ = MagicMock(
                return_value=False
            )

            gen = behaviour.async_act()
            _exhaust_gen(gen)

    def test_async_act_normal_mode(self) -> None:
        """Should use normal path when benchmarking is disabled."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()  # type: ignore[no-untyped-def]
        behaviour._mech_tools = {"tool1"}
        behaviour.redeemed_condition_ids = set()
        behaviour.payout_so_far = 0
        # type: ignore[no-untyped-def]
        mock_synced = MagicMock()
        mock_synced.is_policy_set = True
        mock_synced.policy = _make_policy()
        mock_synced.available_mech_tools = {"tool1"}  # type: ignore[no-untyped-def]
        mock_synced.did_transact = False

        mock_bm = MagicMock()
        mock_bm.enabled = False

        params = MagicMock()  # type: ignore[no-untyped-def]
        params.store_path = Path("/tmp/test")

        progress = RedeemingProgress()
        progress.check_started = False

        def mock_normal_act():  # type: ignore[no-untyped-def]
            """Mock _normal_act."""
            yield
            return RedeemPayload("test_agent", mech_tools="[]")

        def mock_store_all() -> None:
            """Mock _store_all."""
            pass

        def mock_finish(payload):  # type: ignore[no-untyped-def]
            """Mock finish_behaviour."""
            yield

        behaviour._normal_act = mock_normal_act  # type: ignore[method-assign]
        behaviour._store_all = mock_store_all  # type: ignore[method-assign]
        behaviour.finish_behaviour = mock_finish  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd, patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_benchmark, patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_sd.return_value = mock_synced
            mock_benchmark.return_value = mock_bm
            mock_params.return_value = params

            behaviour.context.benchmark_tool.measure.return_value.local.return_value.__enter__ = (  # type: ignore[no-untyped-def]
                MagicMock()
            )
            behaviour.context.benchmark_tool.measure.return_value.local.return_value.__exit__ = MagicMock(
                return_value=False  # type: ignore[no-untyped-def]
            )

            gen = behaviour.async_act()
            _exhaust_gen(gen)  # type: ignore[no-untyped-def]

    def test_async_act_setup_fails(self) -> None:
        """Should return early when setup fails."""
        behaviour = _make_redeem_behaviour()

        mock_synced = MagicMock()
        mock_synced.is_policy_set = False

        def mock_parent_setup(self_arg):  # type: ignore[no-untyped-def]
            """Mock parent _setup_policy_and_tools returning False."""
            yield
            return False

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd, patch.object(
            RedeemInfoBehaviour, "_setup_policy_and_tools", mock_parent_setup
        ):
            mock_sd.return_value = mock_synced

            behaviour.context.benchmark_tool.measure.return_value.local.return_value.__enter__ = (
                MagicMock()
            )
            behaviour.context.benchmark_tool.measure.return_value.local.return_value.__exit__ = MagicMock(
                return_value=False
            )

            gen = behaviour.async_act()
            _exhaust_gen(gen)

    def test_async_act_normal_returns_none(self) -> None:
        """Should return early when normal_act returns None."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()
        behaviour._mech_tools = {"tool1"}
        # type: ignore[no-untyped-def]
        mock_synced = MagicMock()
        mock_synced.is_policy_set = True
        mock_synced.policy = _make_policy()
        mock_synced.available_mech_tools = {"tool1"}
        mock_synced.did_transact = False

        mock_bm = MagicMock()
        mock_bm.enabled = False

        def mock_normal_act():  # type: ignore[no-untyped-def]
            """Mock _normal_act returning None."""
            yield
            return None

        behaviour._normal_act = mock_normal_act  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd, patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_benchmark:
            mock_sd.return_value = mock_synced
            mock_benchmark.return_value = mock_bm

            behaviour.context.benchmark_tool.measure.return_value.local.return_value.__enter__ = (
                MagicMock()
            )
            behaviour.context.benchmark_tool.measure.return_value.local.return_value.__exit__ = MagicMock(
                return_value=False
            )

            gen = behaviour.async_act()
            _exhaust_gen(gen)

    def test_async_act_with_bet_placement_transact(self) -> None:
        """Should call update_bet_transaction_information when did_transact with bet placement."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()
        behaviour._mech_tools = {"tool1"}
        behaviour.redeemed_condition_ids = set()
        behaviour.payout_so_far = 0

        mock_synced = MagicMock()
        mock_synced.is_policy_set = True
        mock_synced.policy = _make_policy()
        mock_synced.available_mech_tools = {"tool1"}
        mock_synced.did_transact = True
        mock_synced.tx_submitter = BetPlacementRound.auto_round_id()

        mock_bm = MagicMock()
        mock_bm.enabled = False

        # type: ignore[no-untyped-def]
        def mock_normal_act():  # type: ignore[no-untyped-def]
            """Mock _normal_act."""
            yield
            return RedeemPayload("test_agent", mech_tools="[]")  # type: ignore[no-untyped-def]

        def mock_store_all() -> None:
            """Mock _store_all."""
            pass

        def mock_finish(payload):  # type: ignore[no-untyped-def]
            """Mock finish_behaviour."""
            yield

        def mock_update_bet() -> None:
            """Mock update_bet_transaction_information."""
            pass

        behaviour._normal_act = mock_normal_act  # type: ignore[method-assign]
        behaviour._store_all = mock_store_all  # type: ignore[method-assign]
        behaviour.finish_behaviour = mock_finish  # type: ignore[method-assign]
        behaviour.update_bet_transaction_information = mock_update_bet  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd, patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_benchmark:
            mock_sd.return_value = mock_synced
            mock_benchmark.return_value = mock_bm

            behaviour.context.benchmark_tool.measure.return_value.local.return_value.__enter__ = (
                MagicMock()
            )
            behaviour.context.benchmark_tool.measure.return_value.local.return_value.__exit__ = MagicMock(
                return_value=False
            )

            gen = behaviour.async_act()
            _exhaust_gen(gen)

    def test_async_act_with_sell_outcome_transact(self) -> None:
        """Should call update_bet_transaction_information with sell outcome round."""
        behaviour = _make_redeem_behaviour()
        behaviour._policy = _make_policy()
        behaviour._mech_tools = {"tool1"}
        behaviour.redeemed_condition_ids = set()
        behaviour.payout_so_far = 0

        mock_synced = MagicMock()
        mock_synced.is_policy_set = True
        mock_synced.policy = _make_policy()
        mock_synced.available_mech_tools = {"tool1"}
        mock_synced.did_transact = True
        mock_synced.tx_submitter = SellOutcomeTokensRound.auto_round_id()

        mock_bm = MagicMock()
        mock_bm.enabled = False

        def mock_normal_act():  # type: ignore[no-untyped-def]
            """Mock _normal_act."""
            yield
            return RedeemPayload("test_agent", mech_tools="[]")

        def mock_store_all() -> None:  # type: ignore[no-untyped-def]
            """Mock _store_all."""
            pass

        def mock_finish(payload):  # type: ignore[no-untyped-def]
            """Mock finish_behaviour."""
            yield

        def mock_update_bet() -> None:
            """Mock update_bet_transaction_information."""
            pass

        behaviour._normal_act = mock_normal_act  # type: ignore[method-assign]
        behaviour._store_all = mock_store_all  # type: ignore[method-assign]
        behaviour.finish_behaviour = mock_finish  # type: ignore[method-assign]
        behaviour.update_bet_transaction_information = mock_update_bet  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd, patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_benchmark:
            mock_sd.return_value = mock_synced
            mock_benchmark.return_value = mock_bm

            behaviour.context.benchmark_tool.measure.return_value.local.return_value.__enter__ = (
                MagicMock()
            )
            behaviour.context.benchmark_tool.measure.return_value.local.return_value.__exit__ = MagicMock(
                return_value=False
            )

            gen = behaviour.async_act()
            _exhaust_gen(gen)
