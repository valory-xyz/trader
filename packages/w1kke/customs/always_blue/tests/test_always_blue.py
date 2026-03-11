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

"""Tests for the always_blue custom strategy."""

from packages.w1kke.customs.always_blue.always_blue import get_always_blue, run


class TestGetAlwaysBlue:
    """Tests for get_always_blue."""

    def test_returns_zero_bet(self) -> None:
        """Returns a zero bet amount."""
        result = get_always_blue()
        assert result["bet_amount"] == 0

    def test_returns_always_blue_message(self) -> None:
        """Returns the ALWAYS BLUE message."""
        result = get_always_blue()
        assert result["info"] == ["ALWAYS BLUE!"]


class TestRun:
    """Tests for run entry point."""

    def test_ignores_args(self) -> None:
        """Run ignores positional arguments."""
        result = run("arg1", "arg2")
        assert result["bet_amount"] == 0
        assert result["info"] == ["ALWAYS BLUE!"]

    def test_ignores_kwargs(self) -> None:
        """Run ignores keyword arguments."""
        result = run(some_key="some_value", another=123)
        assert result["bet_amount"] == 0
        assert result["info"] == ["ALWAYS BLUE!"]

    def test_no_args(self) -> None:
        """Run works with no arguments."""
        result = run()
        assert result == {"bet_amount": 0, "info": ["ALWAYS BLUE!"]}
