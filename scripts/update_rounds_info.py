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
"""A script to auto update the rounds info for the 'decision_maker_abci' skill."""

import re
from collections.abc import KeysView
from pathlib import Path
from typing import Dict, List, Tuple

import yaml
from aea.protocols.generator.common import _camel_case_to_snake_case

from packages.valory.skills.decision_maker_abci.rounds_info import ROUNDS_INFO


# Find the project root dynamically
def find_project_root(current_path: Path) -> Path:
    """Find the root of the project by looking for a pyproject.toml."""
    while current_path != current_path.parent:
        if (current_path / "pyproject.toml").exists():
            return current_path
        current_path = current_path.parent
    raise FileNotFoundError(
        "Project root not found. Ensure you have a pyproject.toml in the root."
    )


ROOT_DIR = find_project_root(Path(__file__).resolve())
FSM_SPECIFICATION_FILE = Path(
    ROOT_DIR / "packages/valory/skills/trader_abci/fsm_specification.yaml"
)
SKILLS_DIR_PATH = Path(ROOT_DIR / "packages/valory/skills")
ROUNDS_INFO_PATH = Path(
    ROOT_DIR / "packages/valory/skills/decision_maker_abci/rounds_info.py"
)


def load_fsm_spec() -> Dict:
    """Load the FSM specification."""
    with open(
        FSM_SPECIFICATION_FILE,
        "r",
        encoding="utf-8",
    ) as spec_file:
        return yaml.safe_load(spec_file)


def load_rounds_info_with_transitions(updated_rounds_info: Dict) -> Dict:
    """Load the rounds info with the transitions"""

    fsm = load_fsm_spec()

    rounds_info_with_transitions: Dict = updated_rounds_info
    for source_info, target_round in fsm["transition_func"].items():
        # Removes the brackets from the source info tuple and splits it into round and event
        source_round, event = source_info[1:-1].split(", ")
        rounds_info_with_transitions[_camel_case_to_snake_case(source_round)][
            "transitions"
        ][event.lower()] = _camel_case_to_snake_case(target_round)

    return rounds_info_with_transitions


def extract_rounds_from_fsm_spec(fsm_spec: Dict) -> List[str]:
    """Extract rounds from FSM specification."""
    return fsm_spec["states"]


def find_rounds_in_file(
    file_path: Path, rounds: KeysView, new_rounds_info: Dict
) -> Dict[str, str]:
    """Find rounds in a file and check for Action Description in docstring."""
    with open(file_path, "r", encoding="utf-8") as file:
        content = file.read()
        for round_name in rounds:
            if round_name in content:
                match = re.search(
                    rf"class {round_name}\(.*\):\n\s+\"\"\"(.*?)\"\"\"",
                    content,
                    re.DOTALL,
                )
                if match:
                    docstring = match.group(1)
                    action_description = re.search(
                        r"Action Description: (.*)", docstring
                    )
                    if action_description:
                        new_rounds_info[_camel_case_to_snake_case(round_name)][
                            "description"
                        ] = action_description.group(1)
    return new_rounds_info


def update_rounds_info(rounds_info: Dict, new_rounds_info: Dict) -> Tuple[Dict, List]:
    """Update rounds info dictionary with new rounds info."""
    rounds_to_check = []
    for fsm_round, new_round_info in new_rounds_info.items():
        if new_round_info["description"] == "":
            rounds_to_check.append(fsm_round)
            if fsm_round in rounds_info:
                new_round_info["description"] = rounds_info[fsm_round]["description"]

    return new_rounds_info, rounds_to_check


def initialize_rounds_info(fsm_spec: Dict) -> Dict:
    """Initialize rounds info dictionary from FSM spec."""
    rounds_info = {}
    for fsm_round in extract_rounds_from_fsm_spec(fsm_spec):
        rounds_info[_camel_case_to_snake_case(fsm_round)] = {
            "name": _camel_case_to_snake_case(fsm_round).replace("_", " ").title(),
            "description": "",
            "transitions": {},
        }
    return rounds_info


def process_rounds_files(new_rounds_info: Dict) -> None:
    """Find round descriptions from round files in skills."""
    for skill_dir in SKILLS_DIR_PATH.iterdir():
        if skill_dir.is_dir() and skill_dir.name != "trader_abci":
            rounds_files = list(skill_dir.glob("**/rounds.py"))
            if skill_dir.name == "decision_maker_abci":
                rounds_files.extend(skill_dir.glob("states/*.py"))
            for rounds_file in rounds_files:
                find_rounds_in_file(
                    rounds_file, new_rounds_info.keys(), new_rounds_info
                )


def write_updated_rounds_info(updated_rounds_info: Dict) -> None:
    """Write updated rounds info back to the rounds_info.py file."""
    with open(ROUNDS_INFO_PATH, "r", encoding="utf-8") as file:
        content = file.read()

    new_rounds_info_str = (
        "ROUNDS_INFO = {\n"
        + "".join(
            f"    {round_name!r}: {info},\n"
            for round_name, info in updated_rounds_info.items()
        )
        + "}\n"
    )

    updated_content = (
        re.sub(
            r"ROUNDS_INFO\s*=\s*\{.*?\}\s*\n",
            new_rounds_info_str,
            content,
            flags=re.DOTALL,
        )
        if re.search(r"ROUNDS_INFO\s*=\s*\{.*?\}\s*\n", content, flags=re.DOTALL)
        else content + "\n\n" + new_rounds_info_str
    )

    with open(ROUNDS_INFO_PATH, "w", encoding="utf-8") as file:
        file.write(updated_content)


def main() -> None:
    """Main function to update rounds info."""
    fsm_spec = load_fsm_spec()
    new_rounds_info = initialize_rounds_info(fsm_spec)

    # Extract descriptions from round files
    process_rounds_files(new_rounds_info)

    # Update rounds info and check for missing descriptions
    updated_rounds_info, rounds_to_check = update_rounds_info(
        ROUNDS_INFO, new_rounds_info
    )

    # load rounds info with transitions
    updated_rounds_info_with_transitions = load_rounds_info_with_transitions(
        updated_rounds_info
    )

    # Write back to file
    write_updated_rounds_info(updated_rounds_info_with_transitions)

    # Alert for missing descriptions
    if rounds_to_check:
        print("Rounds missing action descriptions:")
        for round_name in rounds_to_check:
            print(f"- {round_name}")


if __name__ == "__main__":
    main()
