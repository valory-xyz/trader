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
import shutil
import sys
from collections.abc import KeysView
from pathlib import Path
from typing import Dict, List, Literal, Tuple, Union

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

# Dictionary keys
NAME_KEY = "name"
DESCRIPTION_KEY = "description"
TRANSITIONS_KEY = "transitions"
FILE_PATH_KEY = "file_path"
LEVEL_KEY = "level"
ROUND_NAME_KEY = "round_name"
MESSAGE_KEY = "message"

# Issue levels
ERROR_LEVEL = "error"
WARNING_LEVEL = "warning"

# Compiled regular expressions
ROUND_CLASS_PATTERN = re.compile(
    r"class\s+(\w+Round)\s*\(.*?\):\s*(?:\n\s+(?:\"\"\"|\'\'\'))(.*?)(?:\"\"\"|\'\'\')(?=\n\s+|$)",
    re.DOTALL,
)
# Replace the current ACTION_DESC_PATTERN with:
ACTION_DESC_PATTERN = re.compile(
    r"Action\s+Description\s*:\s*(.*?)(?:\n\n|\Z)", re.DOTALL
)
ROUNDS_INFO_PATTERN = re.compile(r"ROUNDS_INFO\s*=\s*\{.*?\}\s*\n", re.DOTALL)
SOURCE_INFO_PATTERN = re.compile(r"\(([^,]+),\s*([^)]+)\)")


# Types
RoundInfo = Dict[str, Union[str, Dict[str, str]]]
TransitionsDict = Dict[str, str]  # Add this line
IssueLevel = Literal["error", "warning"]
IssueDict = Dict[Literal["level", "round_name", "message"], Union[IssueLevel, str]]


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


# File operation helpers
def read_file_content(file_path: Path) -> str:
    """Read file content with proper error handling."""
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return file.read()
    except (FileNotFoundError, PermissionError) as e:
        logger.warning(f"Could not read file {file_path}: {e}")
        return ""


def write_file_content(file_path: Path, content: str) -> bool:
    """Write content to file with proper error handling."""
    try:
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(content)
        return True
    except (FileNotFoundError, PermissionError) as e:
        logger.error(f"Could not write to file {file_path}: {e}")
        return False


def backup_file(file_path: Path) -> None:
    """Create a backup of a file before overwriting it."""
    if not file_path.exists():
        return

    backup_path = file_path.with_suffix(f"{file_path.suffix}.bak")
    try:
        shutil.copy2(file_path, backup_path)
        logger.info(f"Created backup at {backup_path}")
    except (FileNotFoundError, PermissionError) as e:
        logger.warning(f"Could not create backup of {file_path}: {e}")


# FSM and Round Information Functions
def load_fsm_spec() -> Dict:
    """Load the FSM specification."""
    try:
        content = read_file_content(FSM_SPECIFICATION_FILE)
        if not content:
            logger.error("Failed to read FSM specification: Empty file")
            sys.exit(EXIT_ERROR)

        fsm_spec = yaml.safe_load(content)
        if not validate_fsm_spec(fsm_spec):
            sys.exit(EXIT_ERROR)

        return fsm_spec
    except yaml.YAMLError as e:
        logger.error(f"Failed to parse FSM specification: {e}")
        sys.exit(EXIT_ERROR)


def validate_fsm_spec(fsm_spec: Dict) -> bool:
    """Validate the FSM specification has the expected structure."""
    required_keys = ["states", "transition_func"]
    if not all(key in fsm_spec for key in required_keys):
        logger.error(f"FSM spec missing required keys: {required_keys}")
        return False
    return True


def extract_rounds_from_fsm_spec(fsm_spec: Dict) -> List[str]:
    """Extract rounds from FSM specification."""
    return fsm_spec["states"]


