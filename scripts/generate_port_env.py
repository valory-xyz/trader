#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025-2026 Valory AG
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

"""Generate environment variables for agent ports from aea-config.yaml.

This script analyzes an agent configuration file and generates environment
variables for all port-related settings. It uses the same logic as autonomy
deploy for generating variable names.

Usage:
    python generate_port_env.py [--config PATH] [--abci-port PORT]
                                [--rpc-port PORT] [--p2p-port PORT]
                                [--com-port PORT] [--http-port PORT]
"""

import argparse
import os
import re
import socket
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

import yaml

# Default port values
DEFAULT_PORTS = {
    "abci": 26658,
    "rpc": 26657,
    "p2p": 26656,
    "com": 8080,
    "http": 8716,
}

# Port increment step for finding free ports
PORT_INCREMENT = 10

# Starting port for dynamic allocation (when port=0)
DYNAMIC_PORT_START = 50000


def is_port_available(port: int) -> bool:
    """Check if a port is available."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def find_free_port(
    start_port: int, used_ports: Set[int], max_attempts: int = 100
) -> int:
    """Find a free port starting from start_port, avoiding used_ports."""
    port = start_port
    attempts = 0

    while attempts < max_attempts:
        # Skip if port is already used
        if port in used_ports:
            port += PORT_INCREMENT
            attempts += 1
            continue

        if is_port_available(port):
            return port
        port += PORT_INCREMENT
        attempts += 1

    raise RuntimeError(
        f"Could not find free port after {max_attempts} attempts starting from {start_port}"
    )


def extract_port_from_value(value: str) -> Optional[int]:
    """Extract port number from a string value."""
    if not isinstance(value, str):
        return None

    # Check for port in URLs like "http://localhost:26657"
    # Pattern for port in URL
    url_pattern = r":(\d+)(?:/|$)"
    match = re.search(url_pattern, value)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass

    # Pattern for standalone port or host:port
    port_pattern = r"(?:^|:)(\d+)$"
    match = re.search(port_pattern, value)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass

    return None


def find_port_settings_in_config(config: List[Dict]) -> Dict[str, Dict]:
    """Find all port-related settings in the configuration."""
    # pylint: disable=too-many-locals,too-many-nested-blocks,too-many-branches
    port_settings = {}

    for component in config:
        if not isinstance(component, dict):
            continue

        component_type = component.get("type")
        public_id = component.get("public_id")

        if not component_type or not public_id:
            continue

        component_name = (
            public_id.split(":")[0].split("/")[-1] if ":" in public_id else public_id
        )

        # Check config section
        config_section = component.get("config", {})
        if config_section:
            # Look for port settings in config
            for key, value in config_section.items():
                if isinstance(value, str) and (
                    "port" in key.lower() or "url" in key.lower()
                ):
                    port_value = extract_port_from_value(value)
                    if port_value:
                        env_var_name = f"{component_type.upper()}_{component_name.upper()}_CONFIG_{key.upper()}"  # pylint: disable=line-too-long
                        port_settings[env_var_name] = {
                            "value": value,
                            "port": port_value,
                            "component_type": component_type,
                            "component_name": component_name,
                            "config_key": key,
                        }

        # Check skill models and params
        if component_type == "skill":
            models = component.get("models", {})

            for model_name, model_data in models.items():
                if not isinstance(model_data, dict):
                    continue

                args = model_data.get("args", {})
                if not args:
                    continue

                # Look for port settings in args
                for arg_key, arg_value in args.items():
                    if isinstance(arg_value, str) and (
                        "tendermint" in arg_key.lower() or "url" in arg_key.lower()
                    ):
                        port_value = extract_port_from_value(arg_value)
                        if port_value:
                            env_var_name = f"SKILL_{component_name.upper()}_MODELS_{model_name.upper()}_PARAMS_ARGS_{arg_key.upper()}"  # pylint: disable=line-too-long
                            port_settings[env_var_name] = {
                                "value": arg_value,
                                "port": port_value,
                                "component_type": component_type,
                                "component_name": component_name,
                                "model_name": model_name,
                                "arg_key": arg_key,
                            }

    return port_settings


def map_ports_to_types(port_settings: Dict[str, Dict]) -> Dict[str, int]:
    """Map found ports to standard port types."""
    port_mapping = {}

    # Map based on port values
    for env_var, info in port_settings.items():
        port_value = info["port"]

        # Determine port type based on port value and variable name
        if port_value == 26658 or "abci" in env_var.lower():
            port_mapping["abci"] = port_value
        elif port_value == 26657 or "rpc" in env_var.lower():
            port_mapping["rpc"] = port_value
        elif port_value == 26656 or "p2p" in env_var.lower():
            port_mapping["p2p"] = port_value
        elif port_value == 8080 or "com" in env_var.lower():
            port_mapping["com"] = port_value
        elif port_value == 8716 or "http" in env_var.lower():
            port_mapping["http"] = port_value

    return port_mapping


def generate_env_vars(port_mapping: Dict[str, int]) -> Dict[str, str]:
    """Generate environment variables for the port mapping."""
    env_vars = {}

    # ABCI connection port
    env_vars["CONNECTION_ABCI_CONFIG_PORT"] = str(
        port_mapping.get("abci", DEFAULT_PORTS["abci"])
    )

    # HTTP server port
    env_vars["CONNECTION_HTTP_SERVER_CONFIG_PORT"] = str(
        port_mapping.get("http", DEFAULT_PORTS["http"])
    )

    # Skill params for trader_abci
    env_vars["SKILL_TRADER_ABCI_MODELS_PARAMS_ARGS_TENDERMINT_URL"] = (
        f"http://localhost:{port_mapping.get('rpc', DEFAULT_PORTS['rpc'])}"
    )
    env_vars["SKILL_TRADER_ABCI_MODELS_PARAMS_ARGS_TENDERMINT_COM_URL"] = (
        f"http://localhost:{port_mapping.get('com', DEFAULT_PORTS['com'])}"
    )
    env_vars["SKILL_TRADER_ABCI_MODELS_PARAMS_ARGS_TENDERMINT_P2P_URL"] = (
        f"localhost:{port_mapping.get('p2p', DEFAULT_PORTS['p2p'])}"
    )

    return env_vars


def format_output(port_mapping: Dict[str, int], env_vars: Dict[str, str]) -> str:
    """Format output in bash format."""
    lines = []

    # Tendermint environment variables
    lines.append("# Tendermint environment variables")
    lines.append(
        f"export TENDERMINT_ABCI_PORT={port_mapping.get('abci', DEFAULT_PORTS['abci'])}"
    )
    lines.append(
        f"export TENDERMINT_RPC_PORT={port_mapping.get('rpc', DEFAULT_PORTS['rpc'])}"
    )
    lines.append(
        f"export TENDERMINT_P2P_PORT={port_mapping.get('p2p', DEFAULT_PORTS['p2p'])}"
    )
    lines.append(
        f"export TENDERMINT_COM_PORT={port_mapping.get('com', DEFAULT_PORTS['com'])}"
    )
    lines.append(
        f"export HTTP_SERVER_PORT={port_mapping.get('http', DEFAULT_PORTS['http'])}"
    )

    lines.append("")
    lines.append("# Open-AEA environment variables")
    for env_var, value in sorted(env_vars.items()):
        # Escape quotes and special characters for bash
        escaped_value = str(value).replace('"', '\\"').replace("$", "\\$")
        lines.append(f'export {env_var}="{escaped_value}"')

    return "\n".join(lines)


def main() -> None:
    """Main function."""
    # pylint: disable=too-many-locals,too-many-statements,broad-exception-caught,too-many-branches
    parser = argparse.ArgumentParser(
        description="Generate environment variables for agent ports from aea-config.yaml"
    )
    parser.add_argument(
        "--config",
        default="agent/aea-config.yaml",
        help="Path to aea-config.yaml (default: agent/aea-config.yaml)",
    )
    parser.add_argument(
        "--abci-port", type=int, help="ABCI port (0 for dynamic allocation)"
    )
    parser.add_argument(
        "--rpc-port", type=int, help="Tendermint RPC port (0 for dynamic allocation)"
    )
    parser.add_argument(
        "--p2p-port", type=int, help="Tendermint P2P port (0 for dynamic allocation)"
    )
    parser.add_argument(
        "--com-port", type=int, help="Tendermint COM port (0 for dynamic allocation)"
    )
    parser.add_argument(
        "--http-port", type=int, help="HTTP server port (0 for dynamic allocation)"
    )

    args = parser.parse_args()

    # Check if config file exists
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)

    # Load config
    try:
        with open(config_path, "r", encoding="utf-8") as file:
            config = list(yaml.safe_load_all(file))
    except (yaml.YAMLError, IOError, OSError) as error:
        print(f"Error loading config file: {error}")
        sys.exit(1)

    # Find port settings in config
    port_settings = find_port_settings_in_config(config)

    # User port preferences - check environment variables first, then command line args
    user_ports = {}

    # Check environment variables
    env_port_mapping = {
        "abci": os.environ.get("TENDERMINT_ABCI_PORT"),
        "rpc": os.environ.get("TENDERMINT_RPC_PORT"),
        "p2p": os.environ.get("TENDERMINT_P2P_PORT"),
        "com": os.environ.get("TENDERMINT_COM_PORT"),
        "http": os.environ.get("HTTP_SERVER_PORT"),
    }

    # Convert environment variables to integers if they exist
    for port_type, env_value in env_port_mapping.items():
        if env_value is not None and env_value.strip():
            try:
                user_ports[port_type] = int(env_value)
            except ValueError:
                print(
                    f"Warning: Invalid port value for {port_type}: {env_value}",
                    file=sys.stderr,
                )

    # Override with command line arguments if provided
    if args.abci_port is not None:
        user_ports["abci"] = args.abci_port
    if args.rpc_port is not None:
        user_ports["rpc"] = args.rpc_port
    if args.p2p_port is not None:
        user_ports["p2p"] = args.p2p_port
    if args.com_port is not None:
        user_ports["com"] = args.com_port
    if args.http_port is not None:
        user_ports["http"] = args.http_port

    # Map ports from config
    config_port_mapping = map_ports_to_types(port_settings)

    # Process ports: handle 0 values (dynamic allocation)
    final_port_mapping = {}
    used_ports: Set[int] = set()

    # First pass: collect explicitly specified ports (not 0)
    for port_type, _ in DEFAULT_PORTS.items():
        # Priority: user port > config port
        port_value = None

        # pylint: disable=consider-using-get
        if port_type in user_ports:
            port_value = user_ports[port_type]
        elif port_type in config_port_mapping:
            port_value = config_port_mapping[port_type]

        # If port is explicitly specified (not 0), add to used ports
        if port_value is not None and port_value != 0:
            final_port_mapping[port_type] = port_value
            used_ports.add(port_value)

    # Second pass: handle ports that need dynamic allocation (0 or not specified)
    for port_type, default_port in DEFAULT_PORTS.items():
        if port_type in final_port_mapping:
            continue  # Already processed

        port_value = None

        # pylint: disable=consider-using-get
        if port_type in user_ports:
            port_value = user_ports[port_type]
        elif port_type in config_port_mapping:
            port_value = config_port_mapping[port_type]

        # If port is 0 or not specified, find free port
        if port_value == 0 or port_value is None:
            # For dynamic allocation (port=0), start from DYNAMIC_PORT_START
            # For unspecified ports, use default port
            start_port = DYNAMIC_PORT_START if port_value == 0 else default_port
            free_port = find_free_port(start_port, used_ports)
            final_port_mapping[port_type] = free_port
            used_ports.add(free_port)
        else:
            # Should not happen, but just in case
            final_port_mapping[port_type] = port_value
            used_ports.add(port_value)

    # Generate environment variables
    env_vars = generate_env_vars(final_port_mapping)

    # Format and output (always bash format)
    output = format_output(final_port_mapping, env_vars)
    print(output)


if __name__ == "__main__":
    main()
