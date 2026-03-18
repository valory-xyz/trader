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

"""Tests for BetPlacementBehaviour."""

from unittest.mock import MagicMock, PropertyMock, patch

from packages.valory.skills.decision_maker_abci.behaviours.base import WXDAI
from packages.valory.skills.decision_maker_abci.behaviours.bet_placement import (
    BetPlacementBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import BetPlacementPayload

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


def _make_behaviour():  # type: ignore[no-untyped-def]
    """Return a BetPlacementBehaviour with mocked dependencies."""
    behaviour = object.__new__(BetPlacementBehaviour)  # type: ignore[no-untyped-def]
    behaviour.buy_amount = 0

    context = MagicMock()
    context.agent_address = "test_agent"
    behaviour.__dict__["_context"] = context

    benchmarking_mode = MagicMock()
    benchmarking_mode.enabled = False

    return behaviour, benchmarking_mode


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBetPlacementBehaviour:
    """Tests for BetPlacementBehaviour."""

    def test_init_sets_buy_amount(self) -> None:
        """__init__ should set buy_amount to 0."""
        with patch(
            "packages.valory.skills.decision_maker_abci.behaviours.bet_placement.DecisionMakerBaseBehaviour.__init__",
            return_value=None,
        ):
            behaviour = BetPlacementBehaviour(name="test", skill_context=MagicMock())
            assert behaviour.buy_amount == 0

    def test_w_xdai_deficit_property(self) -> None:
        """w_xdai_deficit should return investment_amount - token_balance."""
        behaviour, bm = _make_behaviour()
        behaviour.token_balance = 100

        with patch.object(
            type(behaviour), "investment_amount", new_callable=PropertyMock
        ) as mock_inv:
            mock_inv.return_value = 250
            assert behaviour.w_xdai_deficit == 150

    def test_build_exchange_tx_success(self) -> None:
        """_build_exchange_tx should return True on success and append a batch."""
        behaviour, bm = _make_behaviour()
        behaviour.multisend_batches = []

        with patch.object(
            type(behaviour), "collateral_token", new_callable=PropertyMock
        ) as mock_ct:
            mock_ct.return_value = WXDAI
            with patch.object(
                type(behaviour), "w_xdai_deficit", new_callable=PropertyMock
            ) as mock_deficit:
                mock_deficit.return_value = 100
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(mech_chain_id="gnosis")

                    # Mock get_contract_api_response
                    response_msg = MagicMock()
                    from packages.valory.protocols.contract_api import (
                        ContractApiMessage,
                    )

                    response_msg.performative = ContractApiMessage.Performative.STATE
                    response_msg.state.body = {"data": "0xdeadbeef"}

                    behaviour.get_contract_api_response = lambda **kwargs: _return_gen(  # type: ignore[method-assign]
                        response_msg
                    )

                    gen = behaviour._build_exchange_tx()
                    result = None
                    try:
                        while True:
                            next(gen)
                    except StopIteration as e:
                        result = e.value

                    assert result is True
                    assert len(behaviour.multisend_batches) == 1

    def test_build_exchange_tx_failure_bad_performative(self) -> None:
        """_build_exchange_tx should return False on bad performative."""
        behaviour, bm = _make_behaviour()

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(mech_chain_id="gnosis")

            response_msg = MagicMock()
            from packages.valory.protocols.contract_api import ContractApiMessage

            response_msg.performative = ContractApiMessage.Performative.ERROR

            behaviour.get_contract_api_response = lambda **kwargs: _return_gen(  # type: ignore[method-assign]
                response_msg
            )

            gen = behaviour._build_exchange_tx()
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

            assert result is False

    def test_build_exchange_tx_failure_no_data(self) -> None:
        """_build_exchange_tx should return False when data is None."""
        behaviour, bm = _make_behaviour()

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(mech_chain_id="gnosis")

            response_msg = MagicMock()
            from packages.valory.protocols.contract_api import ContractApiMessage

            response_msg.performative = ContractApiMessage.Performative.STATE
            response_msg.state.body = {"data": None}

            behaviour.get_contract_api_response = lambda **kwargs: _return_gen(  # type: ignore[method-assign]
                response_msg
            )

            gen = behaviour._build_exchange_tx()
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

            assert result is False

    def test_build_approval_tx(self) -> None:
        """_build_approval_tx should delegate to build_approval_tx."""
        behaviour, bm = _make_behaviour()

        def mock_build_approval(amount, spender, token) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock build approval tx."""
            yield  # type: ignore[no-untyped-def]
            return True

        behaviour.build_approval_tx = mock_build_approval  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "investment_amount", new_callable=PropertyMock
        ) as mock_inv:
            mock_inv.return_value = 500
            with patch.object(
                type(behaviour),
                "market_maker_contract_address",
                new_callable=PropertyMock,
            ) as mock_mca:
                mock_mca.return_value = "0xmarket"
                with patch.object(
                    type(behaviour), "collateral_token", new_callable=PropertyMock
                ) as mock_ct:
                    mock_ct.return_value = WXDAI

                    gen = behaviour._build_approval_tx()
                    result = None
                    try:
                        while True:
                            next(gen)
                    except StopIteration as e:
                        result = e.value

                    assert result is True

    def test_prepare_safe_tx_calc_fails(self) -> None:
        """_prepare_safe_tx should return None when _calc_buy_amount fails."""
        behaviour, bm = _make_behaviour()

        def mock_wait(condition) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition."""
            yield  # type: ignore[no-untyped-def]

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]

        def mock_calc() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock calc buy amount that fails."""
            yield  # type: ignore[no-untyped-def]
            return False

        behaviour._calc_buy_amount = mock_calc  # type: ignore[method-assign]

        gen = behaviour._prepare_safe_tx()
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result is None

    def test_prepare_safe_tx_success(self) -> None:
        """_prepare_safe_tx should return tx_hex on success."""
        behaviour, bm = _make_behaviour()
        behaviour.buy_amount = 1000

        def mock_wait(condition) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition."""
            yield  # type: ignore[no-untyped-def]

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]

        def mock_calc() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock calc buy amount."""
            yield  # type: ignore[no-untyped-def]
            return True

        behaviour._calc_buy_amount = mock_calc  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"

        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = mock_bet
            with patch.object(
                type(behaviour), "outcome_index", new_callable=PropertyMock
            ) as mock_oi:
                mock_oi.return_value = 0
                with patch.object(
                    type(behaviour), "investment_amount", new_callable=PropertyMock
                ) as mock_inv:
                    mock_inv.return_value = 500
                    with patch.object(
                        type(behaviour), "synchronized_data", new_callable=PropertyMock
                    ) as mock_sd:
                        mock_sd.return_value = MagicMock(confidence=0.8)
                        with patch.object(
                            type(behaviour), "tx_hex", new_callable=PropertyMock
                        ) as mock_tx:
                            mock_tx.return_value = "0xfinalhash"

                            behaviour._collateral_amount_info = lambda x: f"{x} WEI"  # type: ignore[method-assign]

                            gen = behaviour._prepare_safe_tx()
                            result = None
                            try:
                                while True:
                                    next(gen)
                            except StopIteration as e:
                                result = e.value

        assert result == "0xfinalhash"

    def test_async_act_benchmarking_mode(self) -> None:
        """In benchmarking mode, async_act should send payload with mocking_mode=True."""
        behaviour, bm = _make_behaviour()
        bm.enabled = True

        payloads_sent = []

        behaviour.send_a2a_transaction = lambda payload: (  # type: ignore[method-assign]
            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
        )
        behaviour.wait_until_round_end = lambda: _noop_gen()  # type: ignore[func-returns-value, method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]
        behaviour.update_bet_transaction_information = MagicMock()  # type: ignore[method-assign]
        behaviour.wallet_balance = 1000

        # After benchmarking finish_behaviour completes, code falls through.
        # Mock everything needed by the non-benchmarking path too.
        behaviour.wait_for_condition_with_sleep = lambda cond: _noop_gen()  # type: ignore[method-assign]
        behaviour.token_balance = 0

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = bm
            with patch.object(
                type(behaviour), "investment_amount", new_callable=PropertyMock
            ) as mock_inv:
                mock_inv.return_value = 100
                with patch.object(
                    type(behaviour), "is_wxdai", new_callable=PropertyMock
                ) as mock_wxdai:
                    mock_wxdai.return_value = False

                    gen = behaviour.async_act()
                    try:
                        while True:
                            next(gen)
                    except StopIteration:
                        pass

        # First payload should be the benchmarking payload with mocking_mode=True
        assert len(payloads_sent) >= 1
        payload = payloads_sent[0]
        assert isinstance(payload, BetPlacementPayload)
        assert payload.mocking_mode is True
        behaviour.update_bet_transaction_information.assert_called_once()

    def test_async_act_sufficient_balance(self) -> None:
        """When token_balance >= investment_amount, should prepare safe tx."""
        behaviour, bm = _make_behaviour()

        payloads_sent = []

        behaviour.send_a2a_transaction = lambda payload: (  # type: ignore[method-assign]
            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
        )
        behaviour.wait_until_round_end = lambda: _noop_gen()  # type: ignore[func-returns-value, method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]
        behaviour.wallet_balance = 2000
        behaviour.token_balance = 500
        behaviour.check_balance = MagicMock()  # type: ignore[method-assign]

        behaviour.wait_for_condition_with_sleep = lambda cond: _noop_gen()  # type: ignore[method-assign]

        def mock_prepare() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock prepare safe tx."""
            yield  # type: ignore[no-untyped-def]
            return "0xsafetxhash"

        behaviour._prepare_safe_tx = mock_prepare  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "investment_amount", new_callable=PropertyMock
            ) as mock_inv:
                mock_inv.return_value = 100
                with patch.object(
                    type(behaviour), "is_wxdai", new_callable=PropertyMock
                ) as mock_wxdai:
                    mock_wxdai.return_value = False
                    with patch.object(
                        type(behaviour),
                        "synchronized_data",
                        new_callable=PropertyMock,
                    ) as mock_sd:
                        mock_sd.return_value = MagicMock(is_policy_set=False)

                        gen = behaviour.async_act()
                        try:
                            while True:
                                next(gen)
                        except StopIteration:
                            pass

        assert len(payloads_sent) >= 1
        payload = payloads_sent[-1]
        assert isinstance(payload, BetPlacementPayload)
        assert payload.tx_hash == "0xsafetxhash"

    def test_async_act_insufficient_balance_can_exchange(self) -> None:
        """When token_balance < investment but can exchange, should build exchange tx."""
        behaviour, bm = _make_behaviour()

        payloads_sent = []

        behaviour.send_a2a_transaction = lambda payload: (  # type: ignore[method-assign]
            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
        )
        behaviour.wait_until_round_end = lambda: _noop_gen()  # type: ignore[func-returns-value, method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]
        behaviour.wallet_balance = 2000
        behaviour.token_balance = 50
        behaviour.check_balance = MagicMock()  # type: ignore[method-assign]

        wait_calls = []

        def mock_wait(cond) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition with sleep."""
            wait_calls.append(cond)  # type: ignore[no-untyped-def]
            yield

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]

        def mock_prepare() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock prepare safe tx."""
            yield  # type: ignore[no-untyped-def]
            return "0xexchangehash"

        behaviour._prepare_safe_tx = mock_prepare  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "investment_amount", new_callable=PropertyMock
            ) as mock_inv:
                mock_inv.return_value = 100
                with patch.object(
                    type(behaviour), "is_wxdai", new_callable=PropertyMock
                ) as mock_wxdai:
                    mock_wxdai.return_value = True
                    with patch.object(
                        type(behaviour), "w_xdai_deficit", new_callable=PropertyMock
                    ) as mock_deficit:
                        mock_deficit.return_value = 50
                        with patch.object(
                            type(behaviour),
                            "synchronized_data",
                            new_callable=PropertyMock,
                        ) as mock_sd:
                            mock_sd.return_value = MagicMock(is_policy_set=False)

                            gen = behaviour.async_act()
                            try:
                                while True:
                                    next(gen)
                            except StopIteration:
                                pass

        assert len(payloads_sent) >= 1

    def test_async_act_insufficient_balance_no_exchange(self) -> None:
        """When token_balance < investment and cannot exchange, should send None tx."""
        behaviour, bm = _make_behaviour()

        payloads_sent = []

        behaviour.send_a2a_transaction = lambda payload: (  # type: ignore[method-assign]
            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
        )
        behaviour.wait_until_round_end = lambda: _noop_gen()  # type: ignore[func-returns-value, method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]
        behaviour.wallet_balance = 10
        behaviour.token_balance = 5
        behaviour.check_balance = MagicMock()  # type: ignore[method-assign]

        behaviour.wait_for_condition_with_sleep = lambda cond: _noop_gen()  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "investment_amount", new_callable=PropertyMock
            ) as mock_inv:
                mock_inv.return_value = 100
                with patch.object(
                    type(behaviour), "is_wxdai", new_callable=PropertyMock
                ) as mock_wxdai:
                    mock_wxdai.return_value = False

                    gen = behaviour.async_act()
                    try:
                        while True:
                            next(gen)
                    except StopIteration:
                        pass

        assert len(payloads_sent) >= 1
        payload = payloads_sent[-1]
        assert payload.tx_submitter is None
        assert payload.tx_hash is None
