# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2022 Valory AG
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

"""This module contains the handler for the 'abci' skill."""
import json
import re
from enum import Enum
from typing import Optional, Tuple, Callable, Dict, cast, Union, List
from urllib.parse import urlparse

from aea.configurations.data_types import PublicId
from aea.protocols.base import Message

from packages.valory.connections.http_client.connection import HttpDialogues, HttpDialogue
from packages.valory.connections.http_server.connection import (
    PUBLIC_ID as HTTP_SERVER_PUBLIC_ID,
)
from packages.valory.protocols.http import HttpMessage
from packages.valory.skills.abstract_round_abci.handlers import (
    HttpHandler as BaseHttpHandler,
)

OK_CODE = 200
BAD_REQUEST_CODE = 400
UNAUTHORIZED_CODE = 401
UNPROCESSABLE_ENTITY_CODE = 422


class HttpMethod(Enum):
    """Http methods"""

    GET = "get"
    HEAD = "head"
    POST = "post"


class HttpHandler(BaseHttpHandler):
    """The HTTP response handler."""

    SUPPORTED_PROTOCOL: Optional[PublicId] = HttpMessage.protocol_id

    def setup(self) -> None:
        """Implement the setup."""

        # Custom hostname (set via params)
        service_endpoint_base = urlparse(
            self.context.params.service_endpoint_base
        ).hostname

        # Propel hostname regex
        propel_uri_base_hostname = (
            r"https?:\/\/[a-zA-Z0-9]{16}.agent\.propel\.(staging\.)?autonolas\.tech"
        )

        # Route regexes
        hostname_regex = rf".*({service_endpoint_base}|{propel_uri_base_hostname}|localhost|127.0.0.1|0.0.0.0)(:\d+)?"
        self.handler_url_regex = rf"{hostname_regex}\/update_params\/?$"

        # Routes
        self.routes = {
            (HttpMethod.POST.value,): [(self.handler_url_regex, self._update_params),],
            (HttpMethod.GET.value, HttpMethod.HEAD.value): [],
        }

        self.json_content_header = "Content-Type: application/json\n"

    def _get_handler(self, url: str, method: str) -> Tuple[Optional[Callable], Dict]:
        """Check if an url is meant to be handled in this handler

        We expect url to match the pattern {hostname}/.*,
        where hostname is allowed to be localhost, 127.0.0.1 or the token_uri_base's hostname.
        Examples:
            localhost:8000/0
            127.0.0.1:8000/100
            https://pfp.staging.autonolas.tech/45
            http://pfp.staging.autonolas.tech/120

        :param url: the url to check
        :param method: the http method
        :returns: the handling method if the message is intended to be handled by this handler, None otherwise, and the regex captures
        """
        # Check base url
        if not re.match(self.handler_url_regex, url):
            self.context.logger.info(
                f"The url {url} does not match the HttpHandler's pattern"
            )
            return None, {}

        # Check if there is a route for this request
        for methods, routes in self.routes.items():
            if method not in methods:
                continue

            for route in routes:  # type: ignore
                # Routes are tuples like (route_regex, handle_method)
                m = re.match(route[0], url)
                if m:
                    return route[1], m.groupdict()

        # No route found
        self.context.logger.info(
            f"The message [{method}] {url} is intended for the HttpHandler but did not match any valid pattern"
        )
        return self._handle_bad_request, {}

    def handle(self, message: Message) -> None:
        """
        Implement the reaction to an envelope.

        :param message: the message
        """
        http_msg = cast(HttpMessage, message)

        # Check if this is a request sent from the http_server skill
        if (
            http_msg.performative != HttpMessage.Performative.REQUEST
            or message.sender != str(HTTP_SERVER_PUBLIC_ID.without_hash())
        ):
            super().handle(message)
            return

        # Check if this message is for this skill. If not, send to super()
        handler, kwargs = self._get_handler(http_msg.url, http_msg.method)
        if not handler:
            super().handle(message)
            return

        # Retrieve dialogues
        http_dialogues = cast(HttpDialogues, self.context.http_dialogues)
        http_dialogue = cast(HttpDialogue, http_dialogues.update(http_msg))

        # Invalid message
        if http_dialogue is None:
            self.context.logger.info(
                "Received invalid http message={}, unidentified dialogue.".format(
                    http_msg
                )
            )
            return

        # Handle message
        self.context.logger.info(
            "Received http request with method={}, url={} and body={!r}".format(
                http_msg.method,
                http_msg.url,
                http_msg.body,
            )
        )
        handler(http_msg, http_dialogue, **kwargs)

    def _handle_bad_request(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """
        Handle a Http bad request.

        :param http_msg: the http message
        :param http_dialogue: the http dialogue
        """
        http_response = http_dialogue.reply(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=BAD_REQUEST_CODE,
            status_text="Bad request",
            headers=http_msg.headers,
            body=b"",
        )

        # Send response
        self.context.logger.info("Responding with: {}".format(http_response))
        self.context.outbox.put_message(message=http_response)

    def _send_wrong_parameter(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        param: str,
    ) -> None:
        http_response = http_dialogue.reply(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=UNPROCESSABLE_ENTITY_CODE,
            status_text="Unprocessable Entity",
            headers=f"{self.json_content_header}{http_msg.headers}",
            body=f"No parameter {param}.".encode("utf-8"),
        )

        # Send response
        self.context.logger.info("Responding with: {}".format(http_response))
        self.context.outbox.put_message(message=http_response)

    def _send_wrong_secret_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
    ) -> None:
        http_response = http_dialogue.reply(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=UNAUTHORIZED_CODE,
            status_text="Unauthorized",
            headers=f"{self.json_content_header}{http_msg.headers}",
            body=b"Incorrect secret.",
        )

        # Send response
        self.context.logger.info("Responding with: {}".format(http_response))
        self.context.outbox.put_message(message=http_response)

    def _send_ok_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        data: Union[Dict, List],
    ) -> None:
        """Send an OK response with the provided data"""
        http_response = http_dialogue.reply(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=OK_CODE,
            status_text="Success",
            headers=f"{self.json_content_header}{http_msg.headers}",
            body=json.dumps(data).encode("utf-8"),
        )

        # Send response
        self.context.logger.info("Responding with: {}".format(http_response))
        self.context.outbox.put_message(message=http_response)

    def _update_params(self, http_msg: HttpMessage, http_dialogue: HttpDialogue) -> None:
        self.context.logger.info("Received update command.")
        try:
            body = json.loads(http_msg.body.decode("utf-8"))
        except:
            return self._handle_bad_request(http_msg, http_dialogue)
        secret = body["secret"]
        if secret != self.context.params.update_secret:  # only who is allowed
            return self._send_wrong_secret_response(http_msg, http_dialogue)
        old = {}
        for k, v in body["update_params"].items():
            try:
                old[k] = getattr(self.context.params, k)
            except:
                return self._send_wrong_parameter(http_msg, http_dialogue, k)
        new = {}
        self.context.params.__dict__["_frozen"] = False
        for k, v in body["update_params"].items():
            setattr(self.context.params, k, v)
            new[k] = v
            self.context.params.__dict__["_frozen"] = True
        self._send_ok_response(http_msg, http_dialogue, {"old": old, "new": new})
