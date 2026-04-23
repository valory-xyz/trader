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

"""Tests for PolymarketWrapCollateralBehaviour and its round."""

from typing import Any, Generator
from unittest.mock import MagicMock, PropertyMock, patch

from eth_abi import encode
from eth_utils import keccak  # type: ignore[import-not-found]
from hexbytes import HexBytes

from packages.valory.skills.decision_maker_abci.behaviours.polymarket_wrap_collateral import (
    ERC20_APPROVE_SELECTOR,
    PolymarketWrapCollateralBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import (
    PolymarketWrapCollateralPayload,
)
from packages.valory.skills.decision_maker_abci.states.base import Event
from packages.valory.skills.decision_maker_abci.states.polymarket_wrap_collateral import (
    PolymarketWrapCollateralRound,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


SAFE_ADDR = "0x" + "11" * 20
USDC_E_ADDR = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
ONRAMP_ADDR = "0x93070a847efEf7F70739046A929D47a521F5B8ee"
AGENT_ADDR = "0x" + "22" * 20


def _return_gen(value: Any) -> Generator[None, None, Any]:
    """A generator that yields once then returns value."""
    yield
    return value


def _drain(gen: Generator) -> None:
    """Drive a generator to completion, ignoring yielded values."""
    try:
        while True:
            next(gen)
    except StopIteration:
        pass


def _make_behaviour(
    is_polymarket: bool = True,
    dust: int = 10_000,  # 0.01 USDC.e at 6 decimals
) -> PolymarketWrapCollateralBehaviour:
    """Build a PolymarketWrapCollateralBehaviour with the minimum attrs the tests touch."""
    behaviour = object.__new__(PolymarketWrapCollateralBehaviour)
    behaviour.multisend_batches = []
    behaviour.multisend_data = b""
    behaviour._safe_tx_hash = ""

    context = MagicMock()
    context.agent_address = AGENT_ADDR
    context.benchmark_tool.measure.return_value.local.return_value.__enter__ = (
        lambda _self: None
    )
    context.benchmark_tool.measure.return_value.local.return_value.__exit__ = (
        lambda _self, *_a: None
    )
    context.benchmark_tool.measure.return_value.consensus.return_value.__enter__ = (
        lambda _self: None
    )
    context.benchmark_tool.measure.return_value.consensus.return_value.__exit__ = (
        lambda _self, *_a: None
    )
    behaviour.__dict__["_context"] = context

    params = MagicMock()
    params.is_running_on_polymarket = is_polymarket
    params.polymarket_usdc_e_address = USDC_E_ADDR
    params.polymarket_collateral_onramp_address = ONRAMP_ADDR
    params.polymarket_usdc_e_wrap_dust_threshold = dust
    behaviour.__dict__["_params_proxy"] = params
    return behaviour


# ---------------------------------------------------------------------------
# _encode_erc20_approve parity
# ---------------------------------------------------------------------------


class TestEncodeErc20Approve:
    """Parity tests for the static _encode_erc20_approve helper."""

    @staticmethod
    def _expected(spender: str, amount: int) -> str:
        selector = bytes.fromhex(ERC20_APPROVE_SELECTOR[2:])
        encoded = encode(["address", "uint256"], [spender, amount])
        return "0x" + (selector + encoded).hex()

    def test_matches_eth_abi_encode_lowercase_address(self) -> None:
        """Output must equal eth_abi.encode for a plain lowercase address."""
        spender = "0x" + "ab" * 20
        amount = 12345
        assert PolymarketWrapCollateralBehaviour._encode_erc20_approve(
            spender, amount
        ) == self._expected(spender, amount)

    def test_matches_eth_abi_encode_checksum_address(self) -> None:
        """Output must equal eth_abi.encode for a mixed-case (checksum) address."""
        spender = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
        amount = 1
        assert PolymarketWrapCollateralBehaviour._encode_erc20_approve(
            spender, amount
        ) == self._expected(spender, amount)

    def test_matches_eth_abi_encode_zero_amount(self) -> None:
        """Output must equal eth_abi.encode for amount=0."""
        spender = "0x" + "11" * 20
        assert PolymarketWrapCollateralBehaviour._encode_erc20_approve(
            spender, 0
        ) == self._expected(spender, 0)

    def test_matches_eth_abi_encode_max_uint256(self) -> None:
        """Output must equal eth_abi.encode for amount=2**256-1."""
        spender = "0x" + "22" * 20
        amount = 2**256 - 1
        assert PolymarketWrapCollateralBehaviour._encode_erc20_approve(
            spender, amount
        ) == self._expected(spender, amount)


# ---------------------------------------------------------------------------
# _encode_onramp_wrap
# ---------------------------------------------------------------------------


class TestEncodeOnrampWrap:
    """Sanity checks for the onramp.wrap calldata encoder."""

    def test_selector_and_args(self) -> None:
        """Calldata must be keccak('wrap(address,address,uint256)')[:4] + abi-encoded args."""
        asset = "0x" + "aa" * 20
        to = "0x" + "bb" * 20
        amount = 42
        result = PolymarketWrapCollateralBehaviour._encode_onramp_wrap(
            asset, to, amount
        )
        expected_selector = keccak(text="wrap(address,address,uint256)")[:4]
        expected_args = encode(["address", "address", "uint256"], [asset, to, amount])
        assert result == "0x" + (expected_selector + expected_args).hex()


# ---------------------------------------------------------------------------
# async_act
# ---------------------------------------------------------------------------


class TestAsyncAct:
    """async_act orchestration: Omen short-circuit, payload construction."""

    @staticmethod
    def _wire(
        behaviour: PolymarketWrapCollateralBehaviour,
    ) -> list[PolymarketWrapCollateralPayload]:
        """Swap out network/consensus hooks so async_act can run synchronously."""
        captured: list[PolymarketWrapCollateralPayload] = []

        def capture_send_a2a(payload: PolymarketWrapCollateralPayload) -> Generator:
            captured.append(payload)
            yield

        behaviour.send_a2a_transaction = capture_send_a2a  # type: ignore[method-assign, assignment]
        behaviour.wait_until_round_end = lambda: (yield)  # type: ignore[method-assign, misc, assignment]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]
        return captured

    def _patch_params(self, behaviour: PolymarketWrapCollateralBehaviour) -> Any:
        """Patch the `params` property to return the MagicMock we stored on the behaviour."""
        proxy = behaviour.__dict__["_params_proxy"]
        return patch.object(
            type(behaviour),
            "params",
            new_callable=PropertyMock,
            return_value=proxy,
        )

    def test_omen_short_circuits_without_touching_chain(self) -> None:
        """When is_running_on_polymarket is False, async_act must NOT call _get_tx_hash."""
        behaviour = _make_behaviour(is_polymarket=False)
        captured = self._wire(behaviour)

        behaviour._get_tx_hash = MagicMock(  # type: ignore[method-assign]
            side_effect=AssertionError("_get_tx_hash must not be called on Omen")
        )

        with self._patch_params(behaviour):
            _drain(behaviour.async_act())

        assert len(captured) == 1
        payload = captured[0]
        assert payload.should_wrap is False
        assert payload.tx_submitter is None
        assert payload.tx_hash is None
        behaviour.set_done.assert_called_once()  # type: ignore[attr-defined]

    def test_polymarket_with_tx_hash_sets_should_wrap_true(self) -> None:
        """When _get_tx_hash returns a hash, payload must set should_wrap=True."""
        behaviour = _make_behaviour(is_polymarket=True)
        captured = self._wire(behaviour)

        behaviour._get_tx_hash = lambda: _return_gen("0xdeadbeef")  # type: ignore[method-assign]

        with self._patch_params(behaviour):
            _drain(behaviour.async_act())

        assert len(captured) == 1
        payload = captured[0]
        assert payload.should_wrap is True
        assert payload.tx_hash == "0xdeadbeef"
        # tx_submitter is the round's auto id, not None.
        assert payload.tx_submitter is not None

    def test_polymarket_without_tx_hash_sets_should_wrap_false(self) -> None:
        """When _get_tx_hash returns None (dust/read-fail), payload must set should_wrap=False."""
        behaviour = _make_behaviour(is_polymarket=True)
        captured = self._wire(behaviour)

        behaviour._get_tx_hash = lambda: _return_gen(None)  # type: ignore[method-assign]

        with self._patch_params(behaviour):
            _drain(behaviour.async_act())

        assert len(captured) == 1
        payload = captured[0]
        assert payload.should_wrap is False
        assert payload.tx_hash is None
        assert payload.tx_submitter is None


# ---------------------------------------------------------------------------
# _get_tx_hash
# ---------------------------------------------------------------------------


class TestGetTxHash:
    """Balance-read branch, dust skip, multisend build, and batch contents."""

    @staticmethod
    def _patch_synced_data(
        behaviour: PolymarketWrapCollateralBehaviour, safe_address: str
    ) -> Any:
        synced = MagicMock()
        synced.safe_contract_address = safe_address
        return patch.object(
            type(behaviour),
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=synced,
        )

    @staticmethod
    def _patch_params(behaviour: PolymarketWrapCollateralBehaviour) -> Any:
        proxy = behaviour.__dict__["_params_proxy"]
        return patch.object(
            type(behaviour),
            "params",
            new_callable=PropertyMock,
            return_value=proxy,
        )

    def test_returns_none_when_balance_read_fails(self) -> None:
        """If _get_usdc_e_balance returns None, _get_tx_hash returns None and logs error."""
        behaviour = _make_behaviour()
        behaviour._get_usdc_e_balance = lambda _safe: _return_gen(None)  # type: ignore[method-assign, assignment]

        result = None
        with (
            self._patch_synced_data(behaviour, SAFE_ADDR),
            self._patch_params(behaviour),
        ):
            gen = behaviour._get_tx_hash()
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result is None
        # No multisend batches built for a read-failure.
        assert behaviour.multisend_batches == []

    def test_returns_none_when_balance_at_or_below_dust(self) -> None:
        """Balance == dust must skip the wrap (strictly-greater guard)."""
        behaviour = _make_behaviour(dust=10_000)
        behaviour._get_usdc_e_balance = lambda _safe: _return_gen(10_000)  # type: ignore[method-assign, assignment]

        result = None
        with (
            self._patch_synced_data(behaviour, SAFE_ADDR),
            self._patch_params(behaviour),
        ):
            gen = behaviour._get_tx_hash()
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result is None
        assert behaviour.multisend_batches == []

    def test_below_dust_skips_wrap(self) -> None:
        """Balance < dust must skip the wrap."""
        behaviour = _make_behaviour(dust=10_000)
        behaviour._get_usdc_e_balance = lambda _safe: _return_gen(9_999)  # type: ignore[method-assign, assignment]

        result = None
        with (
            self._patch_synced_data(behaviour, SAFE_ADDR),
            self._patch_params(behaviour),
        ):
            gen = behaviour._get_tx_hash()
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result is None
        assert behaviour.multisend_batches == []

    def test_success_builds_two_batch_multisend_with_correct_contents(self) -> None:
        """Above dust: two batches — approve(onramp, balance) and wrap(USDC.e, safe, balance)."""
        behaviour = _make_behaviour(dust=10_000)
        balance = 50_000_000  # 50 USDC.e
        behaviour._get_usdc_e_balance = lambda _safe: _return_gen(balance)  # type: ignore[method-assign, assignment]
        behaviour._build_multisend_data = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = lambda: _return_gen(True)  # type: ignore[method-assign]

        result = None
        with (
            self._patch_synced_data(behaviour, SAFE_ADDR),
            self._patch_params(behaviour),
            patch.object(
                type(behaviour),
                "tx_hex",
                new_callable=PropertyMock,
                return_value="0xsafeHash",
            ),
        ):
            gen = behaviour._get_tx_hash()
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result == "0xsafeHash"
        assert len(behaviour.multisend_batches) == 2

        approve_batch, wrap_batch = behaviour.multisend_batches
        # Approve targets USDC.e, pulls 'balance' to the onramp.
        assert approve_batch.to == USDC_E_ADDR
        assert approve_batch.value == 0
        expected_approve_data = HexBytes(
            PolymarketWrapCollateralBehaviour._encode_erc20_approve(
                ONRAMP_ADDR, balance
            )
        )
        assert approve_batch.data == expected_approve_data

        # Wrap targets the onramp, sends pUSD to the safe.
        assert wrap_batch.to == ONRAMP_ADDR
        assert wrap_batch.value == 0
        expected_wrap_data = HexBytes(
            PolymarketWrapCollateralBehaviour._encode_onramp_wrap(
                USDC_E_ADDR, SAFE_ADDR, balance
            )
        )
        assert wrap_batch.data == expected_wrap_data

    def test_returns_none_when_multisend_data_build_fails(self) -> None:
        """If _build_multisend_data fails, _get_tx_hash returns None."""
        behaviour = _make_behaviour(dust=10_000)
        behaviour._get_usdc_e_balance = lambda _safe: _return_gen(50_000_000)  # type: ignore[method-assign, assignment]
        behaviour._build_multisend_data = lambda: _return_gen(False)  # type: ignore[method-assign]

        result = None
        with (
            self._patch_synced_data(behaviour, SAFE_ADDR),
            self._patch_params(behaviour),
        ):
            gen = behaviour._get_tx_hash()
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result is None

    def test_returns_none_when_safe_tx_hash_build_fails(self) -> None:
        """If _build_multisend_safe_tx_hash fails, _get_tx_hash returns None."""
        behaviour = _make_behaviour(dust=10_000)
        behaviour._get_usdc_e_balance = lambda _safe: _return_gen(50_000_000)  # type: ignore[method-assign, assignment]
        behaviour._build_multisend_data = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = lambda: _return_gen(False)  # type: ignore[method-assign]

        result = None
        with (
            self._patch_synced_data(behaviour, SAFE_ADDR),
            self._patch_params(behaviour),
        ):
            gen = behaviour._get_tx_hash()
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result is None


# ---------------------------------------------------------------------------
# _get_usdc_e_balance
# ---------------------------------------------------------------------------


class TestGetUsdcEBalance:
    """Read path for the Safe's USDC.e balance via ERC20.check_balance."""

    @staticmethod
    def _patch_params(
        behaviour: PolymarketWrapCollateralBehaviour,
    ) -> Any:
        proxy = behaviour.__dict__["_params_proxy"]
        return patch.object(
            type(behaviour),
            "params",
            new_callable=PropertyMock,
            return_value=proxy,
        )

    @staticmethod
    def _run(behaviour: PolymarketWrapCollateralBehaviour, response: MagicMock) -> Any:
        behaviour.get_contract_api_response = lambda **_kw: _return_gen(response)  # type: ignore[method-assign]
        gen = behaviour._get_usdc_e_balance(SAFE_ADDR)
        try:
            while True:
                next(gen)
        except StopIteration as e:
            return e.value
        return None  # pragma: no cover

    def test_returns_int_balance_on_success(self) -> None:
        """RAW_TRANSACTION with a 'token' field must be coerced to int."""
        from packages.valory.protocols.contract_api import ContractApiMessage

        behaviour = _make_behaviour()
        response = MagicMock()
        response.performative = ContractApiMessage.Performative.RAW_TRANSACTION
        response.raw_transaction.body = {"token": "123456789"}  # nosec B105

        with self._patch_params(behaviour):
            result = self._run(behaviour, response)

        assert result == 123456789
        assert isinstance(result, int)

    def test_returns_none_on_wrong_performative(self) -> None:
        """Non-RAW_TRANSACTION performative (e.g. ERROR) returns None and logs."""
        from packages.valory.protocols.contract_api import ContractApiMessage

        behaviour = _make_behaviour()
        response = MagicMock()
        response.performative = ContractApiMessage.Performative.ERROR

        with self._patch_params(behaviour):
            result = self._run(behaviour, response)

        assert result is None
        behaviour.context.logger.error.assert_called_once()

    def test_returns_none_when_token_field_missing(self) -> None:
        """Missing 'token' field in the raw_transaction body returns None and logs."""
        from packages.valory.protocols.contract_api import ContractApiMessage

        behaviour = _make_behaviour()
        response = MagicMock()
        response.performative = ContractApiMessage.Performative.RAW_TRANSACTION
        response.raw_transaction.body = {}

        with self._patch_params(behaviour):
            result = self._run(behaviour, response)

        assert result is None
        behaviour.context.logger.error.assert_called_once()


# ---------------------------------------------------------------------------
# Round.end_block
# ---------------------------------------------------------------------------


class TestPolymarketWrapCollateralRound:
    """End-block event override: PREPARE_TX when should_wrap, DONE otherwise."""

    @staticmethod
    def _make_round() -> PolymarketWrapCollateralRound:
        return object.__new__(PolymarketWrapCollateralRound)

    def test_end_block_returns_none_when_super_returns_none(self) -> None:
        """If super().end_block() is None (no majority yet), propagate None."""
        round_ = self._make_round()
        with patch(
            "packages.valory.skills.decision_maker_abci.states."
            "polymarket_wrap_collateral.TxPreparationRound.end_block",
            return_value=None,
        ):
            result = round_.end_block()
        assert result is None

    def test_end_block_emits_prepare_tx_when_should_wrap_true(self) -> None:
        """should_wrap=True must map to Event.PREPARE_TX."""
        round_ = self._make_round()
        synced = MagicMock()
        with (
            patch(
                "packages.valory.skills.decision_maker_abci.states."
                "polymarket_wrap_collateral.TxPreparationRound.end_block",
                return_value=(synced, Event.DONE),
            ),
            patch.object(
                type(round_),
                "most_voted_payload_values",
                new_callable=PropertyMock,
                return_value=("submitter", "0xhash", False, True),
            ),
        ):
            result = round_.end_block()

        assert result is not None
        _, event = result
        assert event == Event.PREPARE_TX

    def test_end_block_emits_done_when_should_wrap_false(self) -> None:
        """should_wrap=False must map to Event.DONE even if super returned PREPARE_TX."""
        round_ = self._make_round()
        synced = MagicMock()
        with (
            patch(
                "packages.valory.skills.decision_maker_abci.states."
                "polymarket_wrap_collateral.TxPreparationRound.end_block",
                return_value=(synced, Event.PREPARE_TX),
            ),
            patch.object(
                type(round_),
                "most_voted_payload_values",
                new_callable=PropertyMock,
                return_value=("submitter", None, False, False),
            ),
        ):
            result = round_.end_block()

        assert result is not None
        _, event = result
        assert event == Event.DONE
