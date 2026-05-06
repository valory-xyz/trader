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
transition out. A deliberate restart (with `withdrawal_state == complete`)
is what triggers the boot auto-clear and resumes normal trading (D19).
"""

from abc import ABC

from packages.valory.skills.abstract_round_abci.base import DegenerateRound


class WithdrawalIdleRound(DegenerateRound, ABC):
    """Terminal halt round reached after withdrawal completes."""