def initialize_rounds_info(fsm_spec: Dict) -> Dict[str, RoundInfo]:
    """Initialize rounds info dictionary from FSM spec."""
    rounds_info = {}
    for fsm_round in extract_rounds_from_fsm_spec(fsm_spec):
        snake_case_round = _camel_case_to_snake_case(fsm_round)
        rounds_info[snake_case_round] = {
            NAME_KEY: snake_case_round.replace("_", " ").title(),
            DESCRIPTION_KEY: "",
            TRANSITIONS_KEY: {},
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
    content = read_file_content(file_path)
    if not content:
        return new_rounds_info

    for round_name in rounds:
        camel_case_round = _to_camel_case(round_name)
        if camel_case_round in content:
            match = ROUND_CLASS_PATTERN.search(content)
            if match and match.group(1) == camel_case_round:
                docstring = match.group(2)
                action_description = ACTION_DESC_PATTERN.search(docstring)
                if action_description:
                    new_rounds_info[round_name][DESCRIPTION_KEY] = (
                        action_description.group(1).strip()
                    )
                    logger.debug(
                        f"Found description for {camel_case_round}: "
                        f"{action_description.group(1).strip()}"
                    )

    return new_rounds_info


def extract_rounds_with_descriptions_from_files() -> Dict[str, Dict[str, str]]:
    """
    Extract all round classes with action descriptions from files.

    Returns:
        Dictionary mapping round_name to {description, file_path}
    """
    found_rounds = {}
    skill_dirs = list(SKILLS_DIR_PATH.iterdir())

    for skill_idx, skill_dir in enumerate(skill_dirs):
        if not skill_dir.is_dir():
            continue

        logger.debug(
            f"Processing skill {skill_idx + 1}/{len(skill_dirs)}: {skill_dir.name}"
        )

        # Collect all relevant Python files that might contain Round classes
        rounds_files = list(skill_dir.glob("**/rounds.py"))
        if skill_dir.name == "decision_maker_abci":
            rounds_files.extend(skill_dir.glob("states/*.py"))

        for file_path in rounds_files:
            content = read_file_content(file_path)
            if not content:
                continue

            # Find all Round classes and their docstrings
            class_matches = ROUND_CLASS_PATTERN.finditer(content)

            for match in class_matches:
                class_name = match.group(1)
                docstring = match.group(2)

                # Check if it has an Action Description
                action_desc_match = ACTION_DESC_PATTERN.search(docstring)
                if action_desc_match:
                    snake_case_name = _camel_case_to_snake_case(class_name)
                    description = action_desc_match.group(1).strip()

                    found_rounds[snake_case_name] = {
                        DESCRIPTION_KEY: description,
                        FILE_PATH_KEY: str(file_path),
                    }

    return found_rounds


def process_rounds_files(new_rounds_info: Dict[str, RoundInfo]) -> Dict[str, RoundInfo]:
    """
    Find round descriptions from round files in skills.

    Args:
        new_rounds_info: Initial rounds info dictionary to update

    Returns:
        Updated rounds info dictionary with descriptions
    """
    skill_dirs = list(
        path
        for path in SKILLS_DIR_PATH.iterdir()
        if path.is_dir() and path.name != "trader_abci"
    )

    for skill_idx, skill_dir in enumerate(skill_dirs):
        logger.debug(
            f"Processing skill {skill_idx + 1}/{len(skill_dirs)}: {skill_dir.name}"
        )

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
        if not new_round_info.get(DESCRIPTION_KEY):
            rounds_to_check.append(fsm_round)
            # Preserve existing description if available
            if fsm_round in current_rounds_info:
                existing_desc = current_rounds_info[fsm_round].get(DESCRIPTION_KEY, "")
                new_round_info[DESCRIPTION_KEY] = existing_desc

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
        match = SOURCE_INFO_PATTERN.match(source_info)
        if not match:
            logger.warning(f"Unexpected format for source_info: {source_info}")
            continue

        source_round, event = match.groups()
        source_round_snake = _camel_case_to_snake_case(source_round)
        target_round_snake = _camel_case_to_snake_case(target_round)
        event_lower = event.lower().strip()

        # Add transition to the source round
        if source_round_snake in updated_rounds_info:
            # Ensure TRANSITIONS_KEY exists and is a dictionary
            transitions = updated_rounds_info[source_round_snake].get(
                TRANSITIONS_KEY, {}
            )
            if not isinstance(transitions, dict):
                transitions = {}

            # Update transitions
            transitions[event_lower] = target_round_snake
            updated_rounds_info[source_round_snake][TRANSITIONS_KEY] = transitions

    return updated_rounds_info


def write_updated_rounds_info(updated_rounds_info: Dict[str, RoundInfo]) -> None:
    """
    Write updated rounds info back to the rounds_info.py file.

    Args:
        updated_rounds_info: Updated rounds info to write
    """
    # Create backup before modifying
    backup_file(ROUNDS_INFO_PATH)

    # Check if file exists or is empty
    if not ROUNDS_INFO_PATH.exists() or ROUNDS_INFO_PATH.stat().st_size == 0:
        content = "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n\n"
    else:
        content = read_file_content(ROUNDS_INFO_PATH)
        if not content:
            logger.error(f"Failed to read {ROUNDS_INFO_PATH}")
            sys.exit(EXIT_ERROR)

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
    if ROUNDS_INFO_PATTERN.search(content):
        updated_content = ROUNDS_INFO_PATTERN.sub(new_rounds_info_str, content)
    else:
        updated_content = content + "\n\n" + new_rounds_info_str

    # Write updated content
    if write_file_content(ROUNDS_INFO_PATH, updated_content):
        logger.info(f"Successfully updated {ROUNDS_INFO_PATH}")
    else:
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
                    LEVEL_KEY: ERROR_LEVEL,
                    ROUND_NAME_KEY: fsm_round,
                    MESSAGE_KEY: "Present in FSM but missing from rounds_info.py",
                }
            )

    for info_round in info_rounds:
        if info_round not in fsm_rounds:
            issues.append(
                {
                    LEVEL_KEY: WARNING_LEVEL,
                    ROUND_NAME_KEY: info_round,
                    MESSAGE_KEY: "Present in rounds_info.py but not in FSM specification",
                }
            )

    # 3. Check for description consistency
    for round_name in (
        fsm_rounds & info_rounds
    ):  # Intersection - rounds in both FSM and info
        in_code = round_name in code_rounds
        has_desc_in_info = bool(
            current_rounds_info[round_name].get(DESCRIPTION_KEY, "")
        )

        if in_code and not has_desc_in_info:
            issues.append(
                {
                    LEVEL_KEY: WARNING_LEVEL,
                    ROUND_NAME_KEY: round_name,
                    MESSAGE_KEY: (
                        f"Has Action Description in code ({code_rounds[round_name][FILE_PATH_KEY]}) "
                        f"but missing or empty in rounds_info.py: {code_rounds[round_name][DESCRIPTION_KEY]!r}"
                    ),
                }
            )

        # Check if descriptions are different when both exist
        if in_code and has_desc_in_info:
            code_desc = code_rounds[round_name][DESCRIPTION_KEY]
            info_desc = current_rounds_info[round_name][DESCRIPTION_KEY]
            if code_desc != info_desc:
                issues.append(
                    {
                        LEVEL_KEY: WARNING_LEVEL,
                        ROUND_NAME_KEY: round_name,
                        MESSAGE_KEY: (
                            f"Description mismatch between code and rounds_info.py:\n"
                            f"Code: {code_desc!r}\n"
                            f"Info: {info_desc!r}"
                        ),
                    }
                )

    # 4. Check transition consistency
    for source_info, target_round in fsm_spec["transition_func"].items():
        # Parse the transition tuple
        match = SOURCE_INFO_PATTERN.match(source_info)
        if not match:
            logger.warning(f"Unexpected format for source_info: {source_info}")
            continue

        source_round, event = match.groups()
        source_round_snake = _camel_case_to_snake_case(source_round)
        target_round_snake = _camel_case_to_snake_case(target_round)
        event_lower = event.lower().strip()

        # Check if transition is correctly represented in rounds_info
        if source_round_snake in current_rounds_info:
            transitions = current_rounds_info[source_round_snake].get(
                TRANSITIONS_KEY, {}
            )

            # Handle case where transitions might not be a dictionary
            if not isinstance(transitions, dict):
                issues.append(
                    {
                        LEVEL_KEY: ERROR_LEVEL,
                        ROUND_NAME_KEY: source_round_snake,
                        MESSAGE_KEY: f"Transitions key is not a dictionary: {transitions!r}",
                    }
                )
                continue

            if event_lower not in transitions:
                issues.append(
                    {
                        LEVEL_KEY: ERROR_LEVEL,
                        ROUND_NAME_KEY: source_round_snake,
                        MESSAGE_KEY: f"Missing transition {event_lower!r} in rounds_info.py that is present in FSM",
                    }
                )
            elif transitions[event_lower] != target_round_snake:
                issues.append(
                    {
                        LEVEL_KEY: ERROR_LEVEL,
                        ROUND_NAME_KEY: source_round_snake,
                        MESSAGE_KEY: (
                            f"Transition mismatch for {event_lower!r}: "
                            f"rounds_info.py has {transitions[event_lower]!r} but FSM has {target_round_snake!r}"
                        ),
                    }
                )

    # 5. Check for transitions in rounds_info that aren't in the FSM
    for round_name, info in current_rounds_info.items():
        transitions = info.get(TRANSITIONS_KEY, {})

        # Skip if transitions is not a dictionary
        if not isinstance(transitions, dict):
            continue

        for event, target in transitions.items():
            # Convert to camel case for checking in the FSM
            round_camel = _to_camel_case(round_name)
            source_tuple = f"({round_camel}, {event.upper()})"

            if source_tuple not in fsm_spec["transition_func"]:
                issues.append(
                    {
                        LEVEL_KEY: WARNING_LEVEL,
                        ROUND_NAME_KEY: round_name,
                        MESSAGE_KEY: f"Transition {event!r} to {target!r} exists in rounds_info.py but not in FSM specification",
                    }
                )

    return issues


