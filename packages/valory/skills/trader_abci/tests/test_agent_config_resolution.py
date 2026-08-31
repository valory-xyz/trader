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

"""Regression tests for the agent-level ``aea-config.yaml`` env-var wiring.

These guard against the class of bug introduced by renaming anonymous
``${type:default}`` placeholders to named ``${NAME:type:default}`` ones.
open-aea only applies the auto-derived component-path env var (e.g.
``SKILL_..._ARGS_URL``) for *anonymous* placeholders; a *named* placeholder
resolves solely against a bare env var of that exact name and otherwise
silently falls back to its default. When the chosen name does not match what
the runtime actually exports, the agent boots with the wrong (typically
Omen/gnosis-flavored or ``0x``) default.

The agent-runner path resolves ``aea-config.yaml`` (not ``service.yaml``), so
these mismatches only surface there. We resolve the real ``aea-config.yaml``
with open-aea's own resolver against a representative per-chain environment
and assert the result is internally consistent for both deployment flavors.
"""

import io
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest import mock

import pytest
from aea.helpers.env_vars import ENV_VARIABLE_RE, apply_env_variables_on_agent_config
from aea.helpers.yaml_utils import yaml_load_all

from packages.valory.skills.funds_manager.models import Params

# packages/valory/skills/trader_abci/tests/ -> packages/valory/
_VALORY_DIR = Path(__file__).resolve().parents[3]
AEA_CONFIG_PATH = _VALORY_DIR / "agents" / "trader" / "aea-config.yaml"

# The path-derived env var the middleware exports for the (anonymous) mechs
# marketplace subgraph url; open-aea derives this name from the config path.
MECHS_SUBGRAPH_PATH_KEY = "SKILL_TRADER_ABCI_MODELS_MECHS_SUBGRAPH_ARGS_URL"

SAFE = "0x318bF3775A8DE43ac803cfeDE45F62e256e3a7EC"

# A minimal, valid per-chain fund requirement (chain key is added per test).
_FUND_REQUIREMENT = {
    "agent": {
        "0x0000000000000000000000000000000000000000": {
            "topup": 100000000000000000,
            "threshold": 50000000000000000,
        }
    },
    "safe": {
        "0x0000000000000000000000000000000000000000": {
            "topup": 5000000000000000000,
            "threshold": 2500000000000000000,
        }
    },
}


def _resolve(env: Dict[str, str]) -> List[Dict[str, Any]]:
    """Resolve the real aea-config.yaml against ``env`` with open-aea's resolver.

    :param env: the environment variables to apply during resolution.
    :return: the agent config documents with env vars substituted.
    """
    docs = list(yaml_load_all(io.StringIO(AEA_CONFIG_PATH.read_text(encoding="utf-8"))))
    return apply_env_variables_on_agent_config(docs, env)


def _override(docs: List[Dict[str, Any]], component: str) -> Dict[str, Any]:
    """Return the resolved override doc whose public id contains ``component``.

    :param docs: the resolved agent config documents.
    :param component: substring to match against each override's public id.
    :return: the matching resolved override document.
    :raises AssertionError: if no override matches ``component``.
    """
    for doc in docs:
        if component in str(doc.get("public_id", "")):
            return doc
    raise AssertionError(f"override for {component!r} not found in aea-config.yaml")


@pytest.mark.parametrize(
    "chain, rpc_var, rpc_url",
    [
        ("polygon", "POLYGON_LEDGER_RPC", "https://polygon.example/rpc"),
        ("gnosis", "GNOSIS_LEDGER_RPC", "https://gnosis.example/rpc"),
    ],
)
def test_agent_config_resolves_consistently_per_chain(
    chain: str, rpc_var: str, rpc_url: str
) -> None:
    """The resolved agent config is chain-consistent for both flavors.

    Reproduces the failure modes fixed for the polymarket Safe,
    ``funds_manager.rpc_urls`` and the mechs marketplace subgraph: each must
    resolve to the active chain rather than a stale gnosis/``0x`` default.

    :param chain: the active deployment chain (e.g. ``polygon``/``gnosis``).
    :param rpc_var: the bare env var name carrying that chain's ledger RPC.
    :param rpc_url: the RPC url injected via ``rpc_var`` for the run.
    """
    marketplace_url = (
        f"https://api.subgraph.autonolas.tech/api/proxy/marketplace-{chain}"
    )
    env = {
        "SAFE_CONTRACT_ADDRESSES": json.dumps({chain: SAFE}),
        rpc_var: rpc_url,
        MECHS_SUBGRAPH_PATH_KEY: marketplace_url,
    }
    docs = _resolve(env)

    # funds_manager: rpc_urls / safe must cover the active chain with real values.
    fm_args = _override(docs, "funds_manager")["models"]["params"]["args"]
    assert fm_args["rpc_urls"].get(chain) == rpc_url
    assert fm_args["safe_contract_addresses"].get(chain) == SAFE

    # The exact invariant that crashed the agent runner: fund_requirements'
    # chains must be a subset of rpc_urls and safe_contract_addresses. Drive
    # the real validation (Params.__init__ -> _validate_chain_keys).
    Params(
        name="params",
        skill_context=mock.MagicMock(skill_id="valory/funds_manager:0.1.0"),
        fund_requirements={chain: _FUND_REQUIREMENT},
        rpc_urls=fm_args["rpc_urls"],
        safe_contract_addresses=fm_args["safe_contract_addresses"],
    )

    # polymarket_client Safe must resolve to the provided address, never "0x".
    pm_safe = _override(docs, "polymarket_client")["config"]["safe_contract_addresses"]
    assert pm_safe.get(chain) == SAFE

    # mechs marketplace subgraph must follow the active chain (anonymous
    # placeholder -> path-key), not the gnosis default baked into the yaml.
    mechs_url = _override(docs, "trader_abci")["models"]["mechs_subgraph"]["args"][
        "url"
    ]
    assert mechs_url == marketplace_url


