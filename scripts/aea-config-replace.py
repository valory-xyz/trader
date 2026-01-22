#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
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


"""Updates fetched agent with correct config"""

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv  # type: ignore


AGENT_NAME = "agent"

PATH_TO_VAR = {
    # Ledgers
    "config/ledger_apis/gnosis/address": "GNOSIS_LEDGER_RPC",
    "config/ledger_apis/polygon/address": "POLYGON_LEDGER_RPC",
    # Agent
    "models/params/args/setup/all_participants": "ALL_PARTICIPANTS",
    "models/params/args/setup/safe_contract_address": "SAFE_CONTRACT_ADDRESS",
    "models/params/args/safe_contract_addresses": "SAFE_CONTRACT_ADDRESSES",
    "models/params/args/store_path": "STORE_PATH",
    "models/benchmark_tool/args/log_dir": "BENCHMARKS_DIR",
    "models/params/args/reset_tendermint_after": "RESET_TENDERMINT_AFTER",
    # Subgraphs
    "models/omen_subgraph/args/url": "OMEN_SUBGRAPH_URL",
    "models/trades_subgraph/args/url": "TRADES_SUBGRAPH_URL",
    "models/conditional_tokens_subgraph/args/url": "CONDITIONAL_TOKENS_SUBGRAPH_URL",
    "models/network_subgraph/args/url": "NETWORK_SUBGRAPH_URL",
    "models/realitio_subgraph/args/url": "REALITIO_SUBGRAPH_URL",
    "models/gnosis_staking_subgraph/args/url": "GNOSIS_STAKING_SUBGRAPH",
    # Params
    "models/params/args/prompt_template": "PROMPT_TEMPLATE",
    "models/params/args/strategies_kwargs": "STRATEGIES_KWARGS",
    "models/params/args/mech_marketplace_config": "MECH_MARKETPLACE_CONFIG",
    "models/params/args/irrelevant_tools": "IRRELEVANT_TOOLS",
    "models/params/args/use_mech_marketplace": "USE_MECH_MARKETPLACE",
    "models/params/args/mech_contract_address": "MECH_CONTRACT_ADDRESS",
    "models/params/args/genai_api_key": "GENAI_API_KEY",
    "config/genai_api_key": "GENAI_API_KEY",
    "models/params/args/use_x402": "USE_X402",
    "config/use_x402": "USE_X402",
    "models/params/args/is_agent_performance_summary_enabled": "IS_AGENT_PERFORMANCE_SUMMARY_ENABLED",
    "models/params/args/default_chain_id": "DEFAULT_CHAIN_ID",
    "models/params/args/mech_chain_id": "MECH_CHAIN_ID",
    "config/genai_x402_server_base_url": "GENAI_X402_SERVER_BASE_URL",
    "models/params/args/fund_requirements": "FUND_REQUIREMENTS",
    "config/safe_contract_addresses/polygon": "SAFE_CONTRACT_ADDRESS",
    "models/params/args/is_running_on_polymarket": "IS_RUNNING_ON_POLYMARKET",
    "models/params/args/polymarket_builder_program_enabled": "POLYMARKET_BUILDER_PROGRAM_ENABLED",
    "config/polymarket_builder_program_enabled": "POLYMARKET_BUILDER_PROGRAM_ENABLED",
    "config/usdc_address": "USDC_ADDRESS",
    "config/ctf_address": "CTF_ADDRESS",
    "config/ctf_exchange": "CTF_EXCHANGE",
    "config/neg_risk_ctf_exchange": "NEG_RISK_CTF_EXCHANGE",
    "config/neg_risk_adapter": "NEG_RISK_ADAPTER",
    "models/params/args/bet_threshold": "BET_THRESHOLD",
    "models/params/args/polymarket_market_slug_to_bet_on": "POLYMARKET_MARKET_SLUG_TO_BET_ON",
    "models/params/args/complementary_service_metadata_address": "COMPLEMENTARY_SERVICE_METADATA_ADDRESS",
    "models/params/args/staking_contract_address": "STAKING_CONTRACT_ADDRESS",
}

CONFIG_REGEX = r"\${.*?:(.*)}"


def find_and_replace(config: list, path: list, new_value: Any) -> list[Any]:
    """Find and replace a variable"""

    # Find the correct section where this variable fits
    matching_section_indices = []
    for i, section in enumerate(config):
        value = section
        try:
            for part in path:
                value = value[part]
            matching_section_indices.append(i)
        except KeyError:
            continue

    if not matching_section_indices:
        raise KeyError(f"Path {path} not found in the config.")

    for section_index in matching_section_indices:
        # To persist the changes in the config variable,
        # access iterating the path parts but the last part
        sub_dic = config[section_index]
        for part in path[:-1]:
            sub_dic = sub_dic[part]

        # Now, get the whole string value
        old_str_value = sub_dic[path[-1]]

        # Extract the old variable value
        match = re.match(CONFIG_REGEX, old_str_value)
        old_var_value = match.groups()[0]  # type: ignore

        # Replace the old variable with the secret value in the complete string
        new_str_value = old_str_value.replace(old_var_value, new_value)
        sub_dic[path[-1]] = new_str_value

    return config


def main() -> None:
    """Main"""
    load_dotenv(override=True)

    # Load the aea config
    with open(Path(AGENT_NAME, "aea-config.yaml"), "r", encoding="utf-8") as file:
        config = list(yaml.safe_load_all(file))

    # Search and replace all the secrets
    for path, var in PATH_TO_VAR.items():
        try:
            new_value = os.getenv(var)  # pylint: disable=E1101
            if new_value is None:
                print(f"Environment variable {var} not found. Skipping...")
                continue
            config = find_and_replace(config, path.split("/"), new_value)
        except Exception as e:
            print(f"Exception while replacing {path}:\n{e}")
            raise ValueError from e

    # Dump the updated config
    with open(Path(AGENT_NAME, "aea-config.yaml"), "w", encoding="utf-8") as file:
        yaml.dump_all(config, file, sort_keys=False)


if __name__ == "__main__":
    main()
