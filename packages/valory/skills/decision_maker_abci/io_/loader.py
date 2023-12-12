# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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
"""This module contains helper classes for IPFS interaction."""
from typing import Dict

import yaml

from packages.valory.skills.abstract_round_abci.io_.store import SupportedObjectType


class ComponentPackageLoader:
    """Component package loader."""

    @staticmethod
    def load(serialized_objects: Dict[str, str]) -> SupportedObjectType:
        """
        Load a custom component package.

        :param serialized_objects: the serialized objects.
        :return: the component.yaml, entry_point.py and callable as tuple.
        """
        # the package MUST contain a component.yaml file
        if "component.yaml" not in serialized_objects:
            raise ValueError(
                "Invalid component package. "
                "The package MUST contain a component.yaml."
            )

        # load the component.yaml file
        component_yaml = yaml.safe_load(serialized_objects["component.yaml"])
        if "entry_point" not in component_yaml or "callable" not in component_yaml:
            raise ValueError(
                "Invalid component package. "
                "The component.yaml file MUST contain the 'entry_point' and 'callable' keys."
            )

        # the name of the script that needs to be executed
        entry_point_name = component_yaml["entry_point"]

        # load the script
        if entry_point_name not in serialized_objects:
            raise ValueError(
                f"Invalid component package. "
                f"{entry_point_name} is not present in the component package."
            )
        entry_point = serialized_objects[entry_point_name]

        # the method that needs to be called
        callable_method = component_yaml["callable"]

        return component_yaml, entry_point, callable_method
