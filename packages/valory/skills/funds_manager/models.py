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
from typing import Any, Dict, Optional

from aea.skills.base import Model
from typing import Dict
from pydantic import BaseModel, Field, constr, field_validator


EthAddress = constr(pattern=r"^0x[a-fA-F0-9]{40}$")


class TokenBalances(BaseModel):
    """Map token -> balance."""
    __root__: Dict[EthAddress, Optional[int]]

    @field_validator("__root__", mode="before")
    @classmethod
    def check_balances(cls, v: Dict[str, int]):
        """Check that all balances are non-negative."""
        for token, balance in v.items():
            if balance < 0:
                raise ValueError(f"Negative balance for token {token}")
        return v


class ChainAddresses(BaseModel):
    """Map addresses -> tokens -> balances."""
    __root__: Dict[EthAddress, TokenBalances]


class FundsConfig(BaseModel):
    """Map chain -> addresses -> tokens -> balances."""
    __root__: Dict[str, ChainAddresses]


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

        fund_requirements = self.context.params.fund_requirements
        initial_data = {chain_name: {} for chain_name in fund_requirements.keys()}

        # Replace "agent" and "safe" keys with corresponding addresses
        for chain_name, chain_info in fund_requirements.items():
            for account_name, account_requirements in chain_info.items():

                initial_token_balances = {
                    token: None for token in account_requirements.keys()
                }

                if account_name == "agent":
                    initial_data[chain_name][self.context.agent_address] = initial_token_balances
                elif account_name == "safe":
                    initial_data[chain_name][self.context.params.safe_address] = initial_token_balances

        self.funds = FundsConfig.model_validate(initial_data)
        self.fund_requirements = {}
