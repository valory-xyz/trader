# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2026 Valory AG
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
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from aea_ledger_ethereum.ethereum import EthereumCrypto
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
from packages.valory.skills.agent_performance_summary_abci.handlers import (
    DEFAULT_HEADER,
)
from packages.valory.skills.chatui_abci.handlers import HTTP_CONTENT_TYPE_MAP
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


# UI Build Configuration
UI_BUILD_BASE_DIR = "ui-build"
OMENSTRAT_UI_SUBDIR = "omenstrat"
POLYSTRAT_UI_SUBDIR = "polystrat"

# Gnosis Chain Configuration
GNOSIS_CHAIN_NAME = "gnosis"
GNOSIS_CHAIN_ID = 100
GNOSIS_NATIVE_TOKEN_ADDRESS = (
    "0x0000000000000000000000000000000000000000"  # nosec: B105
)
GNOSIS_WRAPPED_NATIVE_ADDRESS = "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"
GNOSIS_USDC_E_ADDRESS = "0xDDAfbb505ad214D7b80b1f830fcCc89B60fb7A83"

# Polygon Chain Configuration
POLYGON_CHAIN_NAME = "polygon"
POLYGON_CHAIN_ID = 137
POLYGON_NATIVE_TOKEN_ADDRESS = (
    "0x0000000000000000000000000000000000000000"  # nosec: B105
)
POLYGON_WRAPPED_NATIVE_ADDRESS = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"
POLYGON_USDC_E_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
POLYGON_USDC_ADDRESS = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
POLYGON_POL_ADDRESS = "0x0000000000000000000000000000000000001010"

TRADING_STRATEGY_EXPLANATION = {
    "risky": "Dynamic trade sizes based on the pre-existing market conditions, agent confidence, and available agent funds. This more complex strategy allows both agent sizing bias, and market outcome to determine payout and loss and may be subject to greater volatility.",
    "balanced": "A steady, conservative fixed trade size on markets independent of agent confidence. Ensures a fixed cost basis and insulates outcomes from agent sizing logic instead allowing wins, loss, and market odds at time of participation to determine ROI.",
}

