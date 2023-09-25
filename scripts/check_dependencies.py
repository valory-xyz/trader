#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2022-2023 Valory AG
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
"""
This script checks that the pipfile of the repository meets the requirements.

In particular:
- Avoid the usage of "*"

It is assumed the script is run from the repository root.
"""
import os
import subprocess  # nosec
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

import toml
from aea.configurations.data_types import Dependency, PackageType
from aea.package_manager.base import load_configuration
from aea.package_manager.v1 import PackageManagerV1


def load_pyproject_toml(pyproject_toml_path: str = "./pyproject.toml") -> dict:
    """Load the pyproject.toml file contents."""

    # Load the pyproject.toml file
    with open(pyproject_toml_path, "r", encoding="utf-8") as toml_file:
        toml_data = toml.load(toml_file)

    # Get the [tool.poetry.dependencies] section
    dependencies = toml_data.get("tool", {}).get("poetry", {}).get("dependencies", {})

    return dependencies


def get_package_dependencies() -> Dict[str, Any]:
    """Returns a list of package dependencies."""
    package_manager = PackageManagerV1.from_dir(
        Path(
            os.environ.get(  # pylint: disable=no-member
                "PACKAGES_DIR", str(Path.cwd() / "packages")
            )
        )
    )
    dependencies: Dict[str, Dependency] = {}
    for package in package_manager.iter_dependency_tree():
        if package.package_type == PackageType.SERVICE:
            continue
        _dependencies = load_configuration(
            package_type=package.package_type,
            package_path=package_manager.package_path_from_package_id(
                package_id=package
            ),
        ).dependencies
        for key, value in _dependencies.items():
            if key not in dependencies:
                dependencies[key] = value
            else:
                if value.version == "":
                    continue
                if dependencies[key].version == "":
                    dependencies[key] = value
                elif value == dependencies[key]:
                    continue
                else:
                    print(
                        f"Non-matching dependency versions for {key}: {value} vs {dependencies[key]}"
                    )

    return {package.name: package.version for package in dependencies.values()}


def update_toml(
    new_package_dependencies: dict, pyproject_toml_path: str = "./pyproject.toml"
) -> None:
    """Update the pyproject.toml file with the new package dependencies."""

    # Load the pyproject.toml file
    with open(pyproject_toml_path, "r", encoding="utf-8") as toml_file:
        toml_data = toml.load(toml_file)

    toml_data["tool"]["poetry"]["dependencies"] = {
        key: value if value != "" else "*"
        for key, value in new_package_dependencies.items()
    }

    # Write the updated TOML content back to the file
    with open(pyproject_toml_path, "w", encoding="utf-8") as toml_file:
        toml.dump(toml_data, toml_file)


def update_tox_ini(
    new_package_dependencies: dict, tox_ini_path: str = "./tox.ini"
) -> None:
    """Update the tox.ini file with the new package dependencies."""
    new_package_dependencies.pop("python", None)
    for key, value in new_package_dependencies.items():
        if len(value) > 0 and "^" == value[0]:
            new_package_dependencies[key] = "==" + value[1:]
    with open(tox_ini_path, "r", encoding="utf-8") as file:
        lines = file.readlines()

    # Find the [deps-packages] section and replace the deps value
    start_line = None
    end_line = None
    for i, line in enumerate(lines):
        if line.strip() == "[deps-packages]":
            start_line = i + 1
            break

    if start_line is not None:
        for i in range(start_line, len(lines)):
            if lines[i].strip().startswith("["):
                end_line = i
                break
        else:
            end_line = len(lines)

        lines[start_line:end_line] = (
            ["deps =\n"]
            + ["    {[deps-tests]deps}\n"]
            + [f"    {key}{value}\n" for key, value in new_package_dependencies.items()]
            + ["\n"]
        )

    # Write the modified content back to the tox.ini file
    with open(tox_ini_path, "w", encoding="utf-8") as file:
        file.writelines(lines)


def check_for_no_changes(
    pyproject_toml_path: str = "./pyproject.toml", tox_ini_path: str = "./tox.ini"
) -> bool:
    """Check if there are any changes in the current repository."""

    # Check if there are any changes
    result = subprocess.run(  # pylint: disable=W1510 # nosec
        ["git", "diff", "--quiet", "--", pyproject_toml_path, tox_ini_path],
        capture_output=True,
        text=True,
    )

    return result.returncode == 0


if __name__ == "__main__":
    update = len(sys.argv[1:]) > 0
    package_dependencies = get_package_dependencies()
    # temp hack
    package_dependencies["requests"] = "==2.28.2"
    listed_package_dependencies = load_pyproject_toml()
    original_listed_package_dependencies = deepcopy(listed_package_dependencies)
    listed_package_dependencies.update(package_dependencies)
    update_toml(listed_package_dependencies)
    update_tox_ini(listed_package_dependencies)
    if not update and not check_for_no_changes():
        print(
            "There are mismatching package dependencies in the pyproject.toml file and the packages."
        )
        sys.exit(1)
