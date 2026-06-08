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

"""This module contains the Polymarket (CLOB v2) DepositWallet withdrawal top-up round."""

from packages.valory.skills.decision_maker_abci.states.base import Event
from packages.valory.skills.decision_maker_abci.states.polymarket_top_up import (
    PolymarketTopUpRound,
)


class PolymarketWithdrawTopUpRound(PolymarketTopUpRound):
    """Moves all sellable CTF positions from the Safe to the DepositWallet.

    Runs once before the withdrawal sell-loop so the loop's DW-funded FAK
    sells have the shares to sell. Reuses the top-up ``end_block`` (which
    emits the payload-carried event and persists the DepositWallet address):
      - CTF batch transfer Safe→DW built → ``Event.PREPARE_TX`` (settles, then
        returns to ``PolymarketWithdrawRound``).
      - Nothing sellable → ``Event.WITHDRAWAL_DONE`` (straight to
        ``WithdrawalIdleRound``; no tx settles).
      - Transient failure → ``Event.NONE`` (loops).
    """

    none_event = Event.NONE

    # fsm-specs: returns(PREPARE_TX, WITHDRAWAL_DONE, NONE)
