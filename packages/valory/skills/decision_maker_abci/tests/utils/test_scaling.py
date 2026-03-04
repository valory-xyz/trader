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

"""Tests for the scaling utils module of decision_maker_abci."""

import pytest

from packages.valory.skills.decision_maker_abci.utils.scaling import (
    min_max,
    min_max_scale,
    scale_value,
)


class TestMinMax:
    """Tests for the min_max function."""

    def test_min_max_empty_list_raises(self) -> None:
        """Test that min_max raises ValueError for an empty list."""
        with pytest.raises(ValueError, match="The list is empty."):
            min_max([])

    def test_min_max_single_element(self) -> None:
        """Test min_max with a single element."""
        result = min_max([5.0])
        assert result == (5.0, 5.0)

    def test_min_max_two_elements(self) -> None:
        """Test min_max with two elements."""
        result = min_max([3.0, 7.0])
        assert result == (3.0, 7.0)

    def test_min_max_multiple_elements(self) -> None:
        """Test min_max with multiple elements."""
        result = min_max([3.0, 1.0, 5.0, 2.0, 4.0])
        assert result == (1.0, 5.0)

    def test_min_max_all_same(self) -> None:
        """Test min_max when all elements are the same."""
        result = min_max([3.0, 3.0, 3.0])
        assert result == (3.0, 3.0)

    def test_min_max_negative_values(self) -> None:
        """Test min_max with negative values."""
        result = min_max([-5.0, -1.0, -3.0])
        assert result == (-5.0, -1.0)

    def test_min_max_mixed_values(self) -> None:
        """Test min_max with mixed positive and negative values."""
        result = min_max([-2.0, 0.0, 3.0])
        assert result == (-2.0, 3.0)

    def test_min_max_descending_order(self) -> None:
        """Test min_max with values in descending order."""
        result = min_max([10.0, 8.0, 6.0, 4.0, 2.0])
        assert result == (2.0, 10.0)


class TestScaleValue:
    """Tests for the scale_value function."""

    def test_scale_value_midpoint(self) -> None:
        """Test scaling the midpoint value."""
        result = scale_value(5.0, (0.0, 10.0))
        assert result == 0.5

    def test_scale_value_min_bound(self) -> None:
        """Test scaling the minimum bound value."""
        result = scale_value(0.0, (0.0, 10.0))
        assert result == 0.0

    def test_scale_value_max_bound(self) -> None:
        """Test scaling the maximum bound value."""
        result = scale_value(10.0, (0.0, 10.0))
        assert result == 1.0

    def test_scale_value_custom_scale_bounds(self) -> None:
        """Test scaling with custom scale bounds."""
        result = scale_value(5.0, (0.0, 10.0), (0.0, 100.0))
        assert result == 50.0

    def test_scale_value_negative_range(self) -> None:
        """Test scaling with negative source range."""
        result = scale_value(0.0, (-10.0, 10.0))
        assert result == 0.5

    def test_scale_value_custom_target_negative(self) -> None:
        """Test scaling to a negative target range."""
        result = scale_value(5.0, (0.0, 10.0), (-1.0, 1.0))
        assert result == 0.0


class TestMinMaxScale:
    """Tests for the min_max_scale function."""

    def test_min_max_scale_basic(self) -> None:
        """Test basic min-max scaling."""
        result = min_max_scale([1.0, 2.0, 3.0, 4.0, 5.0])
        assert result == [0.0, 0.25, 0.5, 0.75, 1.0]

    def test_min_max_scale_custom_bounds(self) -> None:
        """Test min-max scaling with custom bounds."""
        result = min_max_scale([1.0, 2.0, 3.0], (0.0, 10.0))
        assert result == [0.0, 5.0, 10.0]

    def test_min_max_scale_empty_list_raises(self) -> None:
        """Test that min_max_scale raises ValueError for empty list."""
        with pytest.raises(ValueError, match="The list is empty."):
            min_max_scale([])

    def test_min_max_scale_two_elements(self) -> None:
        """Test min-max scaling with two elements."""
        result = min_max_scale([10.0, 20.0])
        assert result == [0.0, 1.0]

    def test_min_max_scale_negative_values(self) -> None:
        """Test min-max scaling with negative values."""
        result = min_max_scale([-10.0, 0.0, 10.0])
        assert result == [0.0, 0.5, 1.0]
