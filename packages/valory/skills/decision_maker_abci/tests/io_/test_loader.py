# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2026 Valory AG
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

"""Tests for the loader module of decision_maker_abci."""

import pytest

from packages.valory.skills.decision_maker_abci.io_.loader import ComponentPackageLoader


class TestComponentPackageLoader:
    """Tests for the ComponentPackageLoader class."""

    def test_load_missing_component_yaml_raises(self) -> None:
        """Test that load raises ValueError if component.yaml is missing."""
        serialized_objects = {"entry_point.py": "print('hello')"}
        with pytest.raises(
            ValueError,
            match="The package MUST contain a component.yaml.",
        ):
            ComponentPackageLoader.load(serialized_objects)

    def test_load_missing_entry_point_key_raises(self) -> None:
        """Test that load raises ValueError if entry_point key is missing from component.yaml."""
        serialized_objects = {
            "component.yaml": "callable: run\n",
        }
        with pytest.raises(
            ValueError,
            match="The component.yaml file MUST contain the 'entry_point' and 'callable' keys.",
        ):
            ComponentPackageLoader.load(serialized_objects)

    def test_load_missing_callable_key_raises(self) -> None:
        """Test that load raises ValueError if callable key is missing from component.yaml."""
        serialized_objects = {
            "component.yaml": "entry_point: script.py\n",
        }
        with pytest.raises(
            ValueError,
            match="The component.yaml file MUST contain the 'entry_point' and 'callable' keys.",
        ):
            ComponentPackageLoader.load(serialized_objects)

    def test_load_entry_point_file_not_present_raises(self) -> None:
        """Test that load raises ValueError if the entry_point file is not in the package."""
        serialized_objects = {
            "component.yaml": "entry_point: script.py\ncallable: run\n",
        }
        with pytest.raises(
            ValueError,
            match="script.py is not present in the component package.",
        ):
            ComponentPackageLoader.load(serialized_objects)

    def test_load_successful(self) -> None:
        """Test successful loading of a component package."""
        entry_point_code = "def run():\n    pass\n"
        serialized_objects = {
            "component.yaml": "entry_point: script.py\ncallable: run\n",
            "script.py": entry_point_code,
        }
        result = ComponentPackageLoader.load(serialized_objects)  # type: ignore[arg-type]
        component_yaml, entry_point, callable_method = result

        assert component_yaml["entry_point"] == "script.py"  # type: ignore[index]
        assert component_yaml["callable"] == "run"  # type: ignore[index]
        assert entry_point == entry_point_code
        assert callable_method == "run"

    def test_load_returns_tuple(self) -> None:
        """Test that load returns a tuple of (component_yaml, entry_point, callable)."""
        serialized_objects = {
            "component.yaml": "entry_point: my_module.py\ncallable: execute\n",
            "my_module.py": "def execute():\n    return 42\n",
        }
        result = ComponentPackageLoader.load(serialized_objects)  # type: ignore[arg-type]
        assert isinstance(result, tuple)
        assert len(result) == 3
