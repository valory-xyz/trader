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
"""A script to auto update or check the rounds info for the 'decision_maker_abci' skill."""

import argparse
import logging
import re
import sys
from collections.abc import KeysView
from pathlib import Path
from typing import Dict, List, Tuple, Union

import yaml
from aea.protocols.generator.common import _camel_case_to_snake_case, _to_camel_case

from packages.valory.skills.decision_maker_abci.rounds_info import ROUNDS_INFO


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("rounds_info_updater")


# Define constants
EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_ERROR = 13


# Types
RoundInfo = Dict[str, Union[str, Dict[str, str]]]
IssueLevel = str  # "error" or "warning"
IssueDict = Dict[str, Union[IssueLevel, str]]


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


# Setup paths
ROOT_DIR = find_project_root(Path(__file__).resolve())
FSM_SPECIFICATION_FILE = Path(
    ROOT_DIR / "packages/valory/skills/trader_abci/fsm_specification.yaml"
)
SKILLS_DIR_PATH = Path(ROOT_DIR / "packages/valory/skills")
ROUNDS_INFO_PATH = Path(
    ROOT_DIR / "packages/valory/skills/decision_maker_abci/rounds_info.py"
)


# FSM and Round Information Functions
def load_fsm_spec() -> Dict:
    """Load the FSM specification."""
    try:
        with open(FSM_SPECIFICATION_FILE, "r", encoding="utf-8") as spec_file:
            return yaml.safe_load(spec_file)
    except (FileNotFoundError, yaml.YAMLError) as e:
        logger.error(f"Failed to load FSM specification: {e}")
        sys.exit(EXIT_ERROR)


def extract_rounds_from_fsm_spec(fsm_spec: Dict) -> List[str]:
    """Extract rounds from FSM specification."""
    return fsm_spec["states"]


def initialize_rounds_info(fsm_spec: Dict) -> Dict[str, RoundInfo]:
    """Initialize rounds info dictionary from FSM spec."""
    rounds_info = {}
    for fsm_round in extract_rounds_from_fsm_spec(fsm_spec):
        snake_case_round = _camel_case_to_snake_case(fsm_round)
        rounds_info[snake_case_round] = {
            "name": snake_case_round.replace("_", " ").title(),
            "description": "",
            "transitions": {},
        }
    return rounds_info


# File Processing Functions
def find_rounds_in_file(
    file_path: Path, rounds: KeysView, new_rounds_info: Dict[str, RoundInfo]
) -> Dict[str, RoundInfo]:
    """
    Find rounds in a file and check for Action Description in docstring.

    Args:
        file_path: Path to the file to check
        rounds: Round names to look for
        new_rounds_info: Dictionary to update with found descriptions

    Returns:
        Updated rounds_info dictionary
    """
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            content = file.read()
            for round_name in rounds:
                camel_case_round = _to_camel_case(round_name)
                if camel_case_round in content:
                    match = re.search(
                        rf"class {camel_case_round}\(.*\):\n\s+\"\"\"(.*?)\"\"\"",
                        content,
                        re.DOTALL,
                    )
                    if match:
                        docstring = match.group(1)
                        action_description = re.search(
                            r"Action Description: (.*)", docstring
                        )
                        if action_description:
                            new_rounds_info[round_name]["description"] = (
                                action_description.group(1).strip()
                            )
                            logger.debug(
                                f"Found description for {camel_case_round}: "
                                f"{action_description.group(1).strip()}"
                            )
    except (FileNotFoundError, PermissionError) as e:
        logger.warning(f"Could not process file {file_path}: {e}")

    return new_rounds_info