# Rate limiting for CoinGecko API: cache for 2 hours to avoid hitting rate limits
COINGECKO_RATE_CACHE_SECONDS = 7200  # 2 hours


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

        # Cache for POL to USDC conversion rate
        self._pol_usdc_rate: Optional[float] = None  # Rate: 1 POL = X USDC
        self._pol_usdc_rate_timestamp: float = 0.0

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

    def _get_chain_config(self) -> Dict[str, Any]:
        """Get chain configuration based on is_running_on_polymarket parameter."""
        if self.params.is_running_on_polymarket:
            return {
                "chain_name": POLYGON_CHAIN_NAME,
                "chain_id": POLYGON_CHAIN_ID,
                "native_token_address": POLYGON_NATIVE_TOKEN_ADDRESS,
                "wrapped_native_address": POLYGON_WRAPPED_NATIVE_ADDRESS,
                "usdc_e_address": POLYGON_USDC_E_ADDRESS,
                "usdc_address": POLYGON_USDC_ADDRESS,
            }

        return {
            "chain_name": GNOSIS_CHAIN_NAME,
            "chain_id": GNOSIS_CHAIN_ID,
            "native_token_address": GNOSIS_NATIVE_TOKEN_ADDRESS,
            "wrapped_native_address": GNOSIS_WRAPPED_NATIVE_ADDRESS,
            "usdc_e_address": GNOSIS_USDC_E_ADDRESS,
        }

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

        agent_details_url_regex = rf"{hostname_regex}\/api\/v1\/agent\/details"
        agent_performance_url_regex = rf"{hostname_regex}\/api\/v1\/agent\/performance"
        agent_predictions_url_regex = (
            rf"{hostname_regex}\/api\/v1\/agent\/prediction-history"
        )
        agent_profit_over_time_url_regex = (
            rf"{self.hostname_regex}\/api\/v1\/agent\/profit-over-time"
        )
        trading_details_url_regex = (
            rf"{hostname_regex}\/api\/v1\/agent\/trading-details"
        )
        is_enabled_url = rf"{hostname_regex}\/features"
        position_details_url_regex = (
            rf"{hostname_regex}\/api\/v1\/agent\/position-details\/([^\/]+)"
        )

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
                (agent_details_url_regex, self._handle_get_agent_details),
                (agent_performance_url_regex, self._handle_get_agent_performance),
                (agent_predictions_url_regex, self._handle_get_predictions),
                (trading_details_url_regex, self._handle_get_trading_details),
                (is_enabled_url, self._handle_get_features),
                (agent_profit_over_time_url_regex, self._handle_get_profit_over_time),
                (
                    position_details_url_regex,
                    self._handle_get_position_details,
                ),
                (
                    static_files_regex,  # Always keep this route last as it is a catch-all for static files
                    self._handle_get_static_file,
                ),
            ],
        }

        # Determine UI build path based on trading platform
        ui_build_subdir = (
            POLYSTRAT_UI_SUBDIR
            if self.params.is_running_on_polymarket
            else OMENSTRAT_UI_SUBDIR
        )
        self.agent_profile_path = f"{UI_BUILD_BASE_DIR}/{ui_build_subdir}"

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

    def _handle_get_trading_details(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Handle GET /api/v1/agent/trading_details request."""
        try:
            # Get safe address
            safe_address = self.synchronized_data.safe_contract_address

            # Get current trading strategy
            trading_strategy = self.shared_state.chatui_config.trading_strategy
            trading_type = self._get_ui_trading_strategy(trading_strategy).value
            trading_strategy_explanation = TRADING_STRATEGY_EXPLANATION.get(
                trading_type, ""
            )

            # Format response
            formatted_response = {
                "agent_id": safe_address,
                "trading_type": trading_type,
                "trading_type_description": trading_strategy_explanation,
            }

            self.context.logger.info(f"Sending trading details: {formatted_response}")
            self._send_ok_response(http_msg, http_dialogue, formatted_response)

        except Exception as e:
            self.context.logger.error(f"Error fetching trading details: {str(e)}")
            self._send_internal_server_error_response(
                http_msg, http_dialogue, {"error": "Failed to fetch trading details"}
            )

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
        """
        Adjust fund status based on chain-specific token equivalence:

        - Gnosis (Omen): treat wxDAI as xDAI (1:1, same decimals)
        - Polygon (Polymarket): treat USDC as POL by converting via exchange rate

        :return: The adjusted fund requirements.
        """
        funds_status = copy.deepcopy(self.funds_status)

        try:
            chain_config = self._get_chain_config()
            safe_balances = funds_status[chain_config["chain_name"]].accounts[
                self.synchronized_data.safe_contract_address
            ]

            native_status = safe_balances.tokens[chain_config["native_token_address"]]

            if self.params.is_running_on_polymarket:
                # On Polygon: USDC balance needs to be converted to POL equivalent
                # Using CoinGecko to get real-time exchange rate since USDC and POL have different prices
                usdc_status = safe_balances.tokens[chain_config["usdc_address"]]
                usdc_balance = int(usdc_status.balance or 0)
                usdc_decimals = usdc_status.decimals
                pol_decimals = native_status.decimals

                if usdc_decimals is None or pol_decimals is None:
                    self.context.logger.error(
                        "Missing decimal information for USDC or native token. Can't apply adjustment."
                    )
                    return funds_status

                # If USDC balance is zero, no adjustment needed
                if usdc_balance == 0:
                    self.context.logger.info(
                        "USDC balance is zero. Skipping adjustment."
                    )
                    return funds_status

                # Get POL equivalent for USDC balance using CoinGecko
                pol_equivalent = self._get_pol_equivalent_for_usdc(
                    usdc_balance, chain_config
                )
                self.context.logger.info(
                    "USDC balance: raw=%s, decimals=%s",
                    usdc_balance,
                    usdc_decimals,
                )
                self.context.logger.info(
                    "Native token decimals: %s",
                    pol_decimals,
                )
                self.context.logger.info(
                    "CoinGecko POL equivalent (raw): %s",
                    pol_equivalent,
                )

                if pol_equivalent is None:
                    self.context.logger.warning(
                        "Failed to get POL/USDC exchange rate from CoinGecko. Skipping adjustment."
                    )
                    return funds_status

                adjustment_balance = pol_equivalent
            else:
                # On Gnosis: wxDAI balance considered as xDAI (both same decimals, 1:1 rate)
                wrapped_native_status = safe_balances.tokens[
                    chain_config["wrapped_native_address"]
                ]
                adjustment_balance = int(wrapped_native_status.balance or 0)

        except KeyError:
            self.context.logger.error(
                "Misconfigured fund requirements data. Can't apply adjustment."
            )
            return funds_status

        actual_considered_balance = int(native_status.balance or 0) + adjustment_balance

        actual_deficit = 0
        if native_status.threshold > actual_considered_balance:
            actual_deficit = max(0, native_status.topup - actual_considered_balance)
        native_status.deficit = actual_deficit

        return funds_status

    def _get_pol_to_usdc_rate(self, chain_config: Dict[str, Any]) -> Optional[float]:
        """
        Get the POL to USDC conversion rate (1 POL = X USDC), with caching.

        Fetches from CoinGecko API if cache is stale (older than 5 minutes).
        Only used for Polygon chain; Gnosis doesn't need this as wxDAI = xDAI (1:1).

        :param chain_config: Chain configuration dictionary
        :return: Conversion rate (1 POL = X USDC), or None if failed
        """

        try:
            current_time = self.shared_state.synced_timestamp
        except Exception as e:
            self.context.logger.warning(
                f"Cannot access synced_timestamp because agent hasn't made any transitions yet: {str(e)}."
            )
            current_time = None

        # Check if cached rate is still valid
        if (
            current_time is not None
            and self._pol_usdc_rate is not None
            and (current_time - self._pol_usdc_rate_timestamp)
            < COINGECKO_RATE_CACHE_SECONDS
        ):
            self.context.logger.info(
                f"Using cached POL→USDC rate: 1 POL = {self._pol_usdc_rate} USDC "
                f"(cached {int(current_time - self._pol_usdc_rate_timestamp)}s ago)"
            )
            return self._pol_usdc_rate

        # Cache is stale or doesn't exist, fetch new rate from CoinGecko
        try:
            self.context.logger.info(
                "Fetching fresh POL→USDC rate from CoinGecko API (cache expired or missing)"
            )

            # Fetch POL price from CoinGecko
            url = self.params.coingecko_pol_in_usd_price_url

            response = requests.get(url, timeout=10)

            if response.status_code != 200:
                self.context.logger.warning(
                    f"CoinGecko API returned status {response.status_code}: {response.text}"
                )
                return self._pol_usdc_rate  # Return stale cache if available

            data: Dict = response.json()

            price_usd = data.get(POLYGON_POL_ADDRESS, {}).get("usd", None)

            if not price_usd:
                self.context.logger.error(f"No USD price in CoinGecko response: {data}")
                return self._pol_usdc_rate  # Return stale cache if available

            # CoinGecko returns price in USD, which we treat as USDC (1 USD ≈ 1 USDC)
            rate = float(price_usd)

            # Update cache only if we have a valid timestamp
            if current_time is not None:
                self._pol_usdc_rate = rate
                self._pol_usdc_rate_timestamp = current_time
                self.context.logger.info(
                    f"Updated POL→USDC rate cache: 1 POL = {rate} USDC"
                )
            else:
                self.context.logger.info(
                    f"Fetched POL→USDC rate: 1 POL = {rate} USDC (not cached due to missing timestamp)"
                )

            return rate

        except Exception as e:
            self.context.logger.error(
                f"Error fetching POL→USDC rate from CoinGecko: {str(e)}"
            )
            return self._pol_usdc_rate  # Return stale cache if available

    def _get_pol_equivalent_for_usdc(
        self,
        usdc_balance: int,
        chain_config: Dict[str, Any],
    ) -> Optional[int]:
        """
        Get the POL equivalent for a given USDC balance using cached rate.

        Only used for Polygon; on Gnosis, wxDAI = xDAI (1:1) so no conversion needed.

        :param usdc_balance: USDC balance in wei (6 decimals for USDC)
        :param chain_config: Chain configuration dictionary
        :return: POL equivalent amount in wei (18 decimals), or None if failed
        """
        try:
            # Get the conversion rate (1 POL = X USDC)
            rate = self._get_pol_to_usdc_rate(chain_config)

            if rate is None or rate == 0:
                self.context.logger.error(
                    "No valid POL→USDC rate available, cannot calculate equivalent"
                )
                return None

            # Convert USDC balance (6 decimals) to standard units
            usdc_amount = usdc_balance / (10**6)

            # Calculate POL equivalent: POL = USDC / rate
            pol_amount = usdc_amount / rate

            # Convert back to wei (18 decimals)
            pol_wei = int(pol_amount * (10**18))

            self.context.logger.info(
                f"Calculated POL equivalent: {usdc_amount:.2f} USDC ≈ {pol_amount:.4f} POL "
                f"(rate: 1 POL = {rate} USDC)"
            )

            return pol_wei

        except Exception as e:
            self.context.logger.error(
                f"Error calculating POL equivalent for USDC: {str(e)}"
            )
            return None

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

    def _get_eoa_account(self) -> Optional[Account]:
        """Get the EOA account, handling both plaintext and encrypted private keys."""
        default_ledger = self.context.default_ledger_id
        eoa_file_path = (
            Path(self.context.data_dir) / f"{default_ledger}_private_key.txt"
        )

        password = self._get_password_from_args()
        if password is None:
            self.context.logger.error("No password provided for encrypted private key.")

            # Fallback to plaintext private key
            with eoa_file_path.open("r") as f:
                private_key = f.read().strip()
        else:
            crypto = EthereumCrypto(
                private_key_path=str(eoa_file_path), password=password
            )
            private_key = crypto.private_key

        try:
            return Account.from_key(private_key)
        except Exception as e:
            self.context.logger.error(f"Failed to decrypt private key: {e}")
            return None

    def _get_password_from_args(self) -> Optional[str]:
        """Extract password from command line arguments."""
        args = sys.argv
        try:
            password_index = args.index("--password")
            if password_index + 1 < len(args):
                return args[password_index + 1]
        except ValueError:
            pass

        for arg in args:
            if arg.startswith("--password="):
                return arg.split("=", 1)[1]

        return None

    def _get_web3_instance(self, chain: str) -> Optional[Web3]:
        """Get Web3 instance for the specified chain."""
        try:
            # Select RPC URL based on chain
            if chain == POLYGON_CHAIN_NAME:
                rpc_url = self.params.polygon_ledger_rpc
            elif chain == GNOSIS_CHAIN_NAME:
                rpc_url = self.params.gnosis_ledger_rpc
            else:
                self.context.logger.error(f"Unknown chain: {chain}")
                return None

            if not rpc_url:
                self.context.logger.warning(f"No RPC URL for {chain}")
                return None

            # Commented for future debugging purposes:
            # Note that you should create only one HTTPProvider with the same provider URL per python process,
            # as the HTTPProvider recycles underlying TCP/IP network connections, for better performance.
            # Multiple HTTPProviders with different URLs will work as expected.
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

    def _get_lifi_quote(
        self,
        from_token: str,
        to_token: str,
        from_address: str,
        to_address: str,
        chain_config: Dict[str, Any],
        from_amount: Optional[str] = None,
        to_amount: Optional[str] = None,
        timeout: int = 30,
    ) -> Optional[Dict]:
        """
        Get LiFi quote for token swap.

        :param from_token: Source token address
        :param to_token: Destination token address
        :param from_address: Address sending the tokens
        :param to_address: Address receiving the tokens
        :param chain_config: Chain configuration dictionary
        :param from_amount: Amount to swap from (for standard quote)
        :param to_amount: Desired amount to receive (for toAmount quote)
        :param timeout: Request timeout in seconds
        :return: LiFi quote response or None if failed
        """
        try:
            # Use different slippage values based on chain
            slippage = str(
                self.params.slippages_for_swap["POL-USDC"]
                if chain_config["chain_name"] == POLYGON_CHAIN_NAME
                else self.params.slippages_for_swap["xDAI-USDC"]
            )

            params = {
                "fromChain": chain_config["chain_id"],
                "toChain": chain_config["chain_id"],
                "fromToken": from_token,
                "toToken": to_token,
                "fromAddress": from_address,
                "toAddress": to_address,
                "slippage": slippage,
                "integrator": "valory",
            }

            # Add amount parameter based on what's provided
            if to_amount is not None:
                params["toAmount"] = to_amount
                url = self.params.lifi_quote_to_amount_url
            elif from_amount is not None:
                params["fromAmount"] = from_amount
                url = self.params.lifi_quote_to_amount_url.replace(
                    "/quote/toAmount", "/quote"
                )
            else:
                self.context.logger.error(
                    "Either from_amount or to_amount must be provided"
                )
                return None

            response = requests.get(url, params=params, timeout=timeout)

            if response.status_code == 200:
                return response.json()

            self.context.logger.warning(
                f"LiFi API failed with status {response.status_code} {response.text}"
            )
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

            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            return tx_hash.hex()

        except Exception as e:
            self.context.logger.error(f"Error submitting transaction: {str(e)}")
            return None

    def _check_transaction_status(
        self, tx_hash: str, chain: str, timeout: int = 60
    ) -> bool:
        """Check if transaction was successful by waiting for receipt."""
        try:
            w3 = self._get_web3_instance(chain)
            if not w3:
                return False

            self.context.logger.info(
                f"Waiting for transaction {tx_hash} to be mined..."
            )

            # Wait for transaction receipt with timeout
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)

            if receipt.status == 1:
                self.context.logger.info(f"Transaction {tx_hash} successful")
                return True
            else:
                self.context.logger.error(
                    f"Transaction {tx_hash} failed (status: {receipt.status})"
                )
                return False

        except Exception as e:
            self.context.logger.error(f"Error checking transaction status: {str(e)}")
            return False

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

    def _estimate_gas(
        self,
        tx_request: Dict,
        eoa_address: str,
        chain: str,
    ) -> Optional[int]:
        """Estimate gas for a transaction"""
        try:
            w3 = self._get_web3_instance(chain)
            if not w3:
                self.context.logger.error(
                    "Failed to get Web3 instance for gas estimation"
                )
                return False

            tx_value = (
                int(tx_request["value"], 16)
                if isinstance(tx_request["value"], str)
                else tx_request["value"]
            )

            # Prepare transaction data for gas estimation
            tx_data_for_estimation = {
                "to": Web3.to_checksum_address(tx_request["to"]),
                "data": tx_request["data"],
                "value": tx_value,
                "from": Web3.to_checksum_address(eoa_address),
            }
            # Try to estimate gas using Web3
            estimated_gas = w3.eth.estimate_gas(tx_data_for_estimation)
            # Add 20% buffer to estimated gas
            tx_gas = int(estimated_gas * 1.2)
            self.context.logger.info(
                f"Estimated gas: {estimated_gas}, with 20% buffer: {tx_gas}"
            )
            return tx_gas

        except Exception as e:
            self.context.logger.error(f"Error in gas estimation: {str(e)}")
            return None

    def _ensure_sufficient_funds_for_x402_payments(self) -> bool:
        """Ensure agent EOA has at sufficient funds for x402 requests payments"""
        self.context.logger.info("Checking USDC balance for x402 payments...")
        try:
            chain_config = self._get_chain_config()
            chain = chain_config["chain_name"]
            eoa_account = self._get_eoa_account()
            if not eoa_account:
                self.context.logger.error("Failed to get EOA account")
                return False
            eoa_address = eoa_account.address

            # For Polygon use USDC (native), for Gnosis use USDC.e (bridged)
            usdc_address = (
                chain_config["usdc_address"]
                if self.params.is_running_on_polymarket
                else chain_config["usdc_e_address"]
            )
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

            native_token_name = (
                "POL" if self.params.is_running_on_polymarket else "xDAI"
            )
            self.context.logger.info(
                f"USDC balance ({usdc_balance}) < {threshold}, swapping {native_token_name} to {top_up} USDC..."
            )

            top_up_usdc_amount = str(top_up)
            quote = self._get_lifi_quote(
                from_token=chain_config["native_token_address"],
                to_token=usdc_address,
                from_address=eoa_address,
                to_address=eoa_address,
                chain_config=chain_config,
                to_amount=top_up_usdc_amount,
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
            tx_gas = self._estimate_gas(tx_request, eoa_address, chain)
            if tx_gas is None:
                self.context.logger.error("Failed to estimate gas for transaction")
                return False

            tx_data = {
                "to": Web3.to_checksum_address(tx_request["to"]),
                "data": tx_request["data"],
                "value": tx_value,
                "gas": tx_gas,
                "gasPrice": gas_price,
                "nonce": nonce,
                "chainId": chain_config["chain_id"],
            }

            self.context.logger.info(
                f"Signing and submitting tx: value={tx_data['value']}, gas={tx_data['gas']}, to={tx_data['to']}, data={tx_data['data']}..."
            )

            tx_hash = self._sign_and_submit_tx_web3(tx_data, chain, eoa_account)

            if not tx_hash:
                self.context.logger.error("Failed to submit transaction")
                return False

            native_token_name = (
                "POL" if self.params.is_running_on_polymarket else "xDAI"
            )
            self.context.logger.info(
                f"{native_token_name} to USDC swap submitted: {tx_hash}"
            )

            # Check transaction status to ensure it was successful
            tx_successful = self._check_transaction_status(tx_hash, chain)

            if not tx_successful:
                self.context.logger.error(f"Transaction {tx_hash} failed or timed out")
                return False

            self.context.logger.info(
                f"{native_token_name} to USDC swap completed successfully: {tx_hash}"
            )
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
