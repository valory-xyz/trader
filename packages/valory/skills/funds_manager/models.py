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

"""This module contains the model 'state' for the 'funds_manager' skill."""
from typing import Any, Dict

from aea.skills.base import Model
from pydantic import BaseModel


NATIVE_ADDRESSES = [
    "0x0000000000000000000000000000000000000000",
    "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
]


class TokenRequirement(BaseModel):
    """Balance requirements for a specific token in an account."""

    topup: int
    threshold: int
    is_native: bool


class TokenRequest(BaseModel):
    balance: int
    deficit: int
    decimals: int


class AccountRequirements(BaseModel):
    """All token requirements for a single account address."""

    tokens: Dict[str, TokenRequirement] = {}


class ChainRequirements(BaseModel):
    """All account requirements for a single chain."""

    accounts: Dict[str, AccountRequirements] = {}


class Funds(BaseModel):
    """Funds"""

    fund_requirements: Dict[str, ChainRequirements] = {}
    funds_status: Dict[str, Any] = {}

    @classmethod
    def from_dict(cls, fund_dict: Dict[str, Any]) -> "Funds":
        fund_requirements = {}
        for chain, accounts in fund_dict.items():
            chain_obj = {}
            for account, tokens in accounts.items():
                token_objs = {}
                for token_address, token_data in tokens.items():
                    is_native = token_address in NATIVE_ADDRESSES
                    token_objs[token_address] = TokenRequirement(
                        topup=token_data["topup"],
                        threshold=token_data["threshold"],
                        is_native=is_native,
                    )
                chain_obj[account] = AccountRequirements(tokens=token_objs)
            fund_requirements[chain] = ChainRequirements(accounts=chain_obj)
        return cls(fund_requirements=fund_requirements)

    def retrieve_fund_status_dict(self) -> Dict[str, Any]:
        """Get the fund requirements as a dictionary."""
        return self.model_dump()["funds_status"]


class Params(Model):
    """Parameters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the parameters' object."""
        print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! {kwargs.get('fund_requirements')=}")
        self.fund_requirements: Dict[str, Any] = kwargs.get("fund_requirements")
        self.rpc_urls: Dict[str, str] = kwargs.get("rpc_urls")
        self.safe_address: str = kwargs.get("safe_address")

        # self.fund_requirements = kwargs.get("fund_requirements")
        print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! {self.fund_requirements=}")

        super().__init__(*args, **kwargs)