def extract_rounds_with_descriptions_from_files() -> Dict[str, Dict[str, str]]:
    """
    Extract all round classes with action descriptions from files.

    Returns:
        Dictionary mapping round_name to {description, file_path}
    """
    found_rounds = {}

    for skill_dir in SKILLS_DIR_PATH.iterdir():
        if not skill_dir.is_dir():
            continue

        # Collect all relevant Python files that might contain Round classes
        rounds_files = list(skill_dir.glob("**/rounds.py"))
        if skill_dir.name == "decision_maker_abci":
            rounds_files.extend(skill_dir.glob("states/*.py"))

        for file_path in rounds_files:
            try:
                with open(file_path, "r", encoding="utf-8") as file:
                    content = file.read()
                    # Find all Round classes and their docstrings
                    class_matches = re.finditer(
                        r"class (\w+Round)\(.*\):\n\s+\"\"\"(.*?)\"\"\"",
                        content,
                        re.DOTALL,
                    )

                    for match in class_matches:
                        class_name = match.group(1)
                        docstring = match.group(2)

                        # Check if it has an Action Description
                        action_desc_match = re.search(
                            r"Action Description: (.*)", docstring
                        )
                        if action_desc_match:
                            snake_case_name = _camel_case_to_snake_case(class_name)
                            description = action_desc_match.group(1).strip()

                            found_rounds[snake_case_name] = {
                                "description": description,
                                "file_path": str(file_path),
                            }
            except (FileNotFoundError, PermissionError) as e:
                logger.warning(f"Could not process file {file_path}: {e}")

    return found_rounds


def process_rounds_files(new_rounds_info: Dict[str, RoundInfo]) -> Dict[str, RoundInfo]:
    """
    Find round descriptions from round files in skills.

    Args:
        new_rounds_info: Initial rounds info dictionary to update

    Returns:
        Updated rounds info dictionary with descriptions
    """
    for skill_dir in SKILLS_DIR_PATH.iterdir():
        if not skill_dir.is_dir() or skill_dir.name == "trader_abci":
            continue

        rounds_files = list(skill_dir.glob("**/rounds.py"))
        if skill_dir.name == "decision_maker_abci":
            rounds_files.extend(skill_dir.glob("states/*.py"))

        for rounds_file in rounds_files:
            logger.debug(f"Processing file: {rounds_file}")
            new_rounds_info = find_rounds_in_file(
                rounds_file, new_rounds_info.keys(), new_rounds_info
            )

    return new_rounds_info


# Rounds Info Updating Functions
def update_rounds_info(
    current_rounds_info: Dict[str, RoundInfo], new_rounds_info: Dict[str, RoundInfo]
) -> Tuple[Dict[str, RoundInfo], List[str]]:
    """
    Update rounds info dictionary with new rounds info.

    Args:
        current_rounds_info: Existing rounds info from rounds_info.py
        new_rounds_info: New rounds info extracted from FSM and code

    Returns:
        Tuple of (updated rounds info, list of rounds still missing descriptions)
    """
    rounds_to_check = []

    for fsm_round, new_round_info in new_rounds_info.items():
        if new_round_info["description"] == "":
            rounds_to_check.append(fsm_round)
            # Preserve existing description if available
            if fsm_round in current_rounds_info:
                new_round_info["description"] = current_rounds_info[fsm_round][
                    "description"
                ]

    return new_rounds_info, rounds_to_check


def load_rounds_info_with_transitions(
    updated_rounds_info: Dict[str, RoundInfo],
) -> Dict[str, RoundInfo]:
    """
    Load the rounds info with the transitions from FSM.

    Args:
        updated_rounds_info: Rounds info to update with transitions

    Returns:
        Rounds info with transitions added
    """
    fsm = load_fsm_spec()

    for source_info, target_round in fsm["transition_func"].items():
        # Parse the source_info tuple: "(SourceRound, EVENT)" -> ["SourceRound", "EVENT"]
        source_round, event = source_info[1:-1].split(", ")
        source_round_snake = _camel_case_to_snake_case(source_round)
        target_round_snake = _camel_case_to_snake_case(target_round)
        event_lower = event.lower()

        # Add transition to the source round
        if source_round_snake in updated_rounds_info:
            updated_rounds_info[source_round_snake]["transitions"][event_lower] = (
                target_round_snake
            )

    return updated_rounds_info


