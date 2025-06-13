# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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


"""This module contains the handlers for the 'trader_abci' skill."""

import json
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict, List, Union
from urllib.parse import urlparse

from packages.valory.protocols.http.message import HttpMessage
from packages.valory.skills.abstract_round_abci.handlers import ABCIRoundHandler
from packages.valory.skills.abstract_round_abci.handlers import (
    ContractApiHandler as BaseContractApiHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    LedgerApiHandler as BaseLedgerApiHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    SigningHandler as BaseSigningHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    TendermintHandler as BaseTendermintHandler,
)
from packages.valory.skills.decision_maker_abci.handlers import (
    HttpHandler as BaseHttpHandler,
)
from packages.valory.skills.decision_maker_abci.handlers import HttpMethod
from packages.valory.skills.decision_maker_abci.handlers import (
    IpfsHandler as BaseIpfsHandler,
)
from packages.valory.skills.mech_interact_abci.handlers import (
    AcnHandler as BaseAcnHandler,
)
from packages.valory.skills.staking_abci.rounds import SynchronizedData
from packages.valory.skills.trader_abci.dialogues import HttpDialogue


TraderHandler = ABCIRoundHandler
SigningHandler = BaseSigningHandler
LedgerApiHandler = BaseLedgerApiHandler
ContractApiHandler = BaseContractApiHandler
TendermintHandler = BaseTendermintHandler
IpfsHandler = BaseIpfsHandler
AcnHandler = BaseAcnHandler


PREDICT_AGENT_PROFILE_PATH = "predict-ui-build"


class HttpHandler(BaseHttpHandler):
    """This implements the trader handler."""

    SUPPORTED_PROTOCOL = HttpMessage.protocol_id

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the handler."""
        super().__init__(**kwargs)
        self.handler_url_regex: str = ""
        self.routes: Dict[tuple, list] = {}
        self.json_content_header: str = ""

    @property
    def staking_synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return SynchronizedData(
            db=self.context.state.round_sequence.latest_synchronized_data.db
        )

    @property
    def agent_ids(self) -> List[int]:
        """Get the agent ids."""
        return json.loads(self.staking_synchronized_data.agent_ids)

    def setup(self) -> None:
        """Setup the handler."""
        super().setup()
        config_uri_base_hostname = urlparse(
            self.context.params.service_endpoint
        ).hostname

        propel_uri_base_hostname = (
            r"https?:\/\/[a-zA-Z0-9]{16}.agent\.propel\.(staging\.)?autonolas\.tech"
        )

        local_ip_regex = r"192\.168(\.\d{1,3}){2}"

        # Route regexes
        hostname_regex = rf".*({config_uri_base_hostname}|{propel_uri_base_hostname}|{local_ip_regex}|localhost|127.0.0.1|0.0.0.0)(:\d+)?"
        self.handler_url_regex = rf"{hostname_regex}\/.*"

        agent_info_url_regex = rf"{hostname_regex}\/agent-info"
        static_files_regex = (
            rf"{hostname_regex}\/(.*)"  # New regex for serving static files
        )

        self.routes = {
            **self.routes,  # persisting routes from base class
            (HttpMethod.GET.value, HttpMethod.HEAD.value): [
                *(self.routes[(HttpMethod.GET.value, HttpMethod.HEAD.value)] or []),
                (agent_info_url_regex, self._handle_get_agent_info),
                (
                    static_files_regex,
                    self._handle_get_static_file,
                ),
            ],
        }

        self.json_content_header = "Content-Type: application/json\n"
        self.html_content_header = "Content-Type: text/html\n"

        self.agent_profile_path = PREDICT_AGENT_PROFILE_PATH

    def _send_ok_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        data: Union[str, Dict, List, bytes],
    ) -> None:
        """Send an OK response with the provided data"""
        headers = (
            self.json_content_header
            if isinstance(data, (dict, list))
            else self.html_content_header
        )
        headers += http_msg.headers

        # Convert dictionary or list to JSON string
        if isinstance(data, (dict, list)):
            data = json.dumps(data)

        http_response = http_dialogue.reply(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=HTTPStatus.OK.value,
            status_text="Success",
            headers=headers,
            body=data.encode("utf-8") if isinstance(data, str) else data,
        )

        # Send response
        self.context.logger.info("Responding with: {}".format(http_response))
        self.context.outbox.put_message(message=http_response)

    def _handle_get_agent_info(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Handle a Http request of verb GET."""
        data = {
            "address": self.context.agent_address,
            "safe_address": self.synchronized_data.safe_contract_address,
            "agent_ids": self.agent_ids,
            "service_id": self.staking_synchronized_data.service_id,
        }
        self.context.logger.info(f"Sending agent info: {data=}")
        self._send_ok_response(http_msg, http_dialogue, data)

    def _handle_get_static_file(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """
        Handle a HTTP GET request for a static file.

        Implementation borrowed from:
        https://github.com/valory-xyz/optimus/blob/262f14843f171942995acfae8bea85d76fa82926/packages/valory/skills/optimus_abci/handlers.py#L349-L385

        :param http_msg: the HTTP message
        :param http_dialogue: the HTTP dialogue
        """
        try:
            # Extract the requested path from the URL
            requested_path = urlparse(http_msg.url).path.lstrip("/")

            # Construct the file path
            file_path = Path(
                Path(__file__).parent, self.agent_profile_path, requested_path
            )
            # If the file exists and is a file, send it as a response
            if file_path.exists() and file_path.is_file():
                with open(file_path, "rb") as file:
                    file_content = file.read()

                # Send the file content as a response
                self._send_ok_response(http_msg, http_dialogue, file_content)
            else:
                # If the file doesn't exist or is not a file, return the index.html file
                with open(
                    Path(Path(__file__).parent, self.agent_profile_path, "index.html"),
                    "r",
                    encoding="utf-8",
                ) as file:
                    index_html = file.read()

                # Send the HTML response
                self._send_ok_response(http_msg, http_dialogue, index_html)
        except FileNotFoundError:
            self._handle_not_found(http_msg, http_dialogue)
