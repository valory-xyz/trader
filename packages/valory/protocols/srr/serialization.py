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

"""Serialization module for srr protocol."""

# pylint: disable=too-many-statements,too-many-locals,no-member,too-few-public-methods,redefined-builtin
from typing import Any, Dict, cast

from aea.mail.base_pb2 import DialogueMessage  # type: ignore
from aea.mail.base_pb2 import Message as ProtobufMessage  # type: ignore
from aea.protocols.base import Message  # type: ignore
from aea.protocols.base import Serializer  # type: ignore

from packages.valory.protocols.srr import srr_pb2  # type: ignore
from packages.valory.protocols.srr.message import SrrMessage  # type: ignore


class SrrSerializer(Serializer):
    """Serialization for the 'srr' protocol."""

    @staticmethod
    def encode(msg: Message) -> bytes:
        """
        Encode a 'Srr' message into bytes.

        :param msg: the message object.
        :return: the bytes.
        """
        msg = cast(SrrMessage, msg)
        message_pb = ProtobufMessage()
        dialogue_message_pb = DialogueMessage()
        srr_msg = srr_pb2.SrrMessage()  # type: ignore

        dialogue_message_pb.message_id = msg.message_id
        dialogue_reference = msg.dialogue_reference
        dialogue_message_pb.dialogue_starter_reference = dialogue_reference[0]
        dialogue_message_pb.dialogue_responder_reference = dialogue_reference[1]
        dialogue_message_pb.target = msg.target

        performative_id = msg.performative
        if performative_id == SrrMessage.Performative.REQUEST:
            performative = srr_pb2.SrrMessage.Request_Performative()  # type: ignore
            payload = msg.payload
            performative.payload = payload
            srr_msg.request.CopyFrom(performative)
        elif performative_id == SrrMessage.Performative.RESPONSE:
            performative = srr_pb2.SrrMessage.Response_Performative()  # type: ignore
            payload = msg.payload
            performative.payload = payload
            error = msg.error
            performative.error = error
            srr_msg.response.CopyFrom(performative)
        else:
            raise ValueError("Performative not valid: {}".format(performative_id))

        dialogue_message_pb.content = srr_msg.SerializeToString()

        message_pb.dialogue_message.CopyFrom(dialogue_message_pb)
        message_bytes = message_pb.SerializeToString()
        return message_bytes

    @staticmethod
    def decode(obj: bytes) -> Message:
        """
        Decode bytes into a 'Srr' message.

        :param obj: the bytes object.
        :return: the 'Srr' message.
        """
        message_pb = ProtobufMessage()
        srr_pb = srr_pb2.SrrMessage()  # type: ignore
        message_pb.ParseFromString(obj)
        message_id = message_pb.dialogue_message.message_id
        dialogue_reference = (
            message_pb.dialogue_message.dialogue_starter_reference,
            message_pb.dialogue_message.dialogue_responder_reference,
        )
        target = message_pb.dialogue_message.target

        srr_pb.ParseFromString(message_pb.dialogue_message.content)
        performative = srr_pb.WhichOneof("performative")
        performative_id = SrrMessage.Performative(str(performative))
        performative_content = dict()  # type: Dict[str, Any]
        if performative_id == SrrMessage.Performative.REQUEST:
            payload = srr_pb.request.payload
            performative_content["payload"] = payload
        elif performative_id == SrrMessage.Performative.RESPONSE:
            payload = srr_pb.response.payload
            performative_content["payload"] = payload
            error = srr_pb.response.error
            performative_content["error"] = error
        else:
            raise ValueError("Performative not valid: {}.".format(performative_id))

        return SrrMessage(
            message_id=message_id,
            dialogue_reference=dialogue_reference,
            target=target,
            performative=performative,
            **performative_content
        )
