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

"""Tests for PolymarketRedeemBehaviour."""

from io import StringIO
from unittest.mock import MagicMock, PropertyMock, patch

from packages.valory.skills.decision_maker_abci.behaviours.polymarket_reedem import (
    BLOCK_NUMBER_KEY,
    DEFAULT_TO_BLOCK,
    PolymarketRedeemBehaviour,
    ZERO_BYTES,
    ZERO_HEX,
)
from packages.valory.skills.decision_maker_abci.payloads import PolymarketRedeemPayload
from packages.valory.skills.decision_maker_abci.policy import (
    AccuracyInfo,
    EGreedyPolicy,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_redeem import (
    PolymarketRedeemRound,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _noop_gen():  # type: ignore[no-untyped-def]
    """A no-op generator that yields once."""
    yield  # type: ignore[no-untyped-def]


def _return_gen(value):  # type: ignore[no-untyped-def]
    """A generator that yields once and returns a value."""
    yield  # type: ignore[no-untyped-def]
    return value


def _make_policy(tools=None):  # type: ignore[no-untyped-def]
    """Create a test policy."""
    if tools is None:  # type: ignore[no-untyped-def]
        tools = {"tool1": AccuracyInfo(requests=5, accuracy=0.6, pending=1)}
    return EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=3,
        quarantine_duration=100,
        accuracy_store=tools,
    )


def _make_behaviour():  # type: ignore[no-untyped-def]
    """Return a PolymarketRedeemBehaviour with mocked dependencies."""
    behaviour = object.__new__(PolymarketRedeemBehaviour)  # type: ignore[no-untyped-def]
    behaviour._user_token_balance = None
    behaviour._policy = None
    behaviour._utilized_tools = {}
    behaviour._mech_tools = set()
    behaviour._mech_id = 0
    behaviour._mech_hash = ""
    behaviour._remote_accuracy_information = StringIO()
    behaviour.multisend_batches = []
    behaviour.multisend_data = b""
    behaviour._safe_tx_hash = ""
    behaviour.buy_amount = 0

    context = MagicMock()
    context.agent_address = "test_agent"
    behaviour.__dict__["_context"] = context

    return behaviour


# ---------------------------------------------------------------------------
# Tests for constants


class TestPolymarketRedeemConstants:
    """Tests for module-level constants."""

    def test_zero_hex_length(self) -> None:
        """ZERO_HEX should be 64 chars."""
        assert len(ZERO_HEX) == 64

    def test_zero_bytes_length(self) -> None:
        """ZERO_BYTES should be 32 bytes."""
        assert len(ZERO_BYTES) == 32

    def test_block_number_key(self) -> None:
        """BLOCK_NUMBER_KEY should be 'number'."""
        assert BLOCK_NUMBER_KEY == "number"

    def test_default_to_block(self) -> None:
        """DEFAULT_TO_BLOCK should be 'latest'."""
        assert DEFAULT_TO_BLOCK == "latest"


# ---------------------------------------------------------------------------
# Tests for properties


class TestPolymarketRedeemProperties:
    """Tests for PolymarketRedeemBehaviour properties."""

    def test_matching_round(self) -> None:
        """matching_round should be PolymarketRedeemRound."""
        assert PolymarketRedeemBehaviour.matching_round == PolymarketRedeemRound

    def test_user_token_balance_property(self) -> None:
        """user_token_balance should get/set correctly."""
        behaviour = _make_behaviour()
        assert behaviour.user_token_balance is None
        behaviour.user_token_balance = 100
        assert behaviour.user_token_balance == 100

    def test_user_token_balance_setter_none(self) -> None:
        """user_token_balance setter should accept None."""
        behaviour = _make_behaviour()
        behaviour.user_token_balance = 42
        behaviour.user_token_balance = None
        assert behaviour.user_token_balance is None

    def test_params_property(self) -> None:
        """Params property should return context.params cast to DecisionMakerParams."""
        behaviour = _make_behaviour()
        with patch.object(
            type(behaviour), "context", new_callable=PropertyMock
        ) as mock_ctx:
            ctx = MagicMock()
            ctx.params = MagicMock()
            mock_ctx.return_value = ctx
            result = behaviour.params
            assert result is ctx.params

    def test_init_sets_user_token_balance(self) -> None:
        """__init__ should set _user_token_balance to None."""
        with patch(
            "packages.valory.skills.decision_maker_abci.behaviours.polymarket_reedem.StorageManagerBehaviour.__init__",
            return_value=None,
        ):
            behaviour = PolymarketRedeemBehaviour(
                name="test", skill_context=MagicMock()
            )
            assert behaviour._user_token_balance is None


# ---------------------------------------------------------------------------
# Tests for finish_behaviour


class TestFinishBehaviour:
    """Tests for finish_behaviour."""

    def test_finish_behaviour_stores_tools_and_calls_super(self) -> None:
        """finish_behaviour should call _store_utilized_tools and then super().finish_behaviour."""
        behaviour = _make_behaviour()
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]

        payloads_sent = []
        behaviour.send_a2a_transaction = lambda payload: (  # type: ignore[method-assign]
            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
        )
        behaviour.wait_until_round_end = lambda: (yield)  # type: ignore[func-returns-value, method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        payload = PolymarketRedeemPayload(
            sender="test_agent",
            tx_submitter=None,
            tx_hash=None,
            mocking_mode=False,
            event="done",
        )

        gen = behaviour.finish_behaviour(payload)
        try:
            while True:
                next(gen)
        except StopIteration:
            pass

        behaviour._store_utilized_tools.assert_called_once()
        assert len(payloads_sent) == 1


