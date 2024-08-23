# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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
"""This module contains the tests for the loader for the decision maker abci."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

import pytest

from packages.valory.skills.decision_maker_abci.io_.loader import ComponentPackageLoader


@dataclass
class LoaderTestCase:
    """Test case for Loader."""

    name: str
    serialized_objects: Dict
    error: Optional[Any]


class TestComponentPackageLoader:
    """Test ComponentPackageLoader."""

    @pytest.mark.parametrize(
        "test_case",
        [
            LoaderTestCase(
                name="happy path",
                serialized_objects={
                    "component.yaml": """
                    entry_point: entry_point.py
                    callable: dummy_callable
                    """,
                    "entry_point.py": "dummy_function()",
                },
                error=None,
            ),
            LoaderTestCase(
                name="missing component.yaml",
                serialized_objects={"entry_point.py": "dummy_function()"},
                error="Invalid component package. The package MUST contain a component.yaml.",
            ),
            LoaderTestCase(
                name="missing entry_point",
                serialized_objects={
                    "component.yaml": """
                    not_entry_point: none
                    """,
                    "entry_point.py": "dummy_function()",
                },
                error="Invalid component package. The component.yaml file MUST contain the 'entry_point' and 'callable' keys.",
            ),
            LoaderTestCase(
                name="happy path",
                serialized_objects={
                    "component.yaml": """
                        entry_point: entry_point.py
                        callable: dummy_callable
                        """,
                },
                error="Invalid component package. entry_point.py is not present in the component package.",
            ),
        ],
    )
    def test_load(self, test_case: LoaderTestCase) -> None:
        """Test load."""

        if test_case.error:
            with pytest.raises(ValueError, match=test_case.error):
                ComponentPackageLoader.load(test_case.serialized_objects)
        else:
            loader = ComponentPackageLoader.load(test_case.serialized_objects)

            assert loader == (
                {"entry_point": "entry_point.py", "callable": "dummy_callable"},
                "dummy_function()",
                "dummy_callable",
            )
