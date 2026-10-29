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

"""The checks Pearl runs before starting the service: ``agent_runner prestart-check``."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Mapping

import click
import requests
import yaml
from aea.helpers.env_vars import apply_env_variables

POLYMARKET_CONNECTION = "valory/polymarket_client"
DEFAULT_CLOB_HOST = "https://clob.polymarket.com"
# The hosts the Polymarket connection calls besides the CLOB.
DATA_API_BASE_URL = "https://data-api.polymarket.com"
GAMMA_API_BASE_URL = "https://gamma-api.polymarket.com"
PROBE_TIMEOUT = 10  # seconds, per host; the hosts are probed in parallel

POLYMARKET_UNREACHABLE = {
    "code": "polymarket_unreachable",
    "title": "Can't reach Polymarket",
    "description": (
        "Polystrat can't connect to Polymarket's trading service from this "
        "network, so it couldn't place any bets. Start the agent again once "
        "Polymarket is reachable from this network."
    ),
}


def polymarket_hosts(service_dir: Path, env: Mapping[str, str]) -> List[str]:
    """Return the Polymarket hosts the service calls; none when it trades elsewhere.

    :param service_dir: the directory of the service package.
    :param env: the environment variables the service is started with.
    :return: the hosts to probe.
    """
    service_yaml = service_dir / "service.yaml"
    with open(service_yaml, encoding="utf-8") as file:
        _service, *overrides = yaml.safe_load_all(file)
    for override in overrides:
        public_id = str(override.get("public_id", ""))
        if not public_id.startswith(f"{POLYMARKET_CONNECTION}:"):
            continue
        config: Dict[str, Any] = apply_env_variables(  # type: ignore[assignment]
            override.get("config", {}), env
        )
        if not config.get("is_running_on_polymarket"):
            return []
        clob_host = config.get("host") or DEFAULT_CLOB_HOST
        return [clob_host, DATA_API_BASE_URL, GAMMA_API_BASE_URL]
    return []


def is_reachable(url: str) -> bool:
    """Whether a host answers at all; any HTTP status counts as an answer.

    :param url: the host to probe.
    :return: whether the host answered.
    """
    try:
        requests.head(url, timeout=PROBE_TIMEOUT, allow_redirects=False)
    except requests.exceptions.RequestException:
        return False
    return True


def run_checks(service_dir: Path, env: Mapping[str, str]) -> Dict[str, Any]:
    """Run the checks and return their result.

    :param service_dir: the directory of the service package.
    :param env: the environment variables the service is started with.
    :return: the result, as the middleware reads it.
    """
    hosts = polymarket_hosts(service_dir, env)
    with ThreadPoolExecutor(max_workers=max(len(hosts), 1)) as executor:
        reachable = list(executor.map(is_reachable, hosts))
    if all(reachable):
        return {"status": "passed", "issues": []}
    return {"status": "failed", "issues": [POLYMARKET_UNREACHABLE]}


@click.command("prestart-check")
@click.option(
    "--service-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="The directory of the service package.",
)
@click.pass_context
def prestart_check(click_context: click.Context, service_dir: Path) -> None:
    """Check that this machine can run the service; prints the result as JSON.

    Exits 0 when the checks pass, 1 when they fail and 2 when they cannot run.

    :param click_context: the click context.
    :param service_dir: the directory of the service package.
    """
    try:
        result = run_checks(service_dir, os.environ)
    except (OSError, ValueError, yaml.YAMLError) as e:
        click.echo(f"Cannot read the service package: {e}", err=True)
        click_context.exit(2)
    click.echo(json.dumps(result))
    click_context.exit(0 if result["status"] == "passed" else 1)