def write_updated_rounds_info(updated_rounds_info: Dict[str, RoundInfo]) -> None:
    """
    Write updated rounds info back to the rounds_info.py file.

    Args:
        updated_rounds_info: Updated rounds info to write
    """
    try:
        with open(ROUNDS_INFO_PATH, "r", encoding="utf-8") as file:
            content = file.read()

        # Create new rounds info string
        new_rounds_info_str = (
            "ROUNDS_INFO = {\n"
            + "".join(
                f"    {round_name!r}: {info},\n"
                for round_name, info in updated_rounds_info.items()
            )
            + "}\n"
        )

        # Replace existing ROUNDS_INFO or append if not found
        if re.search(r"ROUNDS_INFO\s*=\s*\{.*?\}\s*\n", content, flags=re.DOTALL):
            updated_content = re.sub(
                r"ROUNDS_INFO\s*=\s*\{.*?\}\s*\n",
                new_rounds_info_str,
                content,
                flags=re.DOTALL,
            )
        else:
            updated_content = content + "\n\n" + new_rounds_info_str

        # Write updated content
        with open(ROUNDS_INFO_PATH, "w", encoding="utf-8") as file:
            file.write(updated_content)

        logger.info(f"Successfully updated {ROUNDS_INFO_PATH}")

    except (FileNotFoundError, PermissionError) as e:
        logger.error(f"Failed to write updated rounds_info: {e}")
        sys.exit(EXIT_ERROR)


# Checking and Validation Functions
def check_rounds_info(
    current_rounds_info: Dict[str, RoundInfo], fsm_spec: Dict
) -> List[IssueDict]:
    """
    Check rounds info file for consistency with FSM spec and code.

    Args:
        current_rounds_info: Current rounds_info from rounds_info.py
        fsm_spec: FSM specification

    Returns:
        List of issues found, each as a dictionary with keys:
        - level: 'error' or 'warning'
        - round_name: Name of the round with the issue
        - message: Description of the issue
    """
    issues = []

    # 1. Extract rounds from different sources
    fsm_rounds = {
        _camel_case_to_snake_case(r) for r in extract_rounds_from_fsm_spec(fsm_spec)
    }
    code_rounds = extract_rounds_with_descriptions_from_files()
    info_rounds = set(current_rounds_info.keys())

    # 2. Check for missing or extra rounds
    for fsm_round in fsm_rounds:
        if fsm_round not in info_rounds:
            issues.append(
                {
                    "level": "error",
                    "round_name": fsm_round,
                    "message": "Present in FSM but missing from rounds_info.py",
                }
            )

    for info_round in info_rounds:
        if info_round not in fsm_rounds:
            issues.append(
                {
                    "level": "warning",
                    "round_name": info_round,
                    "message": "Present in rounds_info.py but not in FSM specification",
                }
            )

    # 3. Check for description consistency
    for round_name in (
        fsm_rounds & info_rounds
    ):  # Intersection - rounds in both FSM and info
        in_code = round_name in code_rounds
        has_desc_in_info = bool(current_rounds_info[round_name].get("description", ""))

        if in_code and not has_desc_in_info:
            issues.append(
                {
                    "level": "warning",
                    "round_name": round_name,
                    "message": (
                        f"Has Action Description in code ({code_rounds[round_name]['file_path']}) "
                        f"but missing or empty in rounds_info.py: '{code_rounds[round_name]['description']}'"
                    ),
                }
            )
        # Removed the warning for rounds with description in rounds_info.py but no Action Description in code
        # The following condition has been removed:
        # elif has_desc_in_info and not in_code:
        #     issues.append({
        #         "level": "warning",
        #         "round_name": round_name,
        #         "message": "Has description in rounds_info.py but no Action Description found in any code file"
        #     })

        # Check if descriptions are different when both exist
        if in_code and has_desc_in_info:
            code_desc = code_rounds[round_name]["description"]
            info_desc = current_rounds_info[round_name]["description"]
            if code_desc != info_desc:
                issues.append(
                    {
                        "level": "warning",
                        "round_name": round_name,
                        "message": (
                            f"Description mismatch between code and rounds_info.py:\n"
                            f"Code: '{code_desc}'\n"
                            f"Info: '{info_desc}'"
                        ),
                    }
                )

    # 4. Check transition consistency
    for source_info, target_round in fsm_spec["transition_func"].items():
        # Parse the transition tuple
        source_round, event = source_info[1:-1].split(", ")
        source_round_snake = _camel_case_to_snake_case(source_round)
        target_round_snake = _camel_case_to_snake_case(target_round)
        event_lower = event.lower()

        # Check if transition is correctly represented in rounds_info
        if source_round_snake in current_rounds_info:
            transitions = current_rounds_info[source_round_snake].get("transitions", {})

            if event_lower not in transitions:
                issues.append(
                    {
                        "level": "error",
                        "round_name": source_round_snake,
                        "message": f"Missing transition '{event_lower}' in rounds_info.py that is present in FSM",
                    }
                )
            elif transitions[event_lower] != target_round_snake:
                issues.append(
                    {
                        "level": "error",
                        "round_name": source_round_snake,
                        "message": (
                            f"Transition mismatch for '{event_lower}': "
                            f"rounds_info.py has '{transitions[event_lower]}' but FSM has '{target_round_snake}'"
                        ),
                    }
                )

    # 5. Check for transitions in rounds_info that aren't in the FSM
    for round_name, info in current_rounds_info.items():
        for event, target in info.get("transitions", {}).items():
            # Convert to camel case for checking in the FSM
            round_camel = _to_camel_case(round_name)
            source_tuple = f"({round_camel}, {event.upper()})"

            if source_tuple not in fsm_spec["transition_func"]:
                issues.append(
                    {
                        "level": "warning",
                        "round_name": round_name,
                        "message": f"Transition '{event}' to '{target}' exists in rounds_info.py but not in FSM specification",
                    }
                )

    return issues


