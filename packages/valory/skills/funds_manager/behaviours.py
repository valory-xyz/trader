# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2025 Valory AG
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

from abc import ABC
from typing import Optional, cast, Generator

from aea.skills.base import Behaviour
from aea.skills.behaviours import TickerBehaviour


CHAIN_NAME_TO_ID = {
    "ethereum": 1,
    "gnosis": 100,
}

class BaseBehaviour(Behaviour, ABC):
    """Abstract base behaviour for this skill."""


class MonitorBehaviour(TickerBehaviour, BaseBehaviour):
    """Send an ABCI query periodically."""

    def setup(self) -> None:
        """Set up the behaviour."""

    def teardown(self) -> None:
        """Tear down the behaviour."""

    def act(self) -> None:
        """Do the action."""
        yield from self.update_balances()

    def update_balances(self) -> Generator[None, None, None]:
        """Read the balances from the Safe and the agent's EOA."""
        for chain_name, chain_info in self.context.state.funds.items():
            for account_address, account_requirements in chain_info.items():
                for token_address, token_data in account_requirements.items():

                    # Read the balance
                    if token_data["is_native"]:
                        balance = yield from self.get_native_balance(
                            chain_name,
                            account_address,
                        )
                    else:
                        balance = yield from self.get_erc20_balance(
                            chain_name,
                            account_address,
                            token_address,
                        )

                    # Update the balance
                    self.context.state.funds[chain_name][account_address][
                        token_address
                    ]["balance"] = balance

                    # Calculate the deficit
                    deficit = token_data["required_balance"] - balance if balance < token_data["required_balance"] else 0
                    self.context.state.funds[chain_name][account_address][
                        token_address
                    ]["deficit"] = deficit

    def get_native_balance(self, chain_name, account_address) -> Generator[None, None, Optional[float]]:
        """Get the native balance"""

        # TODO: use the correct ledger api to get the native balance
        ledger_api_response = yield from self.get_ledger_api_response(
            performative=LedgerApiMessage.Performative.GET_STATE,
            ledger_callable="get_balance",
            account=account_address,
            chain_id=CHAIN_NAME_TO_ID[chain_name],
        )

        if ledger_api_response.performative != LedgerApiMessage.Performative.STATE:
            self.context.logger.error(
                f"Error while retrieving the native balance: {ledger_api_response}"
            )
            return None

        balance = cast(int, ledger_api_response.state.body["get_balance_result"])
        balance = balance / 10**18  # from wei

        self.context.logger.error(f"Got native balance: {balance}")

        return balance

    def get_erc20_balance(self, chain_name, account_address, token_address) -> Generator[None, None, Optional[float]]:
        """Get ERC20 balance"""

        # TODO: use the correct contract api to get the native balance
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=token_address,
            contract_id=str(ERC20Custom.contract_id),
            contract_callable="check_balance",
            account=account_address,
            chain_id=CHAIN_NAME_TO_ID[chain_name],
        )

        # Check that the response is what we expect
        if response_msg.performative != ContractApiMessage.Performative.RAW_TRANSACTION:
            self.context.logger.error(
                f"Error while retrieving the balance: {response_msg}"
            )
            return None

        balance = response_msg.raw_transaction.body.get("token", None)

        # Ensure that the balance is not None
        if balance is None:
            self.context.logger.error(
                f"Error while retrieving the balance:  {response_msg}"
            )
            return None

        balance = balance / 10**18  # from wei

        return balance
