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

"""This package contains the behaviours of the transaction settlement multiplexer."""

from abc import ABC
from typing import Generator, Set, Type

from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.tx_settlement_multiplexer_abci.rounds import (
    PostTxSettlementRound,
    SynchronizedData,
    TxSettlementMultiplexerAbciApp,
)


class PostTxSettlementBehaviour(BaseBehaviour, ABC):
    """
    The post transaction settlement behaviour.

    This behaviour should be executed after a tx is settled via the transaction_settlement_abci.
    """

    matching_round = PostTxSettlementRound

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return SynchronizedData(super().synchronized_data.db)

    def async_act(self) -> Generator:
        """Simply log that a tx is settled and wait for the round end."""
        msg = f"The transaction submitted by {self.synchronized_data.tx_submitter} was successfully settled."
        self.context.logger.info(msg)
        yield from self.wait_until_round_end()
        self.set_done()


class PostTxSettlementFullBehaviour(AbstractRoundBehaviour):
    """The post tx settlement full behaviour."""

    initial_behaviour_cls = PostTxSettlementBehaviour
    abci_app_cls = TxSettlementMultiplexerAbciApp
    behaviours: Set[Type[BaseBehaviour]] = {PostTxSettlementBehaviour}  # type: ignore