def validate_round_info_structure(rounds_info: Dict[str, RoundInfo]) -> List[IssueDict]:
    """
    Validate the structure of rounds_info entries.

    Args:
        rounds_info: The rounds info dictionary to validate

    Returns:
        List of issues found
    """
    issues = []

    for round_name, info in rounds_info.items():
        # Check required keys
        for key in [NAME_KEY, DESCRIPTION_KEY, TRANSITIONS_KEY]:
            if key not in info:
                issues.append(
                    {
                        LEVEL_KEY: ERROR_LEVEL,
                        ROUND_NAME_KEY: round_name,
                        MESSAGE_KEY: f"Missing required key: {key}",
                    }
                )

        # Check transitions is a dictionary
        transitions = info.get(TRANSITIONS_KEY, {})
        if not isinstance(transitions, dict):
            issues.append(
                {
                    LEVEL_KEY: ERROR_LEVEL,
                    ROUND_NAME_KEY: round_name,
                    MESSAGE_KEY: f"Transitions is not a dictionary: {transitions!r}",
                }
            )

    return issues


def check_mode() -> int:
    """
    Run in check mode to verify rounds_info.py consistency.

    Returns:
        Exit code indicating success or failure
    """
    logger.info("Running in check mode")

    # Load FSM specification
    fsm_spec = load_fsm_spec()

    # Validate the structure of rounds_info
    structure_issues = validate_round_info_structure(ROUNDS_INFO)

    # Check for other issues
    consistency_issues = check_rounds_info(ROUNDS_INFO, fsm_spec)

    # Combine all issues
    issues = structure_issues + consistency_issues

    if not issues:
        logger.info("All rounds are properly defined and described in rounds_info.py")
        return EXIT_SUCCESS

    # Group issues by level
    errors = [issue for issue in issues if issue[LEVEL_KEY] == ERROR_LEVEL]
    warnings = [issue for issue in issues if issue[LEVEL_KEY] == WARNING_LEVEL]

    # Report issues
    if errors:
        logger.error("ERRORS:")
        for issue in sorted(errors, key=lambda x: x[ROUND_NAME_KEY]):
            logger.error(f"- {issue[ROUND_NAME_KEY]}: {issue[MESSAGE_KEY]}")

    if warnings:
        logger.warning("WARNINGS:")
        for issue in sorted(warnings, key=lambda x: x[ROUND_NAME_KEY]):
            logger.warning(f"- {issue[ROUND_NAME_KEY]}: {issue[MESSAGE_KEY]}")

    # Exit with error if there are errors
    if errors:
        return EXIT_FAILURE

    logger.info("No critical errors found, but please review warnings")
    return EXIT_SUCCESS


# Main Functions
def update_mode() -> int:
    """
    Run in update mode to update rounds_info.py file.

    Returns:
        Exit code indicating success or failure
    """
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
        return update_mode()
    except (FileNotFoundError, PermissionError) as e:
        logger.error(f"File system error: {e}", exc_info=True)
        return EXIT_ERROR
    except yaml.YAMLError as e:
        logger.error(f"YAML parsing error: {e}", exc_info=True)
        return EXIT_ERROR
    except KeyError as e:
        logger.error(f"Missing expected key: {e}", exc_info=True)
        return EXIT_ERROR
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
