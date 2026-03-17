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

"""Tests for the payloads module of the chatui_abci skill."""

from packages.valory.skills.chatui_abci.payloads import ChatuiPayload


def test_chatui_payload() -> None:
    """Test ChatuiPayload with vote=True."""
    payload = ChatuiPayload(sender="sender", vote=True)
    assert payload.vote is True
    assert payload.data == {"vote": True}
    assert ChatuiPayload.from_json(payload.json) == payload


def test_chatui_payload_false_vote() -> None:
    """Test ChatuiPayload with vote=False."""
    payload = ChatuiPayload(sender="sender", vote=False)
    assert payload.vote is False
    assert payload.data == {"vote": False}
    assert ChatuiPayload.from_json(payload.json) == payload