# Main Functions
def update_mode() -> int:
    """Run in update mode to update rounds_info.py file."""
    logger.info("Running in update mode")

    # Load FSM specification
    fsm_spec = load_fsm_spec()

    # Initialize new rounds info from FSM
    new_rounds_info = initialize_rounds_info(fsm_spec)

    # Extract descriptions from round files
    new_rounds_info = process_rounds_files(new_rounds_info)

    # Update with existing descriptions where new ones are missing
    updated_rounds_info, rounds_to_check = update_rounds_info(
        ROUNDS_INFO, new_rounds_info
    )

    # Add transitions from FSM
    updated_rounds_info_with_transitions = load_rounds_info_with_transitions(
        updated_rounds_info
    )

    # Write back to file
    write_updated_rounds_info(updated_rounds_info_with_transitions)

    # Report on missing descriptions
    if rounds_to_check:
        logger.warning("The following rounds are still missing action descriptions:")
        for round_name in sorted(rounds_to_check):
            logger.warning(f"- {round_name}")
        return EXIT_FAILURE

    logger.info("Successfully updated rounds_info.py with all descriptions")
    return EXIT_SUCCESS


def check_mode() -> int:
    """Run in check mode to verify rounds_info.py consistency."""
    logger.info("Running in check mode")

    # Load FSM specification
    fsm_spec = load_fsm_spec()

    # Check for issues
    issues = check_rounds_info(ROUNDS_INFO, fsm_spec)

    if not issues:
        logger.info("All rounds are properly defined and described in rounds_info.py")
        return EXIT_SUCCESS

    # Group issues by level
    errors = [issue for issue in issues if issue["level"] == "error"]
    warnings = [issue for issue in issues if issue["level"] == "warning"]

    # Report issues
    if errors:
        logger.error("ERRORS:")
        for issue in sorted(errors, key=lambda x: x["round_name"]):
            logger.error(f"- {issue['round_name']}: {issue['message']}")

    if warnings:
        logger.warning("WARNINGS:")
        for issue in sorted(warnings, key=lambda x: x["round_name"]):
            logger.warning(f"- {issue['round_name']}: {issue['message']}")

    # Exit with error if there are errors
    if errors:
        return EXIT_FAILURE

    logger.info("No critical errors found, but please review warnings")
    return EXIT_SUCCESS


def main(check: bool) -> int:
    """
    Main function to update or check rounds info.

    Args:
        check: Whether to run in check mode

    Returns:
        Exit code
    """
    try:
        if check:
            return check_mode()
        else:
            return update_mode()
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        return EXIT_ERROR


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Update or check the rounds info for the 'decision_maker_abci' skill."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run the script in check mode to report missing descriptions without updating files.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Set logging level based on verbosity
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Run main function and exit with return code
    sys.exit(main(check=args.check))
