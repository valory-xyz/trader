# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
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
"""This module contains the behaviours for the 'funds_manager' skill."""
from typing import Generator, Optional, cast

from aea.skills.behaviours import TickerBehaviour
from w3multicall.multicall import W3Multicall
from web3 import Web3

from packages.valory.contracts.erc20.contract import ERC20
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.protocols.ledger_api import LedgerApiMessage
from packages.valory.skills.funds_manager.models import (
    AccountRequirements,
    ChainRequirements,
    Funds,
    Params,
    TokenRequest,
    TokenRequirement,
)


ERC20Custom = ERC20

CHAIN_NAME_TO_ID = {
    "ethereum": 1,
    "gnosis": 100,
}


ERC20_DECIMALS_ABI = "decimals()(uint8)"
NATIVE_BALANCE_ABI = "getEthBalance(address)(uint256)"
ERC20_BALANCE_ABI = "balanceOf(address)(uint256)"
NATIVE_DECIMALS = 18

MULTICALL_ADDR = "0xcA11bde05977b3631167028862bE2a173976CA11"

FIVE_MINUTES_IN_SECONDS = 300


class MonitorBehaviour(TickerBehaviour):
    """Send an ABCI query periodically."""

    def __init__(self, tick_interval=FIVE_MINUTES_IN_SECONDS, start_at=None, **kwargs):
        super().__init__(tick_interval, start_at, **kwargs)

    def setup(self) -> None:
        """Set up the behaviour."""

    def teardown(self) -> None:
        """Tear down the behaviour."""

    def act(self) -> None:
        """Do the action."""
        self.update_balances()

    def do_w3_multicall(self, rpc_url, calls):
        """Do a multicall using w3_multicall."""
        w3 = Web3(Web3.HTTPProvider(rpc_url))

        w3_multicall = W3Multicall(w3)
        for token_address, token_data, call in calls:
            w3_multicall.add(call)

        return w3_multicall.call()

    @property
    def params(self) -> Params:
        """Return the params."""
        return cast(Params, self.context.params)

    @property
    def shared_state_funds(self) -> Funds:
        """Return the funds from the shared state."""
        return cast(Funds, self.context.shared_state.get("funds", {}))

    @shared_state_funds.setter
    def shared_state_funds(self, value: dict) -> None:
        """Set the funds in the shared state."""
        self.context.shared_state["funds"] = value

    def update_balances(self) -> None:
        """Read the balances from the Safe and the agent's EOA."""

        self._ensure_funds()

        for (
            chain_name,
            chain_requirements,
        ) in self.shared_state_funds.fund_requirements.items():
            w3 = Web3(Web3.HTTPProvider(self.params.rpc_urls[chain_name]))

            self.shared_state_funds.funds_status[chain_name] = {}

            for (
                account_address,
                account_requirements,
            ) in chain_requirements.accounts.items():

                self.shared_state_funds.funds_status[chain_name][account_address] = {}
                calls = []
                decimals_calls = {}

                for (
                    token_address,
                    token_requirements,
                ) in account_requirements.tokens.items():
                    if token_requirements.is_native:
                        # Native tokens: prepare multicall for balance
                        calls.append(
                            (
                                token_address,
                                token_requirements,
                                W3Multicall.Call(
                                    MULTICALL_ADDR,
                                    NATIVE_BALANCE_ABI,
                                    [account_address],
                                ),
                                NATIVE_DECIMALS,
                            )
                        )
                    else:
                        # ERC20: prepare multicall for balance
                        balance_call = W3Multicall.Call(
                            token_address,
                            ERC20_BALANCE_ABI,
                            [account_address],
                        )
                        # ERC20: prepare multicall for decimals
                        decimals_call = W3Multicall.Call(
                            token_address, ERC20_DECIMALS_ABI
                        )
                        calls.append(
                            (token_address, token_requirements, balance_call, None)
                        )
                        decimals_calls[token_address] = decimals_call

                # Execute multicall for balances
                web3_multicall = W3Multicall(w3)
                for _, _, call, _ in calls:
                    web3_multicall.add(call)

                balances = web3_multicall.call()

                # Execute multicall for decimals (only ERC20)
                web3_multicall_decimals = W3Multicall(w3)
                for dec_call in decimals_calls.values():
                    web3_multicall_decimals.add(dec_call)
                decimals_results = web3_multicall_decimals.call()

                # Map decimals back to token addresses
                decimal_results_map = {
                    token_address: value
                    for token_address, value in zip(
                        decimals_calls.keys(), decimals_results
                    )
                }
                decimal_results_map.update(
                    {
                        token_address: 18
                        for token_address, _, _, decimals in calls
                        if decimals is not None
                    }
                )

                # Write balances + deficits + decimals back
                for (token_address, token_requirements, _, _), balance in zip(
                    calls, balances
                ):
                    balance = int(balance or 0)
                    deficit = max(token_requirements.topup - balance, 0)
                    self.shared_state_funds.funds_status[chain_name][account_address][
                        token_address
                    ] = TokenRequest(
                        balance=balance,
                        deficit=deficit,
                        decimals=decimal_results_map[token_address],
                    )

    def _ensure_funds(self) -> None:
        if self.shared_state_funds:
            return

        self.shared_state_funds = Funds.from_dict(self.params.fund_requirements)
