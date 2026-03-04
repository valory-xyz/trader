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

"""Tests for the general utils module of decision_maker_abci."""

import logging

from packages.valory.skills.decision_maker_abci.utils.general import suppress_logs


def test_suppress_logs_suppresses_logging() -> None:
    """Test that suppress_logs suppresses logging at the specified level."""
    logger = logging.getLogger("test_suppress")

    with suppress_logs(logging.CRITICAL):
        # Inside the context manager, logging should be disabled at CRITICAL level
        assert logging.root.manager.disable == logging.CRITICAL

    # After exiting, logging should be restored to the previous level
    assert logging.root.manager.disable != logging.CRITICAL or logging.root.manager.disable == 0


def test_suppress_logs_restores_previous_level() -> None:
    """Test that suppress_logs restores the previous logging level after exiting."""
    previous_level = logging.root.manager.disable

    with suppress_logs(logging.ERROR):
        assert logging.root.manager.disable == logging.ERROR

    assert logging.root.manager.disable == previous_level


def test_suppress_logs_default_level() -> None:
    """Test that suppress_logs uses CRITICAL as the default level."""
    previous_level = logging.root.manager.disable

    with suppress_logs():
        assert logging.root.manager.disable == logging.CRITICAL

    assert logging.root.manager.disable == previous_level


def test_suppress_logs_restores_on_exception() -> None:
    """Test that suppress_logs restores the previous logging level even if an exception occurs."""
    previous_level = logging.root.manager.disable

    try:
        with suppress_logs(logging.WARNING):
            assert logging.root.manager.disable == logging.WARNING
            raise ValueError("test error")
    except ValueError:
        pass

    assert logging.root.manager.disable == previous_level


def test_suppress_logs_with_custom_level() -> None:
    """Test that suppress_logs works with a custom logging level."""
    previous_level = logging.root.manager.disable

    with suppress_logs(logging.WARNING):
        assert logging.root.manager.disable == logging.WARNING

    assert logging.root.manager.disable == previous_level