SKILL_YAML_PATH = _VALORY_DIR / "skills" / "trader_abci" / "skill.yaml"

# Only these model args are exempt from open-aea's arg-path truncation.
_EXEMPT_ARGS = frozenset({"setup", "genesis_config"})


def _nested_model_arg_placeholders() -> List[Tuple[str, str]]:
    """Find placeholders nested below ``models.<model>.args.<arg>`` in the agent config.

    :return: ``(dotted path, placeholder)`` for every such leaf across all overrides.
    """
    docs = list(yaml_load_all(io.StringIO(AEA_CONFIG_PATH.read_text(encoding="utf-8"))))
    found: List[Tuple[str, str]] = []

    def walk(node: Any, path: List[str]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, [*path, str(key)])
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, [*path, str(i)])
        elif isinstance(node, str) and ENV_VARIABLE_RE.match(node):
            # models / <model> / args / <arg> / ...something deeper
            if (
                len(path) > 4
                and path[0] == "models"
                and path[2] == "args"
                and path[3] not in _EXEMPT_ARGS
            ):
                found.append((".".join(path), node))

    for doc in docs:
        walk({"models": doc.get("models", {})}, [])
    return found


def test_no_anonymous_placeholder_nested_under_a_model_arg() -> None:
    """A nested leaf must never use an anonymous ``${type:default}`` placeholder.

    open-aea collapses a dict-valued model arg into one env var whenever any key
    is not a bash identifier, and ``restrict_model_args`` truncates a nested
    leaf's path to that same name. An anonymous leaf falls back to that name and
    resolves to the whole parent dict as a string -- which is how every squid
    query started returning HTTP 400. A named placeholder never consults the
    fallback, and a plain literal is never substituted at all.
    """
    anonymous = [
        (path, placeholder)
        for path, placeholder in _nested_model_arg_placeholders()
        if ENV_VARIABLE_RE.match(placeholder).groups()[1] is None  # type: ignore[union-attr]
    ]
    assert not anonymous, f"anonymous nested placeholders found: {anonymous}"


def test_skill_declares_content_type_as_a_plain_literal() -> None:
    """The skill's own ``Content-Type`` defaults must stay unsubstitutable literals.

    The agent config deliberately does not override ``headers``, so these are the
    values the running agent actually sends.
    """
    docs = list(yaml_load_all(io.StringIO(SKILL_YAML_PATH.read_text(encoding="utf-8"))))
    declared = {
        model: cfg["args"]["headers"].get("Content-Type")
        for model, cfg in docs[0].get("models", {}).items()
        if isinstance(cfg.get("args"), dict) and cfg["args"].get("headers")
    }

    assert declared, "trader_abci declares no Content-Type headers"
    for model, value in declared.items():
        assert value == "application/json", f"{model} -> {value!r}"


def test_agent_config_does_not_override_headers() -> None:
    """No ``headers`` override should reappear in the agent config.

    Re-adding one buys nothing -- it can only restate the skill default -- while
    re-arming the collapsed-env-var trap the tests above guard against.
    """
    docs = list(yaml_load_all(io.StringIO(AEA_CONFIG_PATH.read_text(encoding="utf-8"))))
    overriding = [
        f"{doc.get('public_id')}:{model}"
        for doc in docs
        for model, cfg in doc.get("models", {}).items()
        if isinstance(cfg.get("args"), dict) and "headers" in cfg["args"]
    ]
    assert not overriding, f"headers override reintroduced for: {overriding}"
