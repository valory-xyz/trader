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

"""This module contains the PolymarketWrapCollateralBehaviour.

The behaviour sits between DecisionReceive and PolymarketBetPlacement: if the
Safe holds USDC.e above a dust threshold, it prepares a Safe multisend that
wraps it to pUSD via the Polymarket Collateral Onramp so the subsequent bet
has the v2 collateral token to spend.
"""

from typing import Any, Generator, Optional

from eth_abi import encode
from eth_utils import keccak
from hexbytes import HexBytes

from packages.valory.contracts.erc20.contract import ERC20TokenContract as ERC20
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
    MultisendBatch,
)
from packages.valory.skills.decision_maker_abci.payloads import (
    PolymarketWrapCollateralPayload,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_wrap_collateral import (
    PolymarketWrapCollateralRound,
)

POLYGON_CHAIN_ID = "polygon"
ERC20_APPROVE_SELECTOR = "0x095ea7b3"  # keccak256("approve(address,uint256)")[:4]


class PolymarketWrapCollateralBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour that wraps any USDC.e held by the Safe into pUSD."""

    matching_round = PolymarketWrapCollateralRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the wrap behaviour."""
        super().__init__(**kwargs)

    def async_act(self) -> Generator:
        """Check USDC.e balance, build wrap multisend if above dust."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            agent = self.context.agent_address

            if not self.params.is_running_on_polymarket:
                self.context.logger.info(
                    "[WrapCollateral] Not on Polymarket network; skipping."
                )
                payload = PolymarketWrapCollateralPayload(
                    sender=agent,
                    tx_submitter=None,
                    tx_hash=None,
                    should_wrap=False,
                )
                yield from self.send_a2a_transaction(payload)
                self.set_done()
                return

            tx_hash = yield from self._get_tx_hash()
            if tx_hash is None:
                tx_submitter = None
                should_wrap = False
            else:
                tx_submitter = self.matching_round.auto_round_id()
                should_wrap = True

            payload = PolymarketWrapCollateralPayload(
                sender=agent,
                tx_submitter=tx_submitter,
                tx_hash=tx_hash,
                should_wrap=should_wrap,
            )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()
        self.set_done()

    def _get_usdc_e_balance(
        self, safe_address: str
    ) -> Generator[None, None, Optional[int]]:
        """Read the Safe's USDC.e balance via ERC20.check_balance."""
        response = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.params.polymarket_usdc_e_address,
            contract_id=str(ERC20.contract_id),
            contract_callable="check_balance",
            account=safe_address,
            chain_id=POLYGON_CHAIN_ID,
        )
        if response.performative != ContractApiMessage.Performative.RAW_TRANSACTION:
            self.context.logger.error(
                f"[WrapCollateral] Could not read USDC.e balance: {response}"
            )
            return None
        token_balance = response.raw_transaction.body.get("token")
        if token_balance is None:
            self.context.logger.error(
                f"[WrapCollateral] Missing 'token' field in ERC20 response: {response}"
            )
            return None
        return int(token_balance)

    def _get_tx_hash(self) -> Generator[None, None, Optional[str]]:
        """Build the wrap multisend and return the hashed Safe payload, or None."""
        safe_address = self.synchronized_data.safe_contract_address
        balance = yield from self._get_usdc_e_balance(safe_address)
        if balance is None:
            return None

        dust = self.params.polymarket_usdc_e_wrap_dust_threshold
        self.context.logger.info(
            f"[WrapCollateral] Safe USDC.e balance: {balance} (dust threshold: {dust})"
        )
        if balance <= dust:
            self.context.logger.info(
                "[WrapCollateral] Balance at/below dust; skipping wrap."
            )
            return None

        # Reset so the base's multisend helpers start from a clean slate.
        self.multisend_batches = []

        onramp = self.params.polymarket_collateral_onramp_address
        usdc_e = self.params.polymarket_usdc_e_address

        # 1. USDC.e.approve(onramp, balance) — onramp pulls via transferFrom
        self.multisend_batches.append(
            MultisendBatch(
                to=usdc_e,
                data=HexBytes(self._encode_erc20_approve(onramp, balance)),
                value=0,
            )
        )

        # 2. onramp.wrap(USDC.e, safe, balance) — mints pUSD to the Safe
        self.multisend_batches.append(
            MultisendBatch(
                to=onramp,
                data=HexBytes(self._encode_onramp_wrap(usdc_e, safe_address, balance)),
                value=0,
            )
        )

        built = yield from self._build_multisend_data()
        if not built:
            self.context.logger.error(
                "[WrapCollateral] Failed to build multisend data."
            )
            return None

        built = yield from self._build_multisend_safe_tx_hash()
        if not built:
            self.context.logger.error("[WrapCollateral] Failed to build Safe tx hash.")
            return None

        self.context.logger.info(
            f"[WrapCollateral] Prepared wrap of {balance} USDC.e via onramp {onramp}"
        )
        return self.tx_hex

    @staticmethod
    def _encode_erc20_approve(spender: str, amount: int) -> str:
        """Encode ERC-20 approve(address,uint256) calldata."""
        spender_padded = spender[2:].zfill(64).lower()
        amount_hex = hex(amount)[2:].zfill(64)
        return f"{ERC20_APPROVE_SELECTOR}{spender_padded}{amount_hex}"

    @staticmethod
    def _encode_onramp_wrap(asset: str, to: str, amount: int) -> str:
        """Encode CollateralOnramp.wrap(address,address,uint256) calldata.

        The onramp enforces ``asset == USDC.e``; native USDC is rejected.
        """
        selector = keccak(text="wrap(address,address,uint256)")[:4]
        encoded_args = encode(["address", "address", "uint256"], [asset, to, amount])
        return "0x" + (selector + encoded_args).hex()
