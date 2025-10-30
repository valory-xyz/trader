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

import atexit
import concurrent.futures
import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from eth_account import Account
from web3 import Web3

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
from packages.valory.skills.chatui_abci.handlers import (
    DEFAULT_HEADER,
    HTTP_CONTENT_TYPE_MAP,
)
from packages.valory.skills.chatui_abci.handlers import SrrHandler as BaseSrrHandler
from packages.valory.skills.chatui_abci.models import TradingStrategyUI
from packages.valory.skills.chatui_abci.prompts import TradingStrategy
from packages.valory.skills.decision_maker_abci.handlers import (
    HttpHandler as BaseHttpHandler,
)
from packages.valory.skills.decision_maker_abci.handlers import HttpMethod
from packages.valory.skills.decision_maker_abci.handlers import (
    IpfsHandler as BaseIpfsHandler,
)
from packages.valory.skills.funds_manager.behaviours import GET_FUNDS_STATUS_METHOD_NAME
from packages.valory.skills.funds_manager.models import FundRequirements
from packages.valory.skills.mech_interact_abci.handlers import (
    AcnHandler as BaseAcnHandler,
)
from packages.valory.skills.staking_abci.rounds import SynchronizedData
from packages.valory.skills.trader_abci.dialogues import HttpDialogue
from packages.valory.skills.trader_abci.models import TraderParams


TraderHandler = ABCIRoundHandler
SigningHandler = BaseSigningHandler
LedgerApiHandler = BaseLedgerApiHandler
ContractApiHandler = BaseContractApiHandler
TendermintHandler = BaseTendermintHandler
IpfsHandler = BaseIpfsHandler
AcnHandler = BaseAcnHandler
SrrHandler = BaseSrrHandler


PREDICT_AGENT_PROFILE_PATH = "predict-ui-build"
GNOSIS_CHAIN_NAME = "gnosis"
XDAI_ADDRESS = "0x0000000000000000000000000000000000000000"
WRAPPED_XDAI_ADDRESS = "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"
USDC_E_ADDRESS = "0x2a22f9c3b484c3629090FeED35F17Ff8F88f76F0"
GNOSIS_CHAIN_ID = 100
SLIPPAGE_FOR_SWAP = "0.003"  # 0.3%


