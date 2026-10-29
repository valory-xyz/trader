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

"""Tests for the prestart-check command of the agent runner."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
import requests
from aea.cli.core import cli
from click.testing import CliRunner, Result
from prestart_check import (
    DATA_API_BASE_URL,
    DEFAULT_CLOB_HOST,
    GAMMA_API_BASE_URL,
    POLYMARKET_UNREACHABLE,
    is_reachable,
    prestart_check,
)

PACKAGES_DIR = Path(__file__).parents[1] / "packages" / "valory"
SERVICES_DIR = PACKAGES_DIR / "services"
POLYMARKET_CONNECTION_PY = (
    PACKAGES_DIR / "connections" / "polymarket_client" / "connection.py"
)
POLYSTRAT_DIR = SERVICES_DIR / "polymarket_trader"
OMENSTRAT_DIR = SERVICES_DIR / "trader_pearl"
POLYMARKET_HOSTS = [DEFAULT_CLOB_HOST, DATA_API_BASE_URL, GAMMA_API_BASE_URL]

cli.add_command(prestart_check)


def _run(
    service_dir: Path,
    unreachable: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
) -> "tuple[Result, List[str]]":
    """Run ``prestart-check`` the way the binary does, through the aea CLI."""
    probed: List[str] = []

    def head(url: str, **_: Any) -> MagicMock:
        probed.append(url)
        if url in (unreachable or []):
            raise requests.exceptions.ConnectionError("Connection reset by peer")
        return MagicMock(status_code=200)

    with patch("prestart_check.requests.head", side_effect=head):
        result = CliRunner().invoke(
            cli,
            ["prestart-check", "--service-dir", str(service_dir)],
            env=env,
        )
    return result, probed


def test_polystrat_passes_when_polymarket_answers() -> None:
    """Every Polymarket host answering passes the check."""
    result, probed = _run(POLYSTRAT_DIR)
    assert result.exit_code == 0
    assert json.loads(result.output) == {"status": "passed", "issues": []}
    assert sorted(probed) == sorted(POLYMARKET_HOSTS)


@pytest.mark.parametrize("host", POLYMARKET_HOSTS)
def test_polystrat_fails_when_a_polymarket_host_is_unreachable(host: str) -> None:
    """A Polymarket host that does not answer fails the check."""
    result, _ = _run(POLYSTRAT_DIR, unreachable=[host])
    assert result.exit_code == 1
    assert json.loads(result.output) == {
        "status": "failed",
        "issues": [POLYMARKET_UNREACHABLE],
    }


def test_omenstrat_passes_without_probing() -> None:
    """A service that does not trade on Polymarket probes nothing."""
    result, probed = _run(OMENSTRAT_DIR, unreachable=POLYMARKET_HOSTS)
    assert result.exit_code == 0
    assert json.loads(result.output) == {"status": "passed", "issues": []}
    assert probed == []


def test_env_turning_polymarket_off_passes_without_probing() -> None:
    """The start-time env overrides the service's Polymarket switch."""
    result, probed = _run(
        POLYSTRAT_DIR,
        unreachable=POLYMARKET_HOSTS,
        env={"IS_RUNNING_ON_POLYMARKET": "false"},
    )
    assert result.exit_code == 0
    assert probed == []


def test_env_clob_host_is_probed() -> None:
    """The start-time env overrides the CLOB host."""
    clob_host = "https://clob.example"
    result, probed = _run(
        POLYSTRAT_DIR,
        unreachable=[clob_host],
        env={"POLYMARKET_CLOB_HOST": clob_host},
    )
    assert result.exit_code == 1
    assert clob_host in probed
    assert DEFAULT_CLOB_HOST not in probed


def test_missing_service_dir_is_a_usage_error() -> None:
    """A missing service directory exits with neither 0 nor 1."""
    result, _ = _run(POLYSTRAT_DIR / "missing")
    assert result.exit_code not in (0, 1)


def test_help_lists_prestart_check() -> None:
    """Pearl detects the command from the runner's ``--help``."""
    result = CliRunner().invoke(cli, ["--help"])
    assert "prestart-check" in result.output


@pytest.mark.parametrize("status_code", [200, 403, 404, 503])
def test_any_http_answer_is_reachable(status_code: int) -> None:
    """A host that answers is reachable, whatever the status."""
    with patch(
        "prestart_check.requests.head", return_value=MagicMock(status_code=status_code)
    ):
        assert is_reachable(DEFAULT_CLOB_HOST)


@pytest.mark.parametrize(
    "error",
    [
        requests.exceptions.ConnectionError("Connection reset by peer"),
        requests.exceptions.Timeout("timed out"),
        requests.exceptions.SSLError("handshake failed"),
    ],
)
def test_no_answer_is_unreachable(error: Exception) -> None:
    """A connection error or timeout is unreachable."""
    with patch("prestart_check.requests.head", side_effect=error):
        assert not is_reachable(DEFAULT_CLOB_HOST)


def test_hosts_match_the_polymarket_connection() -> None:
    """The check probes the hosts the Polymarket connection calls."""
    source = POLYMARKET_CONNECTION_PY.read_text(encoding="utf-8")
    assert f'DATA_API_BASE_URL = "{DATA_API_BASE_URL}"' in source
    assert f'GAMMA_API_BASE_URL = "{GAMMA_API_BASE_URL}"' in source
