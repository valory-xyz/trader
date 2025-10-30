#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2025 Valory AG
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

"""Propel"""

import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import dotenv  # type: ignore
import requests
import urllib3  # type: ignore
from propel_client.constants import (  # type: ignore  # pylint: disable=import-error
    PROPEL_SERVICE_BASE_URL,
)

# pylint: disable=import-error
from propel_client.cred_storage import CredentialStorage  # type: ignore
from propel_client.propel import (  # type: ignore  # pylint: disable=import-error
    HttpRequestError,
    PropelClient,
)


logger = logging.getLogger("propel")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


dotenv.load_dotenv(override=True)

HTTP_OK = 200
TRADER_SERVICE_NAME = "trader_pearl"
PROPEL_TRADER_PROD_KEY_IDXS = [
    int(x)
    for x in os.getenv(  # pylint: disable=E1101
        "PROPEL_TRADER_PROD_KEY_IDXS", ""
    ).split(",")
    if x
]

TRADER_VARIABLES_PROD = [
    "TRADER_ALL_PARTICIPANTS",
]


class Agent:
    """Agent"""

    def __init__(self, name: str, client: PropelClient):
        """Constructor"""
        self.name = name
        self.client = client

    def get(self) -> Dict:
        """Get the agent"""
        logger.info(f"Getting agent {self.name}")
        return self.client.agents_get(self.name)

    def restart(self) -> Dict:
        """Restart the agent"""
        logger.info(f"Restarting agent {self.name}")
        return self.client.agents_restart(self.name)

    def stop(self) -> Dict:
        """Stop the agent"""
        logger.info(f"Stopping agent {self.name}")
        return self.client.agents_stop(self.name)

    def get_agent_code(self) -> Optional[str]:
        """Get the agent code"""
        logger.info(f"Getting agent code for {self.name}")
        agent_status = self.get()
        tendermint_p2p_url = agent_status.get("tendermint_p2p_url", None)
        if not tendermint_p2p_url:
            return None

        agent_code = tendermint_p2p_url.split(".")[0].split("-")[-1]
        return agent_code

    def get_agent_state(self) -> Optional[str]:
        """Get the agent state"""
        logger.info(f"Getting status for agent {self.name}")
        data = self.get()
        return data.get("agent_state", None)

    def get_agent_health(self) -> Tuple[bool, Dict]:
        """Get the agent status"""
        logger.info(f"Checking status for agent {self.name}")
        agent_code = self.get_agent_code()
        healthcheck_url = (
            f"https://{agent_code}.agent.propel.autonolas.tech/healthcheck"
        )

        try:
            response = requests.get(healthcheck_url, verify=False)  # nosec
            if response.status_code != HTTP_OK:
                return False, {}
            response_json = response.json()
            is_healthy = response_json["is_transitioning_fast"]
            return is_healthy, response_json
        except Exception:  # pylint: disable=broad-except
            return False, {}

    def healthcheck(self) -> Tuple[bool, Optional[str]]:
        """Healthcheck the agent"""
        is_healthy, data = self.get_agent_health()
        period = data.get("period", None)
        return is_healthy, period

    def get_current_round(self) -> Optional[str]:
        """Get the current round"""
        _, status = self.get_agent_health()

        if "current_round" in status:
            return status["current_round"]

        if "rounds" not in status:
            return None

        if len(status["rounds"]) == 0:
            return None

        return status["rounds"][-1]


class Service:
    """Service"""

    def __init__(self, name: str, agents: List[str], client: PropelClient):
        """Constructor"""
        self.name = name
        self.client = client
        self.agents = {name: Agent(name, client) for name in agents}
        self.not_healthy_counter = 0
        self.last_notification = None
        self.last_restart = None

    def restart(self) -> None:
        """Restart the service"""
        logger.info(f"Restarting service {self.name}")
        for agent in self.agents.values():
            agent.restart()

    def stop(self) -> None:
        """Stop the service"""
        logger.info(f"Stopping service {self.name}")
        for agent in self.agents.values():
            agent.stop()

    def healthcheck(self) -> bool:
        """Healthcheck the service"""
        logger.info(f"Checking health for service {self.name}")
        alive_threshold = math.floor(len(self.agents) * 2 / 3) + 1
        alive_agents = 0
        for agent in self.agents.values():
            is_agent_healthy, _ = agent.healthcheck()
            if is_agent_healthy:
                alive_agents += 1
        is_service_healthy = alive_agents >= alive_threshold

        if not is_service_healthy:
            self.not_healthy_counter += 1
        else:
            self.not_healthy_counter = 0

        return is_service_healthy