class HttpHandler(BaseHttpHandler):
    """This implements the trader handler."""

    SUPPORTED_PROTOCOL = HttpMessage.protocol_id

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the handler."""
        super().__init__(**kwargs)
        self.handler_url_regex: str = ""
        self.routes: Dict[tuple, list] = {}

        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        atexit.register(self._executor_shutdown)

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

    @property
    def funds_status(self) -> FundRequirements:
        """Get the fund status."""
        return self.context.shared_state[GET_FUNDS_STATUS_METHOD_NAME]()

    @property
    def params(self) -> TraderParams:
        """Get the skill params."""
        return self.context.params

    def setup(self) -> None:
        """Setup the handler."""
        super().setup()

        # Only check funds if using X402
        if self.params.use_x402:
            self.executor.submit(self._ensure_sufficient_funds_for_x402_payments)

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

        funds_status_regex = rf"{hostname_regex}\/funds-status"

        static_files_regex = (
            rf"{hostname_regex}\/(.*)"  # New regex for serving static files
        )

        self.routes = {
            **self.routes,  # persisting routes from base class
            (HttpMethod.GET.value, HttpMethod.HEAD.value): [
                *(self.routes[(HttpMethod.GET.value, HttpMethod.HEAD.value)] or []),
                (agent_info_url_regex, self._handle_get_agent_info),
                (
                    funds_status_regex,
                    self._handle_get_funds_status,
                ),
                (
                    static_files_regex,  # Always keep this route last as it is a catch-all for static files
                    self._handle_get_static_file,
                ),
            ],
        }

        self.agent_profile_path = PREDICT_AGENT_PROFILE_PATH

    def _get_content_type(self, file_path: Path) -> str:
        """Get the appropriate content type header based on file extension."""
        return HTTP_CONTENT_TYPE_MAP.get(file_path.suffix.lower(), DEFAULT_HEADER)

    def _get_ui_trading_strategy(
        self, selected_value: Optional[str]
    ) -> TradingStrategyUI:
        """Get the UI trading strategy."""
        if selected_value is None:
            return TradingStrategyUI.BALANCED

        if selected_value == TradingStrategy.BET_AMOUNT_PER_THRESHOLD.value:
            return TradingStrategyUI.BALANCED
        elif selected_value == TradingStrategy.KELLY_CRITERION_NO_CONF.value:
            return TradingStrategyUI.RISKY
        else:
            # mike strat
            return TradingStrategyUI.RISKY

    def _handle_get_agent_info(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Handle a Http request of verb GET."""
        data = {
            "address": self.context.agent_address,
            "safe_address": self.synchronized_data.safe_contract_address,
            "agent_ids": self.agent_ids,
            "service_id": self.staking_synchronized_data.service_id,
            "trading_type": (
                self._get_ui_trading_strategy(
                    self.shared_state.chatui_config.trading_strategy
                )
            ).value,  # note the value call to not return the enum object
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

                # Get the appropriate content type
                content_type = self._get_content_type(file_path)

                # Send the file content as a response
                self._send_ok_response(
                    http_msg, http_dialogue, file_content, content_type
                )
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
            self._send_not_found_response(http_msg, http_dialogue)

    def _get_adjusted_funds_status(self) -> FundRequirements:
        """Deals with the edge case where there is xDAI deficit but wxDAI balance to cover it."""
        funds_status = copy.deepcopy(self.funds_status)
        try:
            safe_balances = funds_status[GNOSIS_CHAIN_NAME].accounts[
                self.synchronized_data.safe_contract_address
            ]

            xDAI_status = safe_balances.tokens[XDAI_ADDRESS]
            wxDAI_status = safe_balances.tokens[WRAPPED_XDAI_ADDRESS]
        except KeyError:
            self.context.logger.error(
                "Misconfigured fund requirements data. Can't apply adjustment."
            )
            return funds_status
        if xDAI_status.deficit != 0:
            xDAI_status.deficit = max(
                0, int(xDAI_status.deficit or 0) - int(wxDAI_status.balance or 0)
            )

        return funds_status

    def _handle_get_funds_status(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Handle a fund status request."""
        # Only check funds if using X402
        if self.params.use_x402:
            self.executor.submit(self._ensure_sufficient_funds_for_x402_payments)

        self._send_ok_response(
            http_msg,
            http_dialogue,
            self._get_adjusted_funds_status().get_response_body(),
        )

    def _get_eoa_account(self) -> Account:
        """Get EOA account from private key file."""
        default_ledger = self.context.default_ledger_id
        eoa_file = Path(self.context.data_dir) / f"{default_ledger}_private_key.txt"
        with eoa_file.open("r") as f:
            private_key = f.read().strip()
        return Account.from_key(private_key=private_key)

    def _get_web3_instance(self, chain: str) -> Optional[Web3]:
        """Get Web3 instance for the specified chain."""
        try:
            rpc_url = self.params.gnosis_ledger_rpc

            if not rpc_url:
                self.context.logger.warning(f"No RPC URL for {chain}")
                return None

            return Web3(Web3.HTTPProvider(rpc_url))
        except Exception as e:
            self.context.logger.error(f"Error creating Web3 instance: {str(e)}")
            return None

    def _check_usdc_balance(
        self, eoa_address: str, chain: str, usdc_address: str
    ) -> Optional[float]:
        """Check USDC balance using Web3 library."""
        try:
            w3 = self._get_web3_instance(chain)
            if not w3:
                return None

            # ERC20 ABI for balanceOf
            erc20_abi = [
                {
                    "constant": True,
                    "inputs": [{"name": "_owner", "type": "address"}],
                    "name": "balanceOf",
                    "outputs": [{"name": "balance", "type": "uint256"}],
                    "type": "function",
                }
            ]

            usdc_contract = w3.eth.contract(
                address=Web3.to_checksum_address(usdc_address), abi=erc20_abi
            )
            balance = usdc_contract.functions.balanceOf(
                Web3.to_checksum_address(eoa_address)
            ).call()
            return balance
        except Exception as e:
            self.context.logger.error(f"Error checking USDC balance: {str(e)}")
            return None

    def _get_lifi_quote_sync(
        self, eoa_address: str, chain: str, usdc_address: str, to_amount: str
    ) -> Optional[Dict]:
        """Get LiFi quote synchronously."""
        try:
            chain_id = GNOSIS_CHAIN_ID

            params = {
                "fromChain": chain_id,
                "toChain": chain_id,
                "fromToken": XDAI_ADDRESS,
                "toToken": usdc_address,
                "fromAddress": eoa_address,
                "toAddress": eoa_address,
                "toAmount": to_amount,
                "slippage": SLIPPAGE_FOR_SWAP,
                "integrator": "valory",
            }

            response = requests.get(
                self.params.lifi_quote_to_amount_url, params=params, timeout=30
            )

            if response.status_code == 200:
                return response.json()

            return None
        except Exception as e:
            self.context.logger.error(f"Error getting LiFi quote: {str(e)}")
            return None

    def _sign_and_submit_tx_web3(
        self, tx_data: Dict, chain: str, eoa_account: Account
    ) -> Optional[str]:
        """Sign and submit transaction using Web3."""
        try:
            w3 = self._get_web3_instance(chain)
            if not w3:
                return None

            signed_tx = eoa_account.sign_transaction(tx_data)

            tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            return tx_hash.hex()

        except Exception as e:
            self.context.logger.error(f"Error submitting transaction: {str(e)}")
            return None

    def _get_nonce_and_gas_web3(
        self, address: str, chain: str
    ) -> Tuple[Optional[int], Optional[int]]:
        """Get nonce and gas price using Web3."""
        try:
            w3 = self._get_web3_instance(chain)
            if not w3:
                return None, None

            nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(address))
            gas_price = w3.eth.gas_price

            return nonce, gas_price

        except Exception as e:
            self.context.logger.error(f"Error getting nonce/gas: {str(e)}")
            return None, None

    def _ensure_sufficient_funds_for_x402_payments(self) -> bool:
        """Ensure agent EOA has at sufficient funds for x402 requests payments"""
        self.context.logger.info("Checking USDC balance for x402 payments...")
        try:
            chain = GNOSIS_CHAIN_NAME
            eoa_account = self._get_eoa_account()
            eoa_address = eoa_account.address

            usdc_address = USDC_E_ADDRESS
            if not usdc_address:
                self.context.logger.error(f"No USDC address for {chain}")
                return False

            usdc_balance = self._check_usdc_balance(eoa_address, chain, usdc_address)

            if usdc_balance is None:
                self.context.logger.warning("Could not check USDC balance, skipping")
                return True

            threshold = self.params.x402_payment_requirements.get("threshold", 0)
            top_up = self.params.x402_payment_requirements.get("top_up", 0)

            if usdc_balance >= threshold:
                self.context.logger.info(
                    f"USDC balance sufficient: {usdc_balance} USDC (threshold: {threshold})"
                )
                return True

            self.context.logger.info(
                f"USDC balance ({usdc_balance}) < {threshold}, swapping xDAI to {top_up} USDC..."
            )

            top_up_usdc_amount = str(int(top_up))
            quote = self._get_lifi_quote_sync(
                eoa_address, chain, usdc_address, top_up_usdc_amount
            )
            if not quote:
                self.context.logger.error("Failed to get LiFi quote")
                return False

            tx_request: Optional[Dict] = quote.get("transactionRequest")
            if not tx_request:
                self.context.logger.error("No transactionRequest in quote")
                return False

            nonce, gas_price = self._get_nonce_and_gas_web3(eoa_address, chain)
            if nonce is None or gas_price is None:
                self.context.logger.error("Failed to get nonce or gas price")
                return False

            tx_value = (
                int(tx_request["value"], 16)
                if isinstance(tx_request["value"], str)
                else tx_request["value"]
            )
            tx_gas = (
                int(tx_request.get("gasLimit", "0x7a120"), 16)
                if isinstance(tx_request.get("gasLimit"), str)
                else self.params.default_gas_limit
            )

            tx_data = {
                "to": Web3.to_checksum_address(tx_request["to"]),
                "data": tx_request["data"],
                "value": tx_value,
                "gas": tx_gas,
                "gasPrice": gas_price,
                "nonce": nonce,
                "chainId": GNOSIS_CHAIN_ID,
            }

            self.context.logger.info(
                f"Signing and submitting tx: value={tx_data['value']}, gas={tx_data['gas']}, to={tx_data['to']}, data={tx_data['data'][:10]}..."
            )

            tx_hash = self._sign_and_submit_tx_web3(tx_data, chain, eoa_account)

            if not tx_hash:
                self.context.logger.error("Failed to submit transaction")
                return False

            self.context.logger.info(f"xDAI to USDC swap submitted: {tx_hash}")
            return True

        except Exception as e:
            self.context.logger.error(f"Error in _ensure_usdc_balance: {str(e)}")
            return False

    def teardown(self) -> None:
        """Tear down the handler."""
        super().teardown()
        self._executor_shutdown()

    def _executor_shutdown(self) -> None:
        """Shut down the executor."""
        self.executor.shutdown(wait=False, cancel_futures=True)
