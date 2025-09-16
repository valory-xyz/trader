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

import json
from abc import ABC
from typing import Dict, Optional, cast

from aea.skills.base import Behaviour
from aea.skills.behaviours import TickerBehaviour

from packages.valory.connections.http_client.connection import (  # pylint: disable=no-name-in-module,import-error
    PUBLIC_ID as HTTP_CLIENT_PUBLIC_ID,
)
from packages.valory.protocols.http import (
    HttpMessage,
)  # pylint: disable=no-name-in-module,import-error

# pylint: disable=no-name-in-module,import-error
from packages.valory.skills.counter_client.dialogues import HttpDialogues
from packages.valory.skills.counter_client.handlers import curdatetime


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
        self.update_balances()
        fund_requirements = self.build_fund_requirements()

        # Check if funding is required and if the Safe has enough funds
        if fund_requirements and self.check_safe_funds():
            self.fund_eoa_from_safe()

            # Update the fund requirements after funding
            self.update_balances()
            fund_requirements = self.build_fund_requirements()

        # This object is read when the funding endpoint is called
        self.context.state.fund_requirements = fund_requirements


    def update_balances(self) -> None:
        """Read the balances from the Safe and the agent's EOA."""
        for chain_name, chain_info in self.context.state.funds.__root__.items():
            for account_address, account_requirements in chain_info.items():
                for token_address, token_balance in account_requirements.items():
                    updated_token_balance = # TODO: read balance
                    token_balance = updated_token_balance

    def build_fund_requirements(self) -> Dict[str, Dict[str, Dict[str, int]]]:
        """Build the fund requirements from the config."""
        fund_requirements = {}
        for chain_name, chain_info in self.context.state.funds.__root__.items():
            for account_address, account_requirements in chain_info.__root__.items():
                for token_address, required_balance in account_requirements.__root__.items():
                    current_balance = (
                        self.context.state.funds.__root__
                        .get(chain_name, {})
                        .get(account_address, {})
                        .get(token_address, 0)
                    )
                    deficit = required_balance - current_balance
                    if deficit > 0:
                        fund_requirements.setdefault(chain_name, {}).setdefault(
                            account_address, {}
                        )[token_address] = deficit
        return fund_requirements


    def check_safe_funds(self) -> None:
        """Check if the Safe has enough funds to cover the agent's requirements."""
        # TODO: implement the logic to check if the Safe has enough funds to cover the agent's requirements


    def fund_eoa_from_safe(self) -> None:
        """Move funds from the Safe to the agent's account"""
        # TODO: implement the funding logic to send funds from the safe to the agent's EOA

