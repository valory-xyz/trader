# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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

"""This module contains the base behaviour for the 'decision_maker_abci' skill."""

from abc import ABC
from typing import Generator, cast

from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.abstract_round_abci.behaviour_utils import BaseBehaviour
from packages.valory.skills.decision_maker_abci.models import DecisionMakerParams
from packages.valory.skills.decision_maker_abci.states.base import SynchronizedData


class DecisionMakerBaseBehaviour(BaseBehaviour, ABC):
    """Represents the base class for the decision-making FSM behaviour."""

    @property
    def params(self) -> DecisionMakerParams:
        """Return the params."""
        return cast(DecisionMakerParams, self.context.params)

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return SynchronizedData(super().synchronized_data.db)

    def finish_behaviour(self, payload: BaseTxPayload) -> Generator:
        """Finish the behaviour."""
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()
