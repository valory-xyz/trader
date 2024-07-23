from unittest.mock import MagicMock

import pytest
from aea.configurations.data_types import PublicId

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
from packages.valory.skills.check_stop_trading_abci.handlers import ABCICheckStopTradingHandler, HttpHandler, \
    SigningHandler, LedgerApiHandler, ContractApiHandler, TendermintHandler, IpfsHandler


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
    ]
)
def test_import(handler, base_handler) -> None:
    """Test that the 'handlers.py' of the CheckStopTradingAbci can be imported."""
    handler = handler(name="dummy_handler", skill_context=MagicMock(skill_id=PublicId.from_str("dummy/skill:0.1.0")))

    assert isinstance(handler, base_handler)

