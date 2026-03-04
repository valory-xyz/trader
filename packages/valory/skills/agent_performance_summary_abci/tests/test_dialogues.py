# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

"""Test the dialogues.py module of the skill."""

# pylint: skip-file

import packages.valory.skills.agent_performance_summary_abci.dialogues as dialogues_module  # noqa
from packages.valory.skills.abstract_round_abci.dialogues import (
    AbciDialogue as BaseAbciDialogue,
)
from packages.valory.skills.abstract_round_abci.dialogues import (
    AbciDialogues as BaseAbciDialogues,
)
from packages.valory.skills.abstract_round_abci.dialogues import (
    ContractApiDialogue as BaseContractApiDialogue,
)
from packages.valory.skills.abstract_round_abci.dialogues import (
    ContractApiDialogues as BaseContractApiDialogues,
)
from packages.valory.skills.abstract_round_abci.dialogues import (
    HttpDialogue as BaseHttpDialogue,
)
from packages.valory.skills.abstract_round_abci.dialogues import (
    HttpDialogues as BaseHttpDialogues,
)
from packages.valory.skills.abstract_round_abci.dialogues import (
    IpfsDialogue as BaseIpfsDialogue,
)
from packages.valory.skills.abstract_round_abci.dialogues import (
    IpfsDialogues as BaseIpfsDialogues,
)
from packages.valory.skills.abstract_round_abci.dialogues import (
    LedgerApiDialogue as BaseLedgerApiDialogue,
)
from packages.valory.skills.abstract_round_abci.dialogues import (
    LedgerApiDialogues as BaseLedgerApiDialogues,
)
from packages.valory.skills.abstract_round_abci.dialogues import (
    SigningDialogue as BaseSigningDialogue,
)
from packages.valory.skills.abstract_round_abci.dialogues import (
    SigningDialogues as BaseSigningDialogues,
)
from packages.valory.skills.abstract_round_abci.dialogues import (
    TendermintDialogue as BaseTendermintDialogue,
)
from packages.valory.skills.abstract_round_abci.dialogues import (
    TendermintDialogues as BaseTendermintDialogues,
)
from packages.valory.skills.agent_performance_summary_abci.dialogues import (
    AbciDialogue,
    AbciDialogues,
    ContractApiDialogue,
    ContractApiDialogues,
    HttpDialogue,
    HttpDialogues,
    IpfsDialogue,
    IpfsDialogues,
    LedgerApiDialogue,
    LedgerApiDialogues,
    SigningDialogue,
    SigningDialogues,
    TendermintDialogue,
    TendermintDialogues,
)


def test_import() -> None:
    """Test that the 'dialogues.py' Python module can be imported."""


def test_abci_dialogue_is_base() -> None:
    """Test AbciDialogue matches base class."""
    assert AbciDialogue is BaseAbciDialogue


def test_abci_dialogues_is_base() -> None:
    """Test AbciDialogues matches base class."""
    assert AbciDialogues is BaseAbciDialogues


def test_http_dialogue_is_base() -> None:
    """Test HttpDialogue matches base class."""
    assert HttpDialogue is BaseHttpDialogue


def test_http_dialogues_is_base() -> None:
    """Test HttpDialogues matches base class."""
    assert HttpDialogues is BaseHttpDialogues


def test_signing_dialogue_is_base() -> None:
    """Test SigningDialogue matches base class."""
    assert SigningDialogue is BaseSigningDialogue


def test_signing_dialogues_is_base() -> None:
    """Test SigningDialogues matches base class."""
    assert SigningDialogues is BaseSigningDialogues


def test_ledger_api_dialogue_is_base() -> None:
    """Test LedgerApiDialogue matches base class."""
    assert LedgerApiDialogue is BaseLedgerApiDialogue


def test_ledger_api_dialogues_is_base() -> None:
    """Test LedgerApiDialogues matches base class."""
    assert LedgerApiDialogues is BaseLedgerApiDialogues


def test_contract_api_dialogue_is_base() -> None:
    """Test ContractApiDialogue matches base class."""
    assert ContractApiDialogue is BaseContractApiDialogue


def test_contract_api_dialogues_is_base() -> None:
    """Test ContractApiDialogues matches base class."""
    assert ContractApiDialogues is BaseContractApiDialogues


def test_tendermint_dialogue_is_base() -> None:
    """Test TendermintDialogue matches base class."""
    assert TendermintDialogue is BaseTendermintDialogue


def test_tendermint_dialogues_is_base() -> None:
    """Test TendermintDialogues matches base class."""
    assert TendermintDialogues is BaseTendermintDialogues


def test_ipfs_dialogue_is_base() -> None:
    """Test IpfsDialogue matches base class."""
    assert IpfsDialogue is BaseIpfsDialogue


def test_ipfs_dialogues_is_base() -> None:
    """Test IpfsDialogues matches base class."""
    assert IpfsDialogues is BaseIpfsDialogues