class Propel:
    """Propel"""

    def __init__(self) -> None:
        """Constructor"""
        self.client = PropelClient(
            base_url=PROPEL_SERVICE_BASE_URL, credentials_storage=CredentialStorage()
        )
        self.login()

    def login(self) -> None:
        """Login"""
        self.client.login(
            username=os.getenv("PROPEL_USERNAME"),  # pylint: disable=E1101
            password=os.getenv("PROPEL_PASSWORD"),  # pylint: disable=E1101
        )

    def logout(self) -> None:
        """Logout"""
        self.client.logout()

    def deploy(  # pylint: disable=too-many-arguments,too-many-locals
        self,
        service_name: str,
        variables: List[str],
        service_ipfs_hash: str,
        number_of_agents: int,
        keys: List[int],
    ) -> None:
        """Deploy a service"""

        agent_names = [f"{service_name}_agent_{i}" for i in range(number_of_agents)]

        # Check if Agent is already deployed and stop it
        existing_agents = []
        for agent_name in agent_names:
            agent = None
            try:
                agent = self.client.agents_get(agent_name)
            except HttpRequestError:
                print(f"Agent {agent_name} does not exist on Propel")

            if agent:
                existing_agents.append(agent_name)

                # Stop the agent if needed
                if agent.get("agent_state", None) in ["STARTED", "ERROR"]:
                    print(f"Stopping agent {agent_name}...")
                    self.client.agents_stop(agent_name)

        # Wait for stop and delete
        for agent_name in existing_agents:
            # Await for the agent to stop
            while True:
                agent = self.client.agents_get(agent_name)

                if agent.get("agent_state", None) == "DEPLOYED":
                    break
                print(f"Waiting for agent {agent_name} to stop...")
                time.sleep(10)

            print(f"Agent {agent_name} is stopped")
            print(f"Deleting agent {agent_name}...")
            self.client.agents_delete(agent_name)

        # Create the agents
        for i, agent_name in enumerate(agent_names):
            print(f"Creating agent {agent_name}...")
            self.client.agents_create(
                key=keys[i],
                name=agent_name,
                service_ipfs_hash=service_ipfs_hash,
                ingress_enabled=True,
                variables=variables,
                tendermint_ingress_enabled=True,
            )

        # Wait for the agents to be deployed and start them
        for agent_name in agent_names:
            while True:
                agent = self.client.agents_get(agent_name)
                if agent.get("agent_state", None) == "DEPLOYED":
                    print(f"Agent {agent_name} is deployed")
                    break
                print(f"Waiting for agent {agent_name} to be deployed...")
                time.sleep(10)

        # Start the agents
        for agent_name in agent_names:
            print(f"Starting agent {agent_name}...")
            self.client.agents_restart(agent_name)

        # Wait for the agents to start
        for agent_name in agent_names:
            while True:
                agent = self.client.agents_get(agent_name)
                state = agent.get("agent_state", None)
                if state == "STARTED":
                    print(f"Agent {agent_name} is running")
                    break
                if state == "ERROR":
                    print(f"Agent {agent_name} has failed to run")
                    break
                print(f"Waiting for agent {agent_name} to start...")
                time.sleep(10)


def deploy_trader() -> None:
    """Deploy Trader"""

    # Load the service hash
    with open(Path("packages", "packages.json"), "r", encoding="utf-8") as f:
        packages = json.load(f)
        service_ipfs_hash = packages["dev"][
            f"service/valory/{TRADER_SERVICE_NAME}/0.1.0"
        ]

    propel = Propel()

    # Prod
    propel.deploy(
        TRADER_SERVICE_NAME,
        TRADER_VARIABLES_PROD,
        service_ipfs_hash,
        1,
        PROPEL_TRADER_PROD_KEY_IDXS,
    )


if __name__ == "__main__":
    deploy_trader()
