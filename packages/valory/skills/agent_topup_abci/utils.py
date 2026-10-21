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

"""Helpers shared by the top-up round and the `/funds-status` handler."""

from typing import Callable, Dict, Optional

from packages.valory.skills.funds_manager.models import (
    AgentTopUp,
    FundRequirements,
    TokenRequirement,
    TopUpAction,
)

GNOSIS_CHAIN_NAME = "gnosis"
WXDAI_ADDRESS = "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"

NO_TOPUP = AgentTopUp(
    action=TopUpAction.NONE, move=0, signer_deficit=None, safe_deficit=None
)

GetAgentTopUp = Callable[..., Dict[str, AgentTopUp]]


def get_safe_native_balance(
    funds: FundRequirements, chain_name: str, agent_address: str
) -> Optional[int]:
    """Return the Agent Safe native balance read on a chain, if any."""
    tokens = _get_safe_tokens(funds, chain_name, agent_address).values()
    native = next((token for token in tokens if token.is_native), None)
    return None if native is None else native.balance


def get_agent_topups(
    get_agent_topup: GetAgentTopUp, funds: FundRequirements, agent_address: str
) -> Dict[str, AgentTopUp]:
    """Apply the funds-manager top-up rule, counting Agent Safe wxDAI as native on Gnosis.

    :param get_agent_topup: the funds-manager `get_agent_topup` rule.
    :param funds: the status returned by funds-manager `get_funds_status()`.
    :param agent_address: the Agent Signer address.
    :return: the top-up decision per chain.
    """
    wxdai = _get_safe_tokens(funds, GNOSIS_CHAIN_NAME, agent_address).get(WXDAI_ADDRESS)
    safe_native_extra = {}
    if wxdai is not None and wxdai.balance is not None:
        safe_native_extra[GNOSIS_CHAIN_NAME] = wxdai.balance

    topups = get_agent_topup(funds, safe_native_extra=safe_native_extra)
    if wxdai is not None and wxdai.balance is None:
        # An unread balance never moves funds.
        topups[GNOSIS_CHAIN_NAME] = NO_TOPUP
    return topups


def _get_safe_tokens(
    funds: FundRequirements, chain_name: str, agent_address: str
) -> Dict[str, TokenRequirement]:
    """Return the Agent Safe token requirements on a chain, keyed by token address."""
    if chain_name not in funds:
        return {}
    # funds-manager tracks two accounts per chain: the Agent Signer and the Agent Safe.
    for address, account in funds[chain_name].accounts.items():
        if address != agent_address:
            return account.tokens
    return {}
