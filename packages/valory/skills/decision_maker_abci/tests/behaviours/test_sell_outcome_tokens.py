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

"""Tests for SellOutcomeTokensBehaviour."""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from packages.valory.skills.decision_maker_abci.behaviours.sell_outcome_tokens import (
    SellOutcomeTokensBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import SellOutcomeTokensPayload
from packages.valory.skills.decision_maker_abci.states.sell_outcome_tokens import (
    SellOutcomeTokensRound,
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


def _make_behaviour():  # type: ignore[no-untyped-def]
    """Return a SellOutcomeTokensBehaviour with mocked dependencies."""
    behaviour = object.__new__(SellOutcomeTokensBehaviour)  # type: ignore[no-untyped-def]
    behaviour.sell_amount = 0

    context = MagicMock()
    context.agent_address = "test_agent"
    behaviour.__dict__["_context"] = context

    return behaviour


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSellOutcomeTokensBehaviour:
    """Tests for SellOutcomeTokensBehaviour."""

    def test_matching_round(self) -> None:
        """matching_round should be SellOutcomeTokensRound."""
        assert SellOutcomeTokensBehaviour.matching_round == SellOutcomeTokensRound

    def test_init(self) -> None:
        """__init__ should initialise correctly."""
        with patch(
            "packages.valory.skills.decision_maker_abci.behaviours.sell_outcome_tokens.DecisionMakerBaseBehaviour.__init__",
            return_value=None,
        ):
            behaviour = SellOutcomeTokensBehaviour(
                name="test", skill_context=MagicMock()
            )
            # __init__ runs super().__init__(**kwargs) - no additional attributes set
            assert behaviour is not None

    def test_async_act_benchmarking_mode(self) -> None:
        """In benchmarking mode, async_act should send payload with mocking_mode=True."""
        behaviour = _make_behaviour()

        payloads_sent = []

        behaviour.send_a2a_transaction = lambda payload: (  # type: ignore[method-assign]
            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
        )
        behaviour.wait_until_round_end = lambda: _noop_gen()  # type: ignore[func-returns-value, method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]
        behaviour.update_sell_transaction_information = MagicMock()  # type: ignore[method-assign]

        # After benchmarking finish_behaviour completes, code falls through.
        # Mock _prepare_safe_tx so the non-benchmarking path does not crash.
        behaviour._prepare_safe_tx = lambda: _return_gen(None)  # type: ignore[method-assign]
        behaviour.sell_amount = 0

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=True)
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(vote=None)

                gen = behaviour.async_act()
                # The non-benchmarking path raises ValueError when vote is None
                # so we catch that
                try:
                    while True:
                        next(gen)
                except (StopIteration, ValueError):
                    pass

        # First payload should be the benchmarking payload with mocking_mode=True
        assert len(payloads_sent) >= 1
        payload = payloads_sent[0]
        assert isinstance(payload, SellOutcomeTokensPayload)
        assert payload.mocking_mode is True
        behaviour.update_sell_transaction_information.assert_called_once()

    def test_build_approval_tx(self) -> None:
        """_build_approval_tx should delegate to build_approval_tx."""
        behaviour = _make_behaviour()

        def mock_build_approval_tx(amount, spender, token) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock build approval tx."""
            yield  # type: ignore[no-untyped-def]
            return True

        behaviour.build_approval_tx = mock_build_approval_tx  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "return_amount", new_callable=PropertyMock
        ) as mock_ra:
            mock_ra.return_value = 500
            with patch.object(
                type(behaviour),
                "market_maker_contract_address",
                new_callable=PropertyMock,
            ) as mock_mca:
                mock_mca.return_value = "0xmarket"
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        conditional_tokens_address="0xcondtokens"
                    )

                    gen = behaviour._build_approval_tx()
                    result = None
                    try:
                        while True:
                            next(gen)
                    except StopIteration as e:
                        result = e.value

                    assert result is True

    def test_prepare_safe_tx_returns_none_on_calc_failure(self) -> None:
        """_prepare_safe_tx should return None when _calc_sell_amount fails."""
        behaviour = _make_behaviour()

        def mock_wait(condition) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition."""
            yield  # type: ignore[no-untyped-def]

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]

        def mock_calc_sell() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock calc sell amount that fails."""
            yield  # type: ignore[no-untyped-def]
            return False

        behaviour._calc_sell_amount = mock_calc_sell  # type: ignore[method-assign]

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
        behaviour = _make_behaviour()

        def mock_wait(condition) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition."""
            yield  # type: ignore[no-untyped-def]

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]

        def mock_calc_sell() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock calc sell amount."""
            yield  # type: ignore[no-untyped-def]
            return True

        behaviour._calc_sell_amount = mock_calc_sell  # type: ignore[method-assign]

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
                    type(behaviour), "return_amount", new_callable=PropertyMock
                ) as mock_ra:
                    mock_ra.return_value = 500
                    with patch.object(
                        type(behaviour), "synchronized_data", new_callable=PropertyMock
                    ) as mock_sd:
                        mock_sd.return_value = MagicMock(confidence=0.8)
                        with patch.object(
                            type(behaviour), "tx_hex", new_callable=PropertyMock
                        ) as mock_tx:
                            mock_tx.return_value = "0xsellhash"

                            behaviour._collateral_amount_info = lambda x: f"{x} WEI"  # type: ignore[method-assign]

                            gen = behaviour._prepare_safe_tx()
                            result = None
                            try:
                                while True:
                                    next(gen)
                            except StopIteration as e:
                                result = e.value

        assert result == "0xsellhash"

    def test_async_act_normal_with_vote(self) -> None:
        """async_act should prepare tx and send payload when vote is set."""
        behaviour = _make_behaviour()
        behaviour.sell_amount = 1000

        payloads_sent = []

        behaviour.send_a2a_transaction = lambda payload: (  # type: ignore[method-assign]
            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
        )
        behaviour.wait_until_round_end = lambda: _noop_gen()  # type: ignore[func-returns-value, method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        behaviour._prepare_safe_tx = lambda: _return_gen("0xsafehash")  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.opposite_vote.return_value = 1

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(vote=0)
                with patch.object(
                    type(behaviour), "sampled_bet", new_callable=PropertyMock
                ) as mock_sb:
                    mock_sb.return_value = mock_bet
                    with patch.object(
                        type(behaviour), "outcome_index", new_callable=PropertyMock
                    ) as mock_oi:
                        mock_oi.return_value = 0

                        gen = behaviour.async_act()
                        try:
                            while True:
                                next(gen)
                        except StopIteration:
                            pass

        assert len(payloads_sent) >= 1
        payload = payloads_sent[-1]
        assert isinstance(payload, SellOutcomeTokensPayload)
        assert payload.tx_hash == "0xsafehash"
        assert payload.sell_amount == 1000
        assert payload.vote == 1

    def test_async_act_no_vote_raises(self) -> None:
        """async_act should raise ValueError when vote is None."""
        behaviour = _make_behaviour()
        behaviour.sell_amount = 0

        payloads_sent = []

        behaviour.send_a2a_transaction = lambda payload: (  # type: ignore[method-assign]
            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
        )
        behaviour.wait_until_round_end = lambda: _noop_gen()  # type: ignore[func-returns-value, method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        behaviour._prepare_safe_tx = lambda: _return_gen("0xsafehash")  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(vote=None)

                gen = behaviour.async_act()
                with pytest.raises(ValueError):  # type: ignore[name-defined]
                    while True:
                        next(gen)

    def test_async_act_sell_amount_zero(self) -> None:
        """When sell_amount is 0 (falsy), should send payload with None sell_amount."""
        behaviour = _make_behaviour()
        behaviour.sell_amount = 0

        payloads_sent = []

        behaviour.send_a2a_transaction = lambda payload: (  # type: ignore[method-assign]
            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
        )
        behaviour.wait_until_round_end = lambda: _noop_gen()  # type: ignore[func-returns-value, method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        behaviour._prepare_safe_tx = lambda: _return_gen("0xsafehash")  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(vote=0)

                gen = behaviour.async_act()
                try:
                    while True:
                        next(gen)
                except StopIteration:
                    pass

        assert len(payloads_sent) >= 1
        payload = payloads_sent[-1]
        # sell_amount is 0 which is falsy, so it won't be set
        assert payload.sell_amount is None
