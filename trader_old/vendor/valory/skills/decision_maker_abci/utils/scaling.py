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


"""This package contains helpers for scaling operations."""


from typing import List, Tuple


def min_max(li: List[float]) -> Tuple[float, float]:
    """Get the min and max of a list."""
    if not li:
        raise ValueError("The list is empty.")

    min_ = max_ = li[0]

    for num in li[1:]:
        if num < min_:
            min_ = num
        elif num > max_:
            max_ = num

    return min_, max_


def scale_value(
    value: float,
    min_max_bounds: Tuple[float, float],
    scale_bounds: Tuple[float, float] = (0, 1),
) -> float:
    """Perform min-max scaling on a value."""
    min_, max_ = min_max_bounds
    current_range = max_ - min_
    # normalize between 0-1
    std = (value - min_) / current_range
    # scale between min_bound and max_bound
    min_bound, max_bound = scale_bounds
    target_range = max_bound - min_bound
    return std * target_range + min_bound


def min_max_scale(
    li: List[float],
    scale_bounds: Tuple[float, float] = (0, 1),
) -> List[float]:
    """Perform min-max scaling on a list of values."""
    min_max_ = min_max(li)
    return [scale_value(value, min_max_, scale_bounds) for value in li]
