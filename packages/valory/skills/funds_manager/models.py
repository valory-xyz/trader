# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021 Valory AG
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

"""This module contains the model 'state' for the 'counter_client' skill."""
from typing import Any

from aea.skills.base import Model


NATIVE_ADDRESSES = ["0x0000000000000000000000000000000000000000", "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"]

class Params(Model):
    """Parameters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the parameters object."""
        super().__init__(*args, **kwargs)

        # Example:
        # fund_requirements = {
        #     "ethereum": {
        #         "agent": {
        #             "0x000000": 50
        #         },
        #         "safe": {
        #             "0x000000": 500,
        #             "0xToken1": 1000,
        #             "0xToken2": 2000
        #         }
        #     },
        #     "gnosis": {
        #         "agent": {
        #             "0x000000": 50
        #         },
        #         "safe": {
        #             "0xToken1": 100,
        #             "0xToken2": 200
        #         }
        #     }
        # }

        self.fund_requirements = kwargs.get("fund_requirements")


class State(Model):
    """Keep the current state."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the state."""
        super().__init__(*args, **kwargs)
        self.funds = self.initialize_funds(self.context.params.fund_requirements)

    def initialize_funds(self, fund_requirements: dict) -> dict:
        """Initialize funds"""

        funds = {}

        for chain_name, chain_info in fund_requirements.items():

            funds[chain_name] = {}

            for account_name, account_requirements in chain_info.items():

                account_address = self.context.agent_address if account_name == "agent" else self.context.params.safe_address

                funds[chain_name][account_address] = {}

                for token_address, balance_requirement in account_requirements.items():

                    funds[chain_name][account_address][token_address] = {
                        "requirement": balance_requirement,
                        "balance": None,
                        "deficit": None,
                        "is_native": token_address in NATIVE_ADDRESSES,
                    }

        return funds
