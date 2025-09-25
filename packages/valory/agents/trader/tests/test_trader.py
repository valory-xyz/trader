# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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

"""Integration tests for the valory/trader agent."""

from pathlib import Path
from typing import Tuple

import pytest
from aea.configurations.data_types import PublicId
from aea_test_autonomy.base_test_classes.agents import (
    BaseTestEnd2EndExecution,
    RoundChecks,
)
from aea_test_autonomy.fixture_helpers import abci_host  # noqa: F401
from aea_test_autonomy.fixture_helpers import abci_port  # noqa: F401
from aea_test_autonomy.fixture_helpers import flask_tendermint  # noqa: F401
from aea_test_autonomy.fixture_helpers import ganache_addr  # noqa: F401
from aea_test_autonomy.fixture_helpers import ganache_configuration  # noqa: F401
from aea_test_autonomy.fixture_helpers import ganache_port  # noqa: F401
from aea_test_autonomy.fixture_helpers import ganache_scope_class  # noqa: F401
from aea_test_autonomy.fixture_helpers import ganache_scope_function  # noqa: F401
from aea_test_autonomy.fixture_helpers import hardhat_addr  # noqa: F401
from aea_test_autonomy.fixture_helpers import hardhat_port  # noqa: F401
from aea_test_autonomy.fixture_helpers import ipfs_daemon  # noqa: F401
from aea_test_autonomy.fixture_helpers import ipfs_domain  # noqa: F401
from aea_test_autonomy.fixture_helpers import key_pairs  # noqa: F401
from aea_test_autonomy.fixture_helpers import tendermint  # noqa: F401
from aea_test_autonomy.fixture_helpers import tendermint_port  # noqa: F401

from packages.valory.agents.trader.tests.helpers.docker import (
    DEFAULT_JSON_SERVER_ADDR as _DEFAULT_JSON_SERVER_ADDR,
)
from packages.valory.agents.trader.tests.helpers.docker import (
    DEFAULT_JSON_SERVER_PORT as _DEFAULT_JSON_SERVER_PORT,
)
from packages.valory.agents.trader.tests.helpers.fixtures import (  # noqa: F401
    UseHardHatTraderBaseTest,
    UseMockAPIDockerImageBaseTest,
    UseMechMockDockerImageBaseTest
)
from packages.valory.skills.registration_abci.rounds import RegistrationStartupRound
from packages.valory.skills.reset_pause_abci.rounds import ResetAndPauseRound

# TODO: add more round checks
HAPPY_PATH: Tuple[RoundChecks, ...] = (
    RoundChecks(RegistrationStartupRound.auto_round_id(), n_periods=1),
    # RoundChecks(ResetAndPauseRound.auto_round_id(), n_periods=2),
)

# TODO: add more string checks
# strict check log messages of the happy path
STRICT_CHECK_STRINGS = (
    "Starting AEA",
    # "Period end",
)
PACKAGES_DIR = Path(__file__).parent.parent.parent.parent.parent


MOCK_NETWORK_SUBGRAPH_URL = f"{_DEFAULT_JSON_SERVER_ADDR}/network_subgraph/"
MOCK_NETWORK_SUBGRAPH_PORT = _DEFAULT_JSON_SERVER_PORT

MOCK_NETWORK_OMEN_URL = f"{_DEFAULT_JSON_SERVER_ADDR}/omen_subgraph/"
MOCK_NETWORK_OMEN_PORT = _DEFAULT_JSON_SERVER_PORT

MOCK_DRAND_URL = f"{_DEFAULT_JSON_SERVER_ADDR}/randomness_api/"
MOCK_DRAND_PORT = _DEFAULT_JSON_SERVER_PORT


@pytest.mark.usefixtures("ipfs_daemon")
class BaseTestEnd2EndTraderNormalExecution(BaseTestEnd2EndExecution):
    """Base class for the trader service e2e tests."""

    agent_package = "valory/trader:0.1.0"
    skill_package = "valory/trader_abci:0.1.0"
    wait_to_finish = 300  # The test runs for 5 minutes
    strict_check_strings = STRICT_CHECK_STRINGS
    happy_path = HAPPY_PATH
    package_registry_src_rel = PACKAGES_DIR

    __models_prefix = f"vendor.valory.skills.{PublicId.from_str(skill_package).name}.models"
    __param_args_prefix = f"{__models_prefix}.params.args"
    __network_subgraph_args_prefix = f"{__models_prefix}.network_subgraph.args"
    __omen_subgraph_args_prefix = f"{__models_prefix}.omen_subgraph.args"
    __drand_args_prefix = f"{__models_prefix}.randomness_api.args"

    # Set param overrides
    extra_configs = [
        {
            "dotted_path": f"{__network_subgraph_args_prefix}.url",
            "value": f"{MOCK_NETWORK_SUBGRAPH_URL}:{MOCK_NETWORK_SUBGRAPH_PORT}/",
        },
        {
            "dotted_path": f"{__omen_subgraph_args_prefix}.url",
            "value": f"{MOCK_NETWORK_OMEN_URL}:{MOCK_NETWORK_OMEN_PORT}/",
        },
        {
            "dotted_path": f"{__drand_args_prefix}.url",
            "value": f"{MOCK_DRAND_URL}:{MOCK_DRAND_PORT}/",
        },
        {
            "dotted_path": f"{__param_args_prefix}.store_path",
            "value": "/tmp/",
        }
    ]

    # Set the http server port config
    http_server_port_config = {
        "dotted_path": "vendor.valory.connections.http_server.config.port",
        "value": 8000,
    }

    def _BaseTestEnd2End__set_extra_configs(self) -> None:
        """Set the current agent's extra config overrides that are skill specific."""
        for config in self.extra_configs:
            self.set_config(**config)

        self.set_config(**self.http_server_port_config)
        self.http_server_port_config["value"] += 1  # avoid collisions in multi-agent setups


@pytest.mark.e2e
@pytest.mark.parametrize("nb_nodes", (1,))
class TestEnd2EndTraderSingleAgent(
    BaseTestEnd2EndTraderNormalExecution,
    UseMockAPIDockerImageBaseTest,
    UseMechMockDockerImageBaseTest,
):
    """Test the trader with only one agent."""
