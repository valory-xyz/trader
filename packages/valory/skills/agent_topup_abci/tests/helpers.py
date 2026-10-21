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

"""Builders for funds-manager statuses and its real top-up rule."""

from typing import Dict, Optional
from unittest.mock import MagicMock

from packages.valory.skills.agent_topup_abci.utils import GetAgentTopUp, WXDAI_ADDRESS
from packages.valory.skills.funds_manager.behaviours import FundsManagerBehaviour
from packages.valory.skills.funds_manager.models import (
    AccountRequirements,
    ChainRequirements,
    FundRequirements,
    TokenRequirement,
)

AGENT = "0x1111111111111111111111111111111111111111"
SAFE = "0x2222222222222222222222222222222222222222"
NATIVE = "0x0000000000000000000000000000000000000000"
ETHER = 10**18


def native(
    balance: Optional[int],
    topup: int,
    threshold: int,
    min_tx_balance: Optional[int] = None,
) -> TokenRequirement:
    """A native token entry as `get_funds_status()` returns it."""
    deficit = None
    if balance is not None:
        deficit = max(topup - balance, 0) if balance < threshold else 0
    return TokenRequirement(
        topup=topup,
        threshold=threshold,
        is_native=True,
        min_tx_balance=min_tx_balance,
        balance=balance,
        deficit=deficit,
        decimals=18,
    )


def funds_status(
    chain: str,
    signer_balance: Optional[int],
    safe_balance: Optional[int],
    wxdai_balance: Optional[int] = None,
    track_wxdai: bool = False,
) -> FundRequirements:
    """A one-chain status: Agent Signer topup 2 / threshold 0.21, Agent Safe topup 10 / threshold 1."""
    safe_tokens: Dict[str, TokenRequirement] = {
        NATIVE: native(safe_balance, 10 * ETHER, ETHER)
    }
    if track_wxdai:
        safe_tokens[WXDAI_ADDRESS] = TokenRequirement(
            topup=0, threshold=0, is_native=False, balance=wxdai_balance, deficit=0
        )
    signer = native(signer_balance, 2 * ETHER, 21 * ETHER // 100, ETHER // 50)
    return FundRequirements(
        {
            chain: ChainRequirements(
                accounts={
                    AGENT: AccountRequirements(tokens={NATIVE: signer}),
                    SAFE: AccountRequirements(tokens=safe_tokens),
                }
            )
        }
    )


def real_topup_rule(chain: str) -> GetAgentTopUp:
    """The funds-manager `get_agent_topup`, bound to AGENT and SAFE."""
    behaviour = object.__new__(FundsManagerBehaviour)
    context = MagicMock(agent_address=AGENT)
    context.params.safe_contract_addresses = {chain: SAFE}
    behaviour._context = context  # pylint: disable=protected-access
    return behaviour.get_agent_topup
