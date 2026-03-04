# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""Tests for the dialogues module of the chatui_abci skill."""

from unittest.mock import MagicMock

from aea.configurations.data_types import PublicId

import packages.valory.skills.chatui_abci.dialogues  # noqa: F401
from packages.valory.protocols.srr.dialogues import SrrDialogue as BaseSrrDialogue
from packages.valory.protocols.srr.message import SrrMessage
from packages.valory.skills.chatui_abci.dialogues import SrrDialogues


def test_import() -> None:
    """Test that the 'dialogues.py' Python module can be imported."""


class TestSrrDialogues:
    """Tests for the SrrDialogues class."""

    def test_init(self) -> None:
        """Test that SrrDialogues can be instantiated with a skill_context."""
        skill_context = MagicMock()
        skill_context.skill_id = PublicId.from_str("dummy/skill:0.1.0")
        dialogues = SrrDialogues(name="srr_dialogues", skill_context=skill_context)
        assert dialogues is not None

    def test_role_from_first_message(self) -> None:
        """The inner role_from_first_message returns SKILL role."""
        skill_context = MagicMock()
        skill_context.skill_id = PublicId.from_str("dummy/skill:0.1.0")
        dialogues = SrrDialogues(name="srr_dialogues", skill_context=skill_context)

        msg, dialogue = dialogues.create(
            counterparty="some_connection",
            performative=SrrMessage.Performative.REQUEST,
            payload="{}",
        )
        assert dialogue is not None
        assert dialogue.role == BaseSrrDialogue.Role.SKILL