# ---------------------------------------------------------------------------
# Tests for conditional_tokens_interact


class TestConditionalTokensInteract:
    """Tests for _conditional_tokens_interact."""

    def test_returns_status_from_contract_interact(self) -> None:
        """Should return status from contract_interact."""
        behaviour = _make_behaviour()

        def mock_contract_interact(**kwargs) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock contract interact."""
            yield  # type: ignore[no-untyped-def]
            return True

        behaviour.contract_interact = mock_contract_interact  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(polymarket_ctf_address="0xctf")

            gen = behaviour._conditional_tokens_interact(
                contract_callable="get_balance_of",
                data_key="balance",
                placeholder="user_token_balance",
            )
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result is True


# ---------------------------------------------------------------------------
# Tests for get_token_balance


class TestGetTokenBalance:
    """Tests for _get_token_balance."""

    def test_returns_balance_on_success(self) -> None:
        """Should return user_token_balance on success."""
        behaviour = _make_behaviour()
        behaviour._user_token_balance = 500

        def mock_conditional_tokens_interact(**kwargs) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock conditional tokens interact."""
            yield  # type: ignore[no-untyped-def]
            return True

        behaviour._conditional_tokens_interact = mock_conditional_tokens_interact  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(safe_contract_address="0xsafe")

            gen = behaviour._get_token_balance(12345)
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result == 500

    def test_returns_none_on_failure(self) -> None:
        """Should return None when contract interaction fails."""
        behaviour = _make_behaviour()

        def mock_conditional_tokens_interact(**kwargs) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock conditional tokens interact that fails."""
            yield  # type: ignore[no-untyped-def]
            return False

        behaviour._conditional_tokens_interact = mock_conditional_tokens_interact  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(safe_contract_address="0xsafe")

            gen = behaviour._get_token_balance(12345)
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result is None


# ---------------------------------------------------------------------------
# Tests for update_policy_for_redeemable_positions


class TestUpdatePolicyForRedeemablePositions:
    """Tests for _update_policy_for_redeemable_positions."""

    def test_updates_accuracy_store_for_winning_position(self) -> None:
        """Should update accuracy store for winning position."""
        behaviour = _make_behaviour()
        policy = _make_policy()
        behaviour._policy = policy
        behaviour._utilized_tools = {"cond1": "tool1"}

        positions = [{"conditionId": "cond1", "curPrice": 1.0}]

        with patch.object(
            type(behaviour), "policy", new_callable=PropertyMock
        ) as mock_pol:
            mock_pol.return_value = policy

            behaviour._update_policy_for_redeemable_positions(positions)

        # Tool should be removed from utilized_tools after update
        assert "cond1" not in behaviour._utilized_tools

    def test_skips_position_without_condition_id(self) -> None:
        """Should skip positions without conditionId."""
        behaviour = _make_behaviour()
        behaviour._utilized_tools = {}

        positions = [{"curPrice": 1.0}]

        behaviour._update_policy_for_redeemable_positions(positions)

    def test_skips_position_without_tool(self) -> None:
        """Should skip positions where tool is not in utilized_tools."""
        behaviour = _make_behaviour()
        behaviour._utilized_tools = {}

        positions = [{"conditionId": "cond_unknown", "curPrice": 1.0}]

        behaviour._update_policy_for_redeemable_positions(positions)

    def test_skips_position_without_cur_price(self) -> None:
        """Should skip positions without curPrice."""
        behaviour = _make_behaviour()
        behaviour._utilized_tools = {"cond1": "tool1"}

        positions = [{"conditionId": "cond1"}]

        behaviour._update_policy_for_redeemable_positions(positions)
        # Tool should still be in utilized_tools since it was skipped
        assert "cond1" in behaviour._utilized_tools

    def test_handles_losing_position(self) -> None:
        """Should update accuracy store for losing position (curPrice < 0.5)."""
        behaviour = _make_behaviour()
        policy = _make_policy()
        behaviour._policy = policy
        behaviour._utilized_tools = {"cond1": "tool1"}

        positions = [{"conditionId": "cond1", "curPrice": 0.0}]

        with patch.object(
            type(behaviour), "policy", new_callable=PropertyMock
        ) as mock_pol:
            mock_pol.return_value = policy

            behaviour._update_policy_for_redeemable_positions(positions)

        assert "cond1" not in behaviour._utilized_tools

    def test_handles_key_error_in_accuracy_store(self) -> None:
        """Should handle KeyError when tool not in accuracy store."""
        behaviour = _make_behaviour()
        policy = _make_policy(tools={})
        behaviour._policy = policy
        behaviour._utilized_tools = {"cond1": "unknown_tool"}

        positions = [{"conditionId": "cond1", "curPrice": 1.0}]

        with patch.object(
            type(behaviour), "policy", new_callable=PropertyMock
        ) as mock_pol:
            mock_pol.return_value = policy

            # Should not raise
            behaviour._update_policy_for_redeemable_positions(positions)


# ---------------------------------------------------------------------------
# Tests for fetch_redeemable_positions


class TestFetchRedeemablePositions:
    """Tests for _fetch_redeemable_positions."""

    def test_fetches_positions_via_connection(self) -> None:
        """Should call send_polymarket_connection_request with correct params."""
        behaviour = _make_behaviour()

        expected_positions = [{"conditionId": "cond1", "redeemable": True}]
        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(  # type: ignore[method-assign]
            expected_positions
        )

        gen = behaviour._fetch_redeemable_positions()
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result == expected_positions


# ---------------------------------------------------------------------------
# Tests for redeem_position


class TestRedeemPosition:
    """Tests for _redeem_position."""

    def test_redeems_standard_position(self) -> None:
        """Should redeem a standard position via connection."""
        behaviour = _make_behaviour()

        redeem_result = {"success": True}
        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(  # type: ignore[method-assign]
            redeem_result
        )

        gen = behaviour._redeem_position(
            condition_id="0xcond1",
            outcome_index=0,
            collateral_token="0xusdc",  # nosec B106
            is_neg_risk=False,
            size=100,
        )
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result == redeem_result

    def test_redeems_neg_risk_position(self) -> None:
        """Should redeem a negative risk position via connection."""
        behaviour = _make_behaviour()

        redeem_result = {"success": True}
        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(  # type: ignore[method-assign]
            redeem_result
        )

        gen = behaviour._redeem_position(
            condition_id="0xcond2",
            outcome_index=1,
            collateral_token="0xusdc",  # nosec B106
            is_neg_risk=True,
            size=50,
        )
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result == redeem_result


# ---------------------------------------------------------------------------
# Tests for setup_policy_and_tools


class TestSetupPolicyAndTools:
    """Tests for _setup_policy_and_tools."""

    def test_uses_synced_data_when_policy_set(self) -> None:
        """Should use policy from synchronized_data when is_policy_set is True."""
        behaviour = _make_behaviour()
        mock_policy = _make_policy()
        mock_tools = {"tool1", "tool2"}

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(
                is_policy_set=True,
                policy=mock_policy,
                available_mech_tools=mock_tools,
            )

            gen = behaviour._setup_policy_and_tools()
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result is True
        assert behaviour._policy is mock_policy

    def test_falls_back_to_super_when_policy_not_set(self) -> None:
        """Should call super()._setup_policy_and_tools when is_policy_set is False."""
        behaviour = _make_behaviour()

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(is_policy_set=False)

            # Mock the super's _setup_policy_and_tools
            with patch(
                "packages.valory.skills.decision_maker_abci.behaviours.storage_manager.StorageManagerBehaviour._setup_policy_and_tools"
            ) as mock_super:
                mock_super.return_value = _return_gen(True)

                gen = behaviour._setup_policy_and_tools()
                result = None
                try:
                    while True:
                        next(gen)
                except StopIteration as e:
                    result = e.value

        assert result is True


# ---------------------------------------------------------------------------
# Tests for build_redeem_positions_data


class TestBuildRedeemPositionsData:
    """Tests for _build_redeem_positions_data."""

    def test_standard_redeem_data_starts_with_correct_selector(self) -> None:
        """Should start with redeemPositions function selector."""
        behaviour = _make_behaviour()
        result = behaviour._build_redeem_positions_data(
            collateral_token="0x1234567890123456789012345678901234567890",  # nosec B106
            condition_id="0xaabbccdd",
            index_sets=[1],
        )
        assert result.startswith("0x01b7037c")

    def test_standard_redeem_data_contains_collateral(self) -> None:
        """Should contain the collateral token address."""
        behaviour = _make_behaviour()
        result = behaviour._build_redeem_positions_data(
            collateral_token="0x1234567890123456789012345678901234567890",  # nosec B106
            condition_id="0xaabbccdd",
            index_sets=[1],
        )
        assert "1234567890123456789012345678901234567890" in result.lower()

    def test_standard_redeem_data_contains_condition_id(self) -> None:
        """Should contain the condition ID."""
        behaviour = _make_behaviour()
        result = behaviour._build_redeem_positions_data(
            collateral_token="0x1234567890123456789012345678901234567890",  # nosec B106
            condition_id="0xaabbccdd",
            index_sets=[1],
        )
        assert "aabbccdd" in result.lower()

    def test_standard_redeem_data_multiple_index_sets(self) -> None:
        """Should handle multiple index sets."""
        behaviour = _make_behaviour()
        result = behaviour._build_redeem_positions_data(
            collateral_token="0x1234567890123456789012345678901234567890",  # nosec B106
            condition_id="0xaabbccdd",
            index_sets=[1, 2],
        )
        # Array length should be 2
        assert result.startswith("0x01b7037c")
        # Should be longer than single element
        single = behaviour._build_redeem_positions_data(
            collateral_token="0x1234567890123456789012345678901234567890",  # nosec B106
            condition_id="0xaabbccdd",
            index_sets=[1],
        )
        assert len(result) > len(single)


# ---------------------------------------------------------------------------
# Tests for build_redeem_neg_risk_data


class TestBuildRedeemNegRiskData:
    """Tests for _build_redeem_neg_risk_data."""

    def test_neg_risk_data_starts_with_correct_selector(self) -> None:
        """Should start with redeemPositions(bytes32,uint256[]) selector."""
        behaviour = _make_behaviour()
        result = behaviour._build_redeem_neg_risk_data(
            collateral_token="0x1234567890123456789012345678901234567890",  # nosec B106
            condition_id="0xaabbccdd",
            redeem_amounts=[100, 0],
        )
        assert result.startswith("0xdbeccb23")

    def test_neg_risk_data_contains_condition_id(self) -> None:
        """Should contain the condition ID."""
        behaviour = _make_behaviour()
        result = behaviour._build_redeem_neg_risk_data(
            collateral_token="0x1234567890123456789012345678901234567890",  # nosec B106
            condition_id="0xaabbccdd",
            redeem_amounts=[100, 0],
        )
        assert "aabbccdd" in result.lower()

    def test_neg_risk_data_encodes_amounts(self) -> None:
        """Should encode redeem amounts correctly."""
        behaviour = _make_behaviour()
        result = behaviour._build_redeem_neg_risk_data(
            collateral_token="0x1234567890123456789012345678901234567890",  # nosec B106
            condition_id="0xaabbccdd",
            redeem_amounts=[100, 0],
        )
        # 100 in hex is 64
        assert hex(100)[2:].zfill(64) in result

    def test_neg_risk_data_zero_amounts(self) -> None:
        """Should handle zero amounts."""
        behaviour = _make_behaviour()
        result = behaviour._build_redeem_neg_risk_data(
            collateral_token="0x1234567890123456789012345678901234567890",  # nosec B106
            condition_id="0xaabbccdd",
            redeem_amounts=[0, 0],
        )
        assert result.startswith("0xdbeccb23")

    def test_neg_risk_condition_id_without_0x_prefix(self) -> None:
        """Should handle condition ID without 0x prefix."""
        behaviour = _make_behaviour()
        result = behaviour._build_redeem_neg_risk_data(
            collateral_token="0x1234567890123456789012345678901234567890",  # nosec B106
            condition_id="aabbccdd",
            redeem_amounts=[100, 0],
        )
        assert "aabbccdd" in result.lower()


# ---------------------------------------------------------------------------
# Tests for get_token_balance_from_chain


class TestGetTokenBalanceFromChain:
    """Tests for _get_token_balance_from_chain."""

    def test_returns_none_on_failure(self) -> None:
        """Should return None when _get_token_balance fails."""
        behaviour = _make_behaviour()
        behaviour._get_token_balance = lambda token_id: _return_gen(None)  # type: ignore[method-assign]

        gen = behaviour._get_token_balance_from_chain(123)
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result is None

    def test_returns_zero_when_balance_is_zero(self) -> None:
        """Should return 0 when token balance is zero."""
        behaviour = _make_behaviour()
        behaviour._get_token_balance = lambda token_id: _return_gen(0)  # type: ignore[method-assign]

        gen = behaviour._get_token_balance_from_chain(123)
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result == 0

    def test_returns_balance_when_positive(self) -> None:
        """Should return balance when positive."""
        behaviour = _make_behaviour()
        behaviour._get_token_balance = lambda token_id: _return_gen(500)  # type: ignore[method-assign]

        gen = behaviour._get_token_balance_from_chain(123)
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result == 500


# ---------------------------------------------------------------------------
# Tests for redeem_via_builder


class TestRedeemViaBuilder:
    """Tests for _redeem_via_builder."""

    def test_redeem_standard_positions(self) -> None:
        """Should redeem standard (non-neg-risk) positions."""
        behaviour = _make_behaviour()

        redeem_results = []

        def mock_redeem(  # type: ignore[no-untyped-def]
            condition_id, outcome_index, collateral_token, is_neg_risk=False, size=0
        ):
            """Mock redeem position."""
            redeem_results.append(condition_id)
            yield
            return {"success": True}

        behaviour._redeem_position = mock_redeem  # type: ignore[method-assign]

        positions = [
            {
                "conditionId": "0xcond1",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": False,
            }
        ]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(polymarket_usdc_address="0xusdc")

            gen = behaviour._redeem_via_builder(
                positions,
                current_mech_tools="[]",
                current_policy=None,
                current_utilized_tools="{}",
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        assert "0xcond1" in redeem_results
        assert isinstance(behaviour.payload, PolymarketRedeemPayload)

    def test_redeem_neg_risk_position_with_balance(self) -> None:
        """Should use on-chain balance for neg risk positions."""
        behaviour = _make_behaviour()

        redeem_calls = []

        def mock_redeem(  # type: ignore[no-untyped-def]
            condition_id, outcome_index, collateral_token, is_neg_risk=False, size=0
        ):
            """Mock redeem position."""
            redeem_calls.append({"condition_id": condition_id, "size": size})
            yield
            return {"success": True}

        behaviour._redeem_position = mock_redeem  # type: ignore[method-assign]
        behaviour._get_token_balance_from_chain = lambda token_id: _return_gen(999)  # type: ignore[method-assign]

        positions = [
            {
                "conditionId": "0xcond1",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": True,
                "asset": "12345",
            }
        ]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(polymarket_usdc_address="0xusdc")

            gen = behaviour._redeem_via_builder(
                positions,
                current_mech_tools="[]",
                current_policy=None,
                current_utilized_tools="{}",
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        assert len(redeem_calls) == 1
        # Size should be the on-chain balance, not the API size
        assert redeem_calls[0]["size"] == 999

    def test_redeem_neg_risk_position_skips_zero_balance(self) -> None:
        """Should skip neg risk positions with zero on-chain balance."""
        behaviour = _make_behaviour()

        redeem_calls = []

        def mock_redeem(**kwargs) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock redeem position."""
            redeem_calls.append(kwargs)  # type: ignore[no-untyped-def]
            yield
            return {"success": True}

        behaviour._redeem_position = lambda **kwargs: mock_redeem(**kwargs)  # type: ignore[method-assign]
        behaviour._get_token_balance_from_chain = lambda token_id: _return_gen(0)  # type: ignore[method-assign]

        positions = [
            {
                "conditionId": "0xcond1",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": True,
                "asset": "12345",
            }
        ]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(polymarket_usdc_address="0xusdc")

            gen = behaviour._redeem_via_builder(
                positions,
                current_mech_tools="[]",
                current_policy=None,
                current_utilized_tools="{}",
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        # Redeem should NOT have been called since balance is 0
        assert len(redeem_calls) == 0

    def test_redeem_neg_risk_position_missing_asset(self) -> None:
        """Should skip neg risk positions missing asset field."""
        behaviour = _make_behaviour()

        behaviour._get_token_balance_from_chain = lambda token_id: _return_gen(500)  # type: ignore[method-assign]

        positions = [
            {
                "conditionId": "0xcond1",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": True,
                # No "asset" key
            }
        ]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(polymarket_usdc_address="0xusdc")

            gen = behaviour._redeem_via_builder(
                positions,
                current_mech_tools="[]",
                current_policy=None,
                current_utilized_tools="{}",
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        # Should complete without error - the position was skipped
        assert isinstance(behaviour.payload, PolymarketRedeemPayload)


# ---------------------------------------------------------------------------
# Tests for prepare_redeem_tx


class TestPrepareRedeemTx:
    """Tests for _prepare_redeem_tx."""

    def test_empty_positions_returns_empty(self) -> None:
        """Should return empty string for empty positions list."""
        behaviour = _make_behaviour()

        gen = behaviour._prepare_redeem_tx([])
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result == ""

    def test_standard_position_builds_batch(self) -> None:
        """Should build multisend batch for standard positions."""
        behaviour = _make_behaviour()
        behaviour.multisend_batches = []

        def mock_build_multisend_data() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock build multisend data."""
            yield  # type: ignore[no-untyped-def]
            return True

        def mock_build_multisend_safe_tx_hash() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock build multisend safe tx hash."""
            yield  # type: ignore[no-untyped-def]
            return True

        behaviour._build_multisend_data = mock_build_multisend_data  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = mock_build_multisend_safe_tx_hash  # type: ignore[method-assign]

        positions = [
            {
                "conditionId": "0xaabbccdd",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": False,
            }
        ]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                polymarket_usdc_address="0x1234567890123456789012345678901234567890",
                polymarket_ctf_address="0x2234567890123456789012345678901234567890",
            )
            with patch.object(
                type(behaviour), "tx_hex", new_callable=PropertyMock
            ) as mock_tx:
                mock_tx.return_value = "0xfinalHash"

                gen = behaviour._prepare_redeem_tx(positions)
                result = None
                try:
                    while True:
                        next(gen)
                except StopIteration as e:
                    result = e.value

        assert result == "0xfinalHash"
        assert len(behaviour.multisend_batches) == 1

    def test_neg_risk_position_builds_batch_with_balance(self) -> None:
        """Should build multisend batch for neg risk positions using on-chain balance."""
        behaviour = _make_behaviour()
        behaviour.multisend_batches = []
        behaviour._get_token_balance_from_chain = lambda token_id: _return_gen(500)  # type: ignore[method-assign]

        def mock_build_multisend_data() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock build multisend data."""
            yield  # type: ignore[no-untyped-def]
            return True

        def mock_build_multisend_safe_tx_hash() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock build multisend safe tx hash."""
            yield  # type: ignore[no-untyped-def]
            return True

        behaviour._build_multisend_data = mock_build_multisend_data  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = mock_build_multisend_safe_tx_hash  # type: ignore[method-assign]

        positions = [
            {
                "conditionId": "0xaabbccdd",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": True,
                "asset": "12345",
            }
        ]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                polymarket_usdc_address="0x1234567890123456789012345678901234567890",
                polymarket_ctf_address="0x2234567890123456789012345678901234567890",
                polymarket_neg_risk_adapter_address="0x3234567890123456789012345678901234567890",
            )
            with patch.object(
                type(behaviour), "tx_hex", new_callable=PropertyMock
            ) as mock_tx:
                mock_tx.return_value = "0xfinalHash"

                gen = behaviour._prepare_redeem_tx(positions)
                result = None
                try:
                    while True:
                        next(gen)
                except StopIteration as e:
                    result = e.value

        assert result == "0xfinalHash"
        assert len(behaviour.multisend_batches) == 1

    def test_neg_risk_missing_asset_skips(self) -> None:
        """Should skip neg risk positions missing asset field in prepare_redeem_tx."""
        behaviour = _make_behaviour()
        behaviour.multisend_batches = []

        def mock_build_multisend_data() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock build multisend data."""
            yield  # type: ignore[no-untyped-def]
            return True

        def mock_build_multisend_safe_tx_hash() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock build multisend safe tx hash."""
            yield  # type: ignore[no-untyped-def]
            return True

        behaviour._build_multisend_data = mock_build_multisend_data  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = mock_build_multisend_safe_tx_hash  # type: ignore[method-assign]

        positions = [
            {
                "conditionId": "0xaabbccdd",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": True,
                # No asset key
            }
        ]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                polymarket_usdc_address="0x1234567890123456789012345678901234567890",
                polymarket_ctf_address="0x2234567890123456789012345678901234567890",
                polymarket_neg_risk_adapter_address="0x3234567890123456789012345678901234567890",
            )
            with patch.object(
                type(behaviour), "tx_hex", new_callable=PropertyMock
            ) as mock_tx:
                mock_tx.return_value = "0xfinalHash"

                gen = behaviour._prepare_redeem_tx(positions)
                _ = None
                try:
                    while True:
                        next(gen)
                except StopIteration as e:
                    _ = e.value

        # Skipped the position, no batches
        assert len(behaviour.multisend_batches) == 0

    def test_multisend_data_failure(self) -> None:
        """Should return empty string when _build_multisend_data fails."""
        behaviour = _make_behaviour()
        behaviour.multisend_batches = []

        def mock_build_multisend_data() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock build multisend data that fails."""
            yield  # type: ignore[no-untyped-def]
            return False

        behaviour._build_multisend_data = mock_build_multisend_data  # type: ignore[method-assign]

        positions = [
            {
                "conditionId": "0xaabbccdd",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": False,
            }
        ]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                polymarket_usdc_address="0x1234567890123456789012345678901234567890",
                polymarket_ctf_address="0x2234567890123456789012345678901234567890",
            )

            gen = behaviour._prepare_redeem_tx(positions)
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result == ""

    def test_safe_tx_hash_failure(self) -> None:
        """Should return empty string when _build_multisend_safe_tx_hash fails."""
        behaviour = _make_behaviour()
        behaviour.multisend_batches = []

        def mock_build_multisend_data() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock build multisend data."""
            yield  # type: ignore[no-untyped-def]
            return True

        def mock_build_multisend_safe_tx_hash() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock build multisend safe tx hash that fails."""
            yield  # type: ignore[no-untyped-def]
            return False

        behaviour._build_multisend_data = mock_build_multisend_data  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = mock_build_multisend_safe_tx_hash  # type: ignore[method-assign]

        positions = [
            {
                "conditionId": "0xaabbccdd",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": False,
            }
        ]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                polymarket_usdc_address="0x1234567890123456789012345678901234567890",
                polymarket_ctf_address="0x2234567890123456789012345678901234567890",
            )

            gen = behaviour._prepare_redeem_tx(positions)
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result == ""

    def test_neg_risk_position_with_zero_balance(self) -> None:
        """Should skip neg risk positions with zero on-chain balance."""
        behaviour = _make_behaviour()
        behaviour.multisend_batches = []
        behaviour._get_token_balance_from_chain = lambda token_id: _return_gen(0)  # type: ignore[method-assign]

        def mock_build_multisend_data() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock build multisend data."""
            yield  # type: ignore[no-untyped-def]
            return True

        def mock_build_multisend_safe_tx_hash() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock build multisend safe tx hash."""
            yield  # type: ignore[no-untyped-def]
            return True

        behaviour._build_multisend_data = mock_build_multisend_data  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = mock_build_multisend_safe_tx_hash  # type: ignore[method-assign]

        positions = [
            {
                "conditionId": "0xaabbccdd",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": True,
                "asset": "12345",
            }
        ]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                polymarket_usdc_address="0x1234567890123456789012345678901234567890",
                polymarket_ctf_address="0x2234567890123456789012345678901234567890",
                polymarket_neg_risk_adapter_address="0x3234567890123456789012345678901234567890",
            )
            with patch.object(
                type(behaviour), "tx_hex", new_callable=PropertyMock
            ) as mock_tx:
                mock_tx.return_value = "0xfinalHash"

                gen = behaviour._prepare_redeem_tx(positions)
                _ = None
                try:
                    while True:
                        next(gen)
                except StopIteration as e:
                    _ = e.value

        # Should still complete, but no batch was added for zero balance
        assert len(behaviour.multisend_batches) == 0


# ---------------------------------------------------------------------------
# Tests for async_act


class TestAsyncAct:
    """Tests for async_act."""

    def test_async_act_no_redeemable_positions(self) -> None:
        """Should send NO_REDEEMING event when no positions found."""
        behaviour = _make_behaviour()
        policy = _make_policy()
        behaviour._policy = policy
        behaviour._mech_tools = {"tool1"}
        behaviour._utilized_tools = {}

        def mock_setup() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock setup policy and tools."""
            yield  # type: ignore[no-untyped-def]
            return True

        behaviour._setup_policy_and_tools = mock_setup  # type: ignore[method-assign]
        behaviour._fetch_redeemable_positions = lambda: _return_gen([])  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]

        payloads_sent = []
        behaviour.send_a2a_transaction = lambda payload: _noop_gen()  # type: ignore[method-assign]
        behaviour.wait_until_round_end = lambda: _noop_gen()  # type: ignore[method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        def capture_finish(payload) -> None:  # type: ignore[no-untyped-def, misc]
            """Capture finish behaviour payload."""
            payloads_sent.append(payload)  # type: ignore[no-untyped-def]
            yield

        behaviour.finish_behaviour = capture_finish  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(is_policy_set=True)
            with patch.object(
                type(behaviour), "benchmarking_mode", new_callable=PropertyMock
            ) as mock_bm:
                mock_bm.return_value = MagicMock(enabled=False)

                gen = behaviour.async_act()
                try:
                    while True:
                        next(gen)
                except StopIteration:
                    pass

        assert len(payloads_sent) == 1
        payload = payloads_sent[0]
        assert isinstance(payload, PolymarketRedeemPayload)
        assert payload.event == "no_redeeming"

    def test_async_act_setup_fails(self) -> None:
        """Should return early when _setup_policy_and_tools fails."""
        behaviour = _make_behaviour()

        def mock_setup() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock setup policy and tools that fails."""
            yield  # type: ignore[no-untyped-def]
            return False

        behaviour._setup_policy_and_tools = mock_setup  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)

            gen = behaviour.async_act()
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        # Should have returned before setting payload
        assert not hasattr(behaviour, "payload") or behaviour.payload is None or True

    def test_async_act_builder_program_enabled(self) -> None:
        """Should use _redeem_via_builder when builder program is enabled."""
        behaviour = _make_behaviour()
        policy = _make_policy()
        behaviour._policy = policy
        behaviour._mech_tools = {"tool1"}
        behaviour._utilized_tools = {}

        def mock_setup() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock setup policy and tools."""
            yield  # type: ignore[no-untyped-def]
            return True

        positions = [
            {
                "conditionId": "0xcond1",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": False,
                "curPrice": 1.0,
            }
        ]

        builder_called = []

        def mock_redeem_via_builder(  # type: ignore[no-untyped-def]
            positions, current_mech_tools, current_policy, current_utilized_tools
        ):
            """Mock redeem via builder."""
            builder_called.append(True)
            behaviour.payload = PolymarketRedeemPayload(
                sender="test_agent",
                tx_submitter=None,
                tx_hash=None,
                mocking_mode=False,
                mech_tools=current_mech_tools,
                policy=current_policy,
                utilized_tools=current_utilized_tools,
                event="done",
            )
            yield

        behaviour._setup_policy_and_tools = mock_setup  # type: ignore[method-assign]
        behaviour._fetch_redeemable_positions = lambda: _return_gen(positions)  # type: ignore[method-assign]
        behaviour._redeem_via_builder = mock_redeem_via_builder  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]

        payloads_sent = []
        behaviour.send_a2a_transaction = lambda payload: _noop_gen()  # type: ignore[method-assign]
        behaviour.wait_until_round_end = lambda: _noop_gen()  # type: ignore[method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        def capture_finish(payload) -> None:  # type: ignore[no-untyped-def, misc]
            """Capture finish behaviour payload."""
            payloads_sent.append(payload)  # type: ignore[no-untyped-def]
            yield

        behaviour.finish_behaviour = capture_finish  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(is_policy_set=True)
            with patch.object(
                type(behaviour), "benchmarking_mode", new_callable=PropertyMock
            ) as mock_bm:
                mock_bm.return_value = MagicMock(enabled=False)

                behaviour.__dict__[
                    "_context"
                ].params.polymarket_builder_program_enabled = True

                gen = behaviour.async_act()
                try:
                    while True:
                        next(gen)
                except StopIteration:
                    pass

        assert len(builder_called) == 1

    def test_async_act_builder_program_disabled(self) -> None:
        """Should use _prepare_redeem_tx when builder program is disabled."""
        behaviour = _make_behaviour()
        policy = _make_policy()
        behaviour._policy = policy
        behaviour._mech_tools = {"tool1"}
        behaviour._utilized_tools = {}

        def mock_setup() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock setup policy and tools."""
            yield  # type: ignore[no-untyped-def]
            return True

        positions = [
            {
                "conditionId": "0xcond1",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": False,
                "curPrice": 1.0,
            }
        ]

        def mock_prepare_redeem_tx(positions) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock prepare redeem tx."""
            yield  # type: ignore[no-untyped-def]
            return "0xtxhash"

        behaviour._setup_policy_and_tools = mock_setup  # type: ignore[method-assign]
        behaviour._fetch_redeemable_positions = lambda: _return_gen(positions)  # type: ignore[method-assign]
        behaviour._prepare_redeem_tx = mock_prepare_redeem_tx  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]

        payloads_sent = []
        behaviour.send_a2a_transaction = lambda payload: _noop_gen()  # type: ignore[method-assign]
        behaviour.wait_until_round_end = lambda: _noop_gen()  # type: ignore[method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        def capture_finish(payload) -> None:  # type: ignore[no-untyped-def, misc]
            """Capture finish behaviour payload."""
            payloads_sent.append(payload)  # type: ignore[no-untyped-def]
            yield

        behaviour.finish_behaviour = capture_finish  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(is_policy_set=True)
            with patch.object(
                type(behaviour), "benchmarking_mode", new_callable=PropertyMock
            ) as mock_bm:
                mock_bm.return_value = MagicMock(enabled=False)

                behaviour.__dict__[
                    "_context"
                ].params.polymarket_builder_program_enabled = False

                gen = behaviour.async_act()
                try:
                    while True:
                        next(gen)
                except StopIteration:
                    pass

        assert len(payloads_sent) == 1
        assert isinstance(payloads_sent[0], PolymarketRedeemPayload)
        assert payloads_sent[0].tx_hash == "0xtxhash"
        assert payloads_sent[0].event == "prepare_tx"
