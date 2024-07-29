# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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
"""This module contains tests for the handlers for the check stop trading abci."""

from unittest.mock import MagicMock

import pytest
from aea.configurations.data_types import PublicId
from aea.skills.base import Handler

from packages.valory.skills.abstract_round_abci.handlers import ABCIRoundHandler
from packages.valory.skills.abstract_round_abci.handlers import (
    ContractApiHandler as BaseContractApiHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    HttpHandler as BaseHttpHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    IpfsHandler as BaseIpfsHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    LedgerApiHandler as BaseLedgerApiHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    SigningHandler as BaseSigningHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    TendermintHandler as BaseTendermintHandler,
)
from packages.valory.skills.check_stop_trading_abci.handlers import (
    ABCICheckStopTradingHandler,
    ContractApiHandler,
    HttpHandler,
    IpfsHandler,
    LedgerApiHandler,
    SigningHandler,
    TendermintHandler,
)


@pytest.mark.parametrize(
    "handler, base_handler",
    [
        (ABCICheckStopTradingHandler, ABCIRoundHandler),
        (HttpHandler, BaseHttpHandler),
        (SigningHandler, BaseSigningHandler),
        (LedgerApiHandler, BaseLedgerApiHandler),
        (ContractApiHandler, BaseContractApiHandler),
        (TendermintHandler, BaseTendermintHandler),
        (IpfsHandler, BaseIpfsHandler),
    ],
)
def test_handler(handler: Handler, base_handler: Handler) -> None:
    """Test that the 'handlers.py' of the CheckStopTradingAbci can be imported."""
    handler = handler(
        name="dummy_handler",
        skill_context=MagicMock(skill_id=PublicId.from_str("dummy/skill:0.1.0")),
    )

    assert isinstance(handler, base_handler)
