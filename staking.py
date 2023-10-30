#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2022-2023 Valory AG
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

"""This script swaps ownership of a Safe with a single owner."""

import argparse
import sys
import traceback
import typing
from pathlib import Path

from aea.contracts.base import Contract
from aea_ledger_ethereum.ethereum import EthereumApi, EthereumCrypto
from eth_typing import HexStr

from packages.valory.contracts.erc20.contract import (
    ERC20,
)
from packages.valory.contracts.service_staking_token.contract import (
    ServiceStakingTokenContract,
)

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ZERO_ETH = 0

ContractType = typing.TypeVar("ContractType")


def load_contract(ctype: ContractType) -> ContractType:
    """Load contract."""
    *parts, _ = ctype.__module__.split(".")
    path = "/".join(parts)
    return Contract.from_dir(directory=path)


def get_stake_txs(service_id: int, service_registry_address: str, staking_contract_address: str) -> typing.List:
    """Stake the service"""
    # 1. approve the service to make use of the

    # we make use of the ERC20 contract to build the approval transaction
    # since it has the same interface as ERC721
    # we use the ZERO_ADDRESS as the contract address since we don't do any contract interaction here,
    # we are simply encoding
    approval_tx = get_approval_tx(service_id, service_registry_address, staking_contract_address)

    # 2. stake the service
    staking_contract = typing.cast(typing.Type[ServiceStakingTokenContract], load_contract(ServiceStakingTokenContract))
    stake_tx_data = staking_contract.build_stake_tx(ledger_api, staking_contract_address, service_id).pop('data')
    stake_tx = {
        "data": stake_tx_data,
        "to": staking_contract_address,
        "value": ZERO_ETH,
    }
    return [approval_tx, stake_tx]


def get_approval_tx(service_id, service_registry_address, staking_contract_address):
    """Get approval tx"""
    approval_tx_data = erc20.build_approval_tx(ledger_api, service_registry_address, staking_contract_address,
                                               service_id).pop('data')
    approval_tx = {
        "data": approval_tx_data,
        "to": service_registry_address,
        "value": ZERO_ETH,
    }
    return approval_tx


def get_unstake_txs(service_id: int, staking_contract_address: str) -> typing.List:
    """Get unstake txs"""

    unstake_tx_data = staking_contract.build_unstake_tx(ledger_api, staking_contract_address, service_id).pop('data')
    unstake_tx = {
        "data": unstake_tx_data,
        "to": staking_contract_address,
        "value": ZERO_ETH,
    }
    return [unstake_tx]


def get_available_rewards(staking_contract_address: str) -> int:
    """Get available rewards."""
    rewards = staking_contract.available_rewards(ledger_api, staking_contract_address).pop('data')
    return rewards


def is_service_staked(service_id: int, staking_contract_address: str) -> bool:
    """Check if service is staked."""
    is_staked = staking_contract.is_service_staked(ledger_api, staking_contract_address, service_id).pop('data')
    return is_staked


def send_tx(crypto: EthereumCrypto, raw_tx: typing.Dict[str, typing.Any]) -> str:
    """Send transaction."""
    signed_tx = crypto.sign_transaction(raw_tx)
    tx_digest = typing.cast(
        str, ledger_api.send_signed_transaction(signed_tx, raise_on_try=True)
    )
    return tx_digest


def send_tx_and_wait_for_receipt(crypto: EthereumCrypto, raw_tx: typing.Dict[str, typing.Any]) -> typing.Dict[str, typing.Any]:
    """Send transaction and wait for receipt."""
    tx_digest = HexStr(send_tx(crypto, raw_tx))
    receipt = ledger_api.api.eth.wait_for_transaction_receipt(tx_digest)
    if receipt["status"] == 1:
        print("Transaction failed. Receipt:", receipt)
        sys.exit(1)
    return receipt


if __name__ == "__main__":
    try:
        print(f"  - Starting {Path(__file__).name} script...")

        parser = argparse.ArgumentParser(
            description="Stake or unstake the service based on the state."
        )
        parser.add_argument(
            "service_id",
            type=int,
            help="The on-chain service id.",
        )
        parser.add_argument(
            "service_registry_address",
            type=str,
            help="The service registry contract address.",
        )
        parser.add_argument(
            "staking_contract_address",
            type=str,
            help="The staking contract address.",
        )
        parser.add_argument(
            "owner_private_key_path",
            type=str,
            help="Path to the file containing the service owner's Ethereum private key",
        )
        parser.add_argument("rpc", type=str, help="RPC for the Gnosis chain")
        args = parser.parse_args()

        ledger_api = EthereumApi(address=args.rpc)
        owner_crypto = EthereumCrypto(
            private_key_path=args.owner_private_key_path
        )
        staking_contract = typing.cast(
            typing.Type[ServiceStakingTokenContract],
            load_contract(ServiceStakingTokenContract)
        )
        erc20 = typing.cast(typing.Type[ERC20], load_contract(ERC20))

        if is_service_staked(args.service_id, args.staking_contract_address):
            print(
                f"Service {args.service_id} is already staked. "
                f"Checking if the staking contract has any rewards..."
            )
            available_rewards = get_available_rewards(args.staking_contract_address)
            if available_rewards == 0:
                print("No rewards available. Unstaking...")
                unstake_txs = get_unstake_txs(args.service_id, args.staking_contract_address)
                for tx in unstake_txs:
                    send_tx_and_wait_for_receipt(owner_crypto, tx)

                print("Unstaked successfully.")
                sys.exit(0)

            print("There are rewards available. The service should remain staked.")
            sys.exit(0)

        print(f"Service {args.service_id} is not staked. Checking for available rewards...")
        available_rewards = get_available_rewards(args.staking_contract_address)
        if available_rewards == 0:
            # no rewards available, do nothing
            print("No rewards available. The service cannot be staked.")
            sys.exit(0)

        print(f"Rewards available: {available_rewards}. Staking the service...")
        stake_txs = get_stake_txs(args.service_id, args.service_registry_address, args.staking_contract_address)
        for tx in stake_txs:
            send_tx_and_wait_for_receipt(owner_crypto, tx)

        print(f"Service {args.service_id} staked successfully.")
        sys.exit(0)
    except Exception as e:  # pylint: disable=broad-except
        print(f"An error occurred while executing {Path(__file__).name}: {str(e)}")
        traceback.print_exc()
        sys.exit(1)
