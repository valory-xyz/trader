#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2024 Valory AG
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


# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 valory
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

"""Test messages module for srr protocol."""

# pylint: disable=too-many-statements,too-many-locals,no-member,too-few-public-methods,redefined-builtin
from typing import List

from aea.test_tools.test_protocol import BaseProtocolMessagesTestCase

from packages.valory.protocols.srr.message import SrrMessage


class TestMessageSrr(BaseProtocolMessagesTestCase):
    """Test for the 'srr' protocol message."""

    MESSAGE_CLASS = SrrMessage

    def build_messages(self) -> List[SrrMessage]:  # type: ignore[override]
        """Build the messages to be used for testing."""
        return [
            SrrMessage(
                performative=SrrMessage.Performative.REQUEST,
                payload="some str",
            ),
            SrrMessage(
                performative=SrrMessage.Performative.RESPONSE,
                payload="some str",
                error=True,
            ),
        ]

    def build_inconsistent(self) -> List[SrrMessage]:  # type: ignore[override]
        """Build inconsistent messages to be used for testing."""
        return [
            SrrMessage(
                performative=SrrMessage.Performative.REQUEST,
                # skip content: payload
            ),
            SrrMessage(
                performative=SrrMessage.Performative.RESPONSE,
                # skip content: payload
                error=True,
            ),
        ]
