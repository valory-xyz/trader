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

"""Tests for PolymarketSwapUsdcBehaviour."""

import json
from unittest.mock import MagicMock, PropertyMock, patch

from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_swap import (
    ETHER_VALUE,
    HTTP_OK,
    INTEGRATOR,
    LIFI_QUOTE_URL,
    POLYGON_CHAIN_ID,
    PolymarketSwapUsdcBehaviour,
    SAFE_TX_GAS,
)
from packages.valory.skills.decision_maker_abci.payloads import PolymarketSwapPayload

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
    """Return a PolymarketSwapUsdcBehaviour with mocked dependencies."""
    behaviour = object.__new__(PolymarketSwapUsdcBehaviour)  # type: ignore[no-untyped-def]

    context = MagicMock()
    context.agent_address = "test_agent"
    behaviour.__dict__["_context"] = context

    return behaviour


class TestPolymarketSwapConstants:
    """Tests for module-level constants."""

    def test_safe_tx_gas(self) -> None:
        """SAFE_TX_GAS should be 0."""
        assert SAFE_TX_GAS == 0

    def test_ether_value(self) -> None:
        """ETHER_VALUE should be 0."""
        assert ETHER_VALUE == 0

    def test_polygon_chain_id(self) -> None:
        """POLYGON_CHAIN_ID should be 137."""
        assert POLYGON_CHAIN_ID == 137

    def test_lifi_quote_url(self) -> None:
        """LIFI_QUOTE_URL should be the LiFi API endpoint."""
        assert "li.quest" in LIFI_QUOTE_URL

    def test_http_ok(self) -> None:
        """HTTP_OK should contain 200."""
        assert 200 in HTTP_OK

    def test_integrator(self) -> None:
        """INTEGRATOR should be 'valory'."""
        assert INTEGRATOR == "valory"


