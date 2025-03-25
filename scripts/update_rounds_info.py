import ast
import re
from pathlib import Path

from aea.protocols.generator.common import _camel_case_to_snake_case

# Adjusted file paths
ROUNDS_INFO_PATH = Path("../packages/valory/skills/decision_maker_abci/rounds_info.py")
STATES_DIR_PATH = Path("../packages/valory/skills/decision_maker_abci/states")


def extract_action_description(docstring: str) -> str:
    """Extract the action description from the docstring."""
    match = re.search(r"Action Description: (.+)", docstring)
    return match.group(1) if match else None


def update_rounds_info():
    """Update the ROUNDS_INFO dictionary with names and descriptions from the states."""
    rounds_info = {}

    for file_path in STATES_DIR_PATH.glob("*.py"):
        if file_path.name == "__init__.py" or file_path.name == "base.py":
            continue
        with open(file_path, "r", encoding="utf-8") as file:
            tree = ast.parse(file.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name
                docstring = ast.get_docstring(node)
                if docstring:
                    action_description = extract_action_description(docstring)
                    if action_description:
                        round_name = _camel_case_to_snake_case(class_name)
                        rounds_info[round_name] = {
                            "name": round_name.replace("_", " ").title(),
                            "description": action_description,
                            "transitions": {},
                        }
                    else:
                        raise ValueError(f"Action description not found in {file_path} for class {class_name}. "
                                         f"You must provide an action description in the docstring in order to update "
                                         f"the rounds info.")

    with open(ROUNDS_INFO_PATH, "r", encoding="utf-8") as file:
        content = file.read()

    rounds_info_pattern = re.compile(r"ROUNDS_INFO\s*=\s*{(.+?)}", re.DOTALL)
    new_rounds_info_str = "ROUNDS_INFO = {\n"
    for round_name, info in rounds_info.items():
        new_rounds_info_str += f'    "{round_name}": {info},\n'
    new_rounds_info_str += "}"

    if rounds_info_pattern.search(content).group(0) != new_rounds_info_str:
        updated_content = rounds_info_pattern.sub(new_rounds_info_str, content)
        with open(ROUNDS_INFO_PATH, "w", encoding="utf-8") as file:
            file.write(updated_content)


if __name__ == "__main__":
    update_rounds_info()