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

from logging import Logger
from typing import Callable, Dict, Optional

from packages.valory.skills.funds_manager.models import (
    AgentTopUp,
    FundRequirements,
    TokenRequirement,
)

GNOSIS_CHAIN_NAME = "gnosis"
WXDAI_ADDRESS = "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"
# False once a top-up fails, True again once a top-up transfer settles.
# Unset (e.g. at startup) counts as True: a pending top-up the Agent Safe covers raises no alert.
TOPUP_SUCCEEDED_KEY = "agent_topup_succeeded"

NO_TOPUP = AgentTopUp(move=0, signer_deficit=None, safe_deficit=None)

GetAgentTopUp = Callable[..., Dict[str, AgentTopUp]]


def get_safe_native_balance(
    funds: FundRequirements, chain_name: str, agent_address: str
) -> Optional[int]:
    """Return the Agent Safe native balance read on a chain, if any."""
    native = _get_native(_get_tokens(funds, chain_name, agent_address, is_signer=False))
    return None if native is None else native.balance


def native_balances_read(
    funds: FundRequirements, chain_name: str, agent_address: str
) -> bool:
    """Return whether the Agent Signer and Agent Safe native balances were read on a chain."""
    for is_signer in (True, False):
        native = _get_native(_get_tokens(funds, chain_name, agent_address, is_signer))
        if native is not None and native.balance is None:
            return False
    return True


def get_signer_native_deficit(
    funds: FundRequirements, chain_name: str, agent_address: str
) -> Optional[int]:
    """Return the Agent Signer native deficit read on a chain, if any."""
    native = _get_native(_get_tokens(funds, chain_name, agent_address, is_signer=True))
    return None if native is None else native.deficit


def get_agent_topups(
    get_agent_topup: GetAgentTopUp,
    funds: FundRequirements,
    agent_address: str,
    min_signer_balance: int,
    logger: Logger,
) -> Dict[str, AgentTopUp]:
    """Apply the funds-manager top-up rule, counting Agent Safe wxDAI as native on Gnosis.

    :param get_agent_topup: the funds-manager `get_agent_topup` rule.
    :param funds: the status returned by funds-manager `get_funds_status()`.
    :param agent_address: the Agent Signer address.
    :param min_signer_balance: the Agent Signer balance below which nothing is moved.
    :param logger: the logger.
    :return: the top-up decision per chain.
    """
    wxdai = _get_tokens(funds, GNOSIS_CHAIN_NAME, agent_address, is_signer=False).get(
        WXDAI_ADDRESS
    )
    safe_native_extra = {}
    if wxdai is not None and wxdai.balance is not None:
        safe_native_extra[GNOSIS_CHAIN_NAME] = wxdai.balance

    topups = get_agent_topup(funds, safe_native_extra=safe_native_extra)
    if wxdai is not None and wxdai.balance is None:
        # An unread balance never moves funds.
        topups[GNOSIS_CHAIN_NAME] = NO_TOPUP
    for chain_name in topups:
        signer = _get_native(
            _get_tokens(funds, chain_name, agent_address, is_signer=True)
        )
        if signer is None:
            continue
        if signer.balance is None:
            logger.warning(
                f"Agent Signer top-up skipped on {chain_name}: its balance was not read."
            )
            topups[chain_name] = NO_TOPUP
        elif signer.balance < min_signer_balance:
            # The tx settlement would wait for a refill before sending the top-up.
            if topups[chain_name].move > 0:
                logger.warning(
                    f"Agent Signer top-up skipped on {chain_name}: its balance "
                    f"{signer.balance} wei is below the {min_signer_balance} wei "
                    "the tx settlement needs."
                )
            topups[chain_name] = NO_TOPUP
    return topups


def _get_tokens(
    funds: FundRequirements, chain_name: str, agent_address: str, is_signer: bool
) -> Dict[str, TokenRequirement]:
    """Return the Agent Signer or Agent Safe token requirements on a chain, keyed by token address."""
    if chain_name not in funds:
        return {}
    # funds-manager tracks two accounts per chain: the Agent Signer and the Agent Safe.
    for address, account in funds[chain_name].accounts.items():
        if (address == agent_address) == is_signer:
            return account.tokens
    return {}


def _get_native(tokens: Dict[str, TokenRequirement]) -> Optional[TokenRequirement]:
    """Return the native token requirement, if tracked."""
    return next((token for token in tokens.values() if token.is_native), None)