class TestPolymarketSwapUsdcBehaviour:
    """Tests for PolymarketSwapUsdcBehaviour."""

    def test_async_act_not_on_polymarket(self) -> None:
        """When not running on Polymarket, should skip swap."""
        behaviour = _make_behaviour()

        payloads_sent = []

        behaviour.send_a2a_transaction = lambda payload: (  # type: ignore[method-assign]
            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
        )
        behaviour.set_done = MagicMock()  # type: ignore[func-returns-value, method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(is_running_on_polymarket=False)

            gen = behaviour.async_act()
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        assert len(payloads_sent) == 1
        payload = payloads_sent[0]
        assert isinstance(payload, PolymarketSwapPayload)
        assert payload.should_swap is False
        assert payload.tx_hash is None

    def test_async_act_on_polymarket_tx_hash_success(self) -> None:
        """When running on Polymarket and get_tx_hash succeeds, should send swap payload."""
        behaviour = _make_behaviour()

        payloads_sent = []

        behaviour.get_tx_hash = lambda: _return_gen("0xfinalhash")  # type: ignore[method-assign]
        behaviour.send_a2a_transaction = lambda payload: (  # type: ignore[method-assign]
            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
        )
        behaviour.wait_until_round_end = lambda: (yield)  # type: ignore[func-returns-value, method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(is_running_on_polymarket=True)

            gen = behaviour.async_act()
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        assert len(payloads_sent) == 1
        payload = payloads_sent[0]
        assert isinstance(payload, PolymarketSwapPayload)
        assert payload.should_swap is True
        assert payload.tx_hash == "0xfinalhash"
        behaviour.set_done.assert_called_once()

    def test_async_act_on_polymarket_tx_hash_none(self) -> None:
        """When running on Polymarket and get_tx_hash returns None, should send no-swap payload."""
        behaviour = _make_behaviour()

        payloads_sent = []

        behaviour.get_tx_hash = lambda: _return_gen(None)  # type: ignore[method-assign]
        behaviour.send_a2a_transaction = lambda payload: (  # type: ignore[method-assign]
            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
        )
        behaviour.wait_until_round_end = lambda: (yield)  # type: ignore[func-returns-value, method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(is_running_on_polymarket=True)

            gen = behaviour.async_act()
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        assert len(payloads_sent) == 1
        payload = payloads_sent[0]
        assert payload.should_swap is False
        assert payload.tx_submitter is None

    def test_get_balance_success(self) -> None:
        """_get_balance should return balance on success."""
        from packages.valory.protocols.ledger_api import LedgerApiMessage

        behaviour = _make_behaviour()

        response = MagicMock()
        response.performative = LedgerApiMessage.Performative.STATE
        response.state.body = {"get_balance_result": 5000}

        behaviour.get_ledger_api_response = lambda **kwargs: _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._get_balance("0xsafe")
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result == 5000

    def test_get_balance_failure(self) -> None:
        """_get_balance should return None on failure."""
        from packages.valory.protocols.ledger_api import LedgerApiMessage

        behaviour = _make_behaviour()

        response = MagicMock()
        response.performative = LedgerApiMessage.Performative.ERROR

        behaviour.get_ledger_api_response = lambda **kwargs: _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._get_balance("0xsafe")
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result is None

    def test_get_safe_tx_hash_success(self) -> None:
        """_get_safe_tx_hash should return tx hash on success."""
        behaviour = _make_behaviour()

        response = MagicMock()
        response.performative = ContractApiMessage.Performative.STATE
        response.state.body = {"tx_hash": "0xdeadbeef1234"}

        behaviour.get_contract_api_response = lambda **kwargs: _return_gen(response)  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(safe_contract_address="0xsafe")

            gen = behaviour._get_safe_tx_hash(to_address="0xto", data=b"\x00", value=0)
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        # Should strip 0x prefix
        assert result == "deadbeef1234"

    def test_get_safe_tx_hash_failure(self) -> None:
        """_get_safe_tx_hash should return None on failure."""
        behaviour = _make_behaviour()

        response = MagicMock()
        response.performative = ContractApiMessage.Performative.ERROR

        behaviour.get_contract_api_response = lambda **kwargs: _return_gen(response)  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(safe_contract_address="0xsafe")

            gen = behaviour._get_safe_tx_hash(to_address="0xto", data=b"\x00", value=0)
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result is None

    def test_get_tx_hash_balance_none(self) -> None:
        """get_tx_hash should return None when balance is None."""
        behaviour = _make_behaviour()

        behaviour._get_balance = lambda addr: _return_gen(None)  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(safe_contract_address="0xsafe")

            gen = behaviour.get_tx_hash()
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result is None

    def test_get_tx_hash_below_threshold(self) -> None:
        """get_tx_hash should return None when balance is below threshold."""
        behaviour = _make_behaviour()

        behaviour._get_balance = lambda addr: _return_gen(100)  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(safe_contract_address="0xsafe")
            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(pol_threshold_for_swap=200)

                gen = behaviour.get_tx_hash()
                result = None
                try:
                    while True:
                        next(gen)
                except StopIteration as e:
                    result = e.value

        assert result is None

    def test_get_tx_hash_full_success(self) -> None:
        """get_tx_hash should return tx payload data on full success."""
        behaviour = _make_behaviour()

        behaviour._get_balance = lambda addr: _return_gen(1000)  # type: ignore[method-assign]

        lifi_quote = {
            "transactionRequest": {
                "to": "0x1234567890123456789012345678901234567890",
                "data": "0xdeadbeef",
                "value": "0x64",
            }
        }
        behaviour._get_lifi_quote = lambda addr, amount: _return_gen(lifi_quote)  # type: ignore[method-assign]
        # safe_tx_hash must be exactly 64 hex chars (32 bytes)
        safe_hash = "a" * 64
        behaviour._get_safe_tx_hash = (  # type: ignore[method-assign]
            lambda to_address, data, value, safe_tx_gas, operation: _return_gen(
                safe_hash
            )
        )

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(safe_contract_address="0xsafe")
            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(pol_threshold_for_swap=100)

                gen = behaviour.get_tx_hash()
                result = None
                try:
                    while True:
                        next(gen)
                except StopIteration as e:
                    result = e.value

        assert result is not None

    def test_get_tx_hash_lifi_quote_none(self) -> None:
        """get_tx_hash should return None when LiFi quote fails."""
        behaviour = _make_behaviour()

        behaviour._get_balance = lambda addr: _return_gen(1000)  # type: ignore[method-assign]
        behaviour._get_lifi_quote = lambda addr, amount: _return_gen(None)  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(safe_contract_address="0xsafe")
            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(pol_threshold_for_swap=100)

                gen = behaviour.get_tx_hash()
                result = None
                try:
                    while True:
                        next(gen)
                except StopIteration as e:
                    result = e.value

        assert result is None

    def test_get_tx_hash_no_transaction_request(self) -> None:
        """get_tx_hash should return None when quote has no transactionRequest."""
        behaviour = _make_behaviour()

        behaviour._get_balance = lambda addr: _return_gen(1000)  # type: ignore[method-assign]
        behaviour._get_lifi_quote = lambda addr, amount: _return_gen({})  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(safe_contract_address="0xsafe")
            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(pol_threshold_for_swap=100)

                gen = behaviour.get_tx_hash()
                result = None
                try:
                    while True:
                        next(gen)
                except StopIteration as e:
                    result = e.value

        assert result is None

    def test_get_tx_hash_missing_lifi_fields(self) -> None:
        """get_tx_hash should return None when transactionRequest lacks required fields."""
        behaviour = _make_behaviour()

        behaviour._get_balance = lambda addr: _return_gen(1000)  # type: ignore[method-assign]
        lifi_quote = {"transactionRequest": {"to": None, "data": None}}
        behaviour._get_lifi_quote = lambda addr, amount: _return_gen(lifi_quote)  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(safe_contract_address="0xsafe")
            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(pol_threshold_for_swap=100)

                gen = behaviour.get_tx_hash()
                result = None
                try:
                    while True:
                        next(gen)
                except StopIteration as e:
                    result = e.value

        assert result is None

    def test_get_tx_hash_invalid_hex_data(self) -> None:
        """get_tx_hash should return None when transaction data is not valid hex."""
        behaviour = _make_behaviour()

        behaviour._get_balance = lambda addr: _return_gen(1000)  # type: ignore[method-assign]
        lifi_quote = {
            "transactionRequest": {
                "to": "0x1234567890123456789012345678901234567890",
                "data": "not_valid_hex_zzz",
                "value": 100,
            }
        }
        behaviour._get_lifi_quote = lambda addr, amount: _return_gen(lifi_quote)  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(safe_contract_address="0xsafe")
            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(pol_threshold_for_swap=100)

                gen = behaviour.get_tx_hash()
                result = None
                try:
                    while True:
                        next(gen)
                except StopIteration as e:
                    result = e.value

        assert result is None

    def test_get_tx_hash_safe_tx_hash_none(self) -> None:
        """get_tx_hash should return None when _get_safe_tx_hash returns None."""
        behaviour = _make_behaviour()

        behaviour._get_balance = lambda addr: _return_gen(1000)  # type: ignore[method-assign]
        lifi_quote = {
            "transactionRequest": {
                "to": "0x1234567890123456789012345678901234567890",
                "data": "0xdeadbeef",
                "value": 100,
            }
        }
        behaviour._get_lifi_quote = lambda addr, amount: _return_gen(lifi_quote)  # type: ignore[method-assign]
        behaviour._get_safe_tx_hash = (  # type: ignore[method-assign]
            lambda to_address, data, value, safe_tx_gas, operation: _return_gen(None)
        )

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(safe_contract_address="0xsafe")
            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(pol_threshold_for_swap=100)

                gen = behaviour.get_tx_hash()
                result = None
                try:
                    while True:
                        next(gen)
                except StopIteration as e:
                    result = e.value

        assert result is None

    def test_get_tx_hash_value_as_int(self) -> None:
        """get_tx_hash should handle value as integer (not string)."""
        behaviour = _make_behaviour()

        behaviour._get_balance = lambda addr: _return_gen(1000)  # type: ignore[method-assign]
        lifi_quote = {
            "transactionRequest": {
                "to": "0x1234567890123456789012345678901234567890",
                "data": "0xdeadbeef",
                "value": 100,
            }
        }
        behaviour._get_lifi_quote = lambda addr, amount: _return_gen(lifi_quote)  # type: ignore[method-assign]
        # safe_tx_hash must be exactly 64 hex chars (32 bytes)
        safe_hash_2 = "b" * 64
        behaviour._get_safe_tx_hash = (  # type: ignore[method-assign]
            lambda to_address, data, value, safe_tx_gas, operation: _return_gen(
                safe_hash_2
            )
        )

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(safe_contract_address="0xsafe")
            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(pol_threshold_for_swap=100)

                gen = behaviour.get_tx_hash()
                result = None
                try:
                    while True:
                        next(gen)
                except StopIteration as e:
                    result = e.value

        assert result is not None

    def test_get_lifi_quote_success(self) -> None:
        """_get_lifi_quote should return parsed quote on success."""
        behaviour = _make_behaviour()

        quote_data = {
            "transactionRequest": {
                "to": "0x1234567890123456789012345678901234567890",
                "data": "0xdata",
            }
        }
        response = MagicMock()
        response.status_code = 200
        response.body = json.dumps(quote_data).encode()

        behaviour.get_http_response = lambda **kwargs: _return_gen(response)  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(slippages_for_swap={"POL-USDC": 0.01})

            gen = behaviour._get_lifi_quote("0xsafe", 1000)
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result is not None
        assert "transactionRequest" in result

    def test_get_lifi_quote_failure(self) -> None:
        """_get_lifi_quote should return None on failure."""
        behaviour = _make_behaviour()

        response = MagicMock()
        response.status_code = 500
        response.body = b"error"

        behaviour.get_http_response = lambda **kwargs: _return_gen(response)  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(slippages_for_swap={"POL-USDC": 0.01})

            gen = behaviour._get_lifi_quote("0xsafe", 1000)
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result is None

    def test_get_lifi_quote_invalid_json(self) -> None:
        """_get_lifi_quote should return None on invalid JSON."""
        behaviour = _make_behaviour()

        response = MagicMock()
        response.status_code = 200
        response.body = b"not json"

        behaviour.get_http_response = lambda **kwargs: _return_gen(response)  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(slippages_for_swap={"POL-USDC": 0.01})

            gen = behaviour._get_lifi_quote("0xsafe", 1000)
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result is None
