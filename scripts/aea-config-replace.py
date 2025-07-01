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


"""Updates fetched agent with correct config"""
import os
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv


AGENT_NAME = "trader"

PATH_TO_VAR = {
    # Chains
    "config/ledger_apis/gnosis/address": "RPC_0",
    # Params
    "models/params/args/setup/all_participants": "ALL_PARTICIPANTS",
    "models/params/args/setup/safe_contract_address": "SAFE_CONTRACT_ADDRESS",
    "models/omen_subgraph/args/url": "OMEN_SUBGRAPH_URL",
    "models/params/args/prompt_template": "PROMPT_TEMPLATE",
    "models/params/args/store_path": "STORE_PATH",
    "models/benchmark_tool/args/log_dir": "BENCHMARKS_DIR",
    "models/params/args/strategies_kwargs": "STRATEGIES_KWARGS",
    "config/genai_api_key": "GENAI_API_KEY",
}

CONFIG_REGEX = r"\${.*?:(.*)}"


def find_and_replace(config, path, new_value):
    """Find and replace a variable"""

    # Find the correct section where this variable fits
    section_indexes = []
    for i, section in enumerate(config):
        value = section
        try:
            for part in path:
                value = value[part]
            section_indexes.append(i)
        except KeyError:
            continue

    if not section_indexes:
        raise ValueError(f"Could not update {path}")

    # To persist the changes in the config variable,
    # access iterating the path parts but the last part
    for section_index in section_indexes:
        sub_dic = config[section_index]
        for part in path[:-1]:
            sub_dic = sub_dic[part]

        # Now, get the whole string value
        old_str_value = sub_dic[path[-1]]

        # Extract the old variable value
        match = re.match(CONFIG_REGEX, old_str_value)
        old_var_value = match.groups()[0]

        # Replace the old variable with the secret value in the complete string
        new_str_value = old_str_value.replace(old_var_value, new_value)
        sub_dic[path[-1]] = new_str_value

    return config


def main() -> None:
    """Main"""
    load_dotenv()

    # Load the aea config
    with open(Path(AGENT_NAME, "aea-config.yaml"), "r", encoding="utf-8") as file:
        config = list(yaml.safe_load_all(file))

    # Search and replace all the secrets
    for path, var in PATH_TO_VAR.items():
        try:
            new_value = os.getenv(var)
            if new_value is None:
                print(f"Env var {var} is not set")
                continue
            config = find_and_replace(config, path.split("/"), new_value)
        except Exception as e:
            raise ValueError(f"Could not update {path}") from e

    # Dump the updated config
    with open(Path(AGENT_NAME, "aea-config.yaml"), "w", encoding="utf-8") as file:
        yaml.dump_all(config, file, sort_keys=False)


if __name__ == "__main__":
    main()
