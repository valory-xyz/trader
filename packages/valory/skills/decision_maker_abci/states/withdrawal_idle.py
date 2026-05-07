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

"""Terminal idle round entered after withdrawal completes (D9).

Both venue branches (Polymarket / Omen) converge here. The agent process
stays alive — Tendermint keeps producing blocks — but the FSM does not
transition out. Restart is the one and only way out of withdrawal mode:
boot unconditionally clears the flag regardless of the persisted state, so
any restart resumes normal trading (D19). To retry a partial sweep, the
user re-arms via POST /api/v1/withdrawal after restarting.
"""

from abc import ABC

from packages.valory.skills.abstract_round_abci.base import DegenerateRound


class WithdrawalIdleRound(DegenerateRound, ABC):
    """Terminal halt round reached after withdrawal completes."""
