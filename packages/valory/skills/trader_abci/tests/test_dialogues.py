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

"""Tests for the dialogues module of the trader_abci skill."""

# pylint: skip-file

from unittest.mock import MagicMock

from aea.configurations.data_types import PublicId

from packages.valory.protocols.srr.dialogues import SrrDialogue as BaseSrrDialogue
from packages.valory.protocols.srr.message import SrrMessage
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
from packages.valory.skills.mech_interact_abci.dialogues import (
    AcnDialogue as BaseAcnDialogue,
)
from packages.valory.skills.mech_interact_abci.dialogues import (
    AcnDialogues as BaseAcnDialogues,
)
from packages.valory.skills.trader_abci.dialogues import (
    AbciDialogue,
    AbciDialogues,
    AcnDialogue,
    AcnDialogues,
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
    SrrDialogue,
    SrrDialogues,
    TendermintDialogue,
    TendermintDialogues,
)


def test_import() -> None:
    """Test that the 'dialogues.py' Python module can be imported."""
    import packages.valory.skills.trader_abci.dialogues  # noqa: F401


def test_abci_dialogue_is_base() -> None:
    """Test AbciDialogue re-export matches the base class."""
    assert AbciDialogue is BaseAbciDialogue


def test_abci_dialogues_is_base() -> None:
    """Test AbciDialogues re-export matches the base class."""
    assert AbciDialogues is BaseAbciDialogues


def test_http_dialogue_is_base() -> None:
    """Test HttpDialogue re-export matches the base class."""
    assert HttpDialogue is BaseHttpDialogue


def test_http_dialogues_is_base() -> None:
    """Test HttpDialogues re-export matches the base class."""
    assert HttpDialogues is BaseHttpDialogues


def test_signing_dialogue_is_base() -> None:
    """Test SigningDialogue re-export matches the base class."""
    assert SigningDialogue is BaseSigningDialogue


def test_signing_dialogues_is_base() -> None:
    """Test SigningDialogues re-export matches the base class."""
    assert SigningDialogues is BaseSigningDialogues


def test_ledger_api_dialogue_is_base() -> None:
    """Test LedgerApiDialogue re-export matches the base class."""
    assert LedgerApiDialogue is BaseLedgerApiDialogue


def test_ledger_api_dialogues_is_base() -> None:
    """Test LedgerApiDialogues re-export matches the base class."""
    assert LedgerApiDialogues is BaseLedgerApiDialogues


def test_contract_api_dialogue_is_base() -> None:
    """Test ContractApiDialogue re-export matches the base class."""
    assert ContractApiDialogue is BaseContractApiDialogue


def test_contract_api_dialogues_is_base() -> None:
    """Test ContractApiDialogues re-export matches the base class."""
    assert ContractApiDialogues is BaseContractApiDialogues


def test_tendermint_dialogue_is_base() -> None:
    """Test TendermintDialogue re-export matches the base class."""
    assert TendermintDialogue is BaseTendermintDialogue


def test_tendermint_dialogues_is_base() -> None:
    """Test TendermintDialogues re-export matches the base class."""
    assert TendermintDialogues is BaseTendermintDialogues


def test_ipfs_dialogue_is_base() -> None:
    """Test IpfsDialogue re-export matches the base class."""
    assert IpfsDialogue is BaseIpfsDialogue


def test_ipfs_dialogues_is_base() -> None:
    """Test IpfsDialogues re-export matches the base class."""
    assert IpfsDialogues is BaseIpfsDialogues


def test_acn_dialogue_is_base() -> None:
    """Test AcnDialogue re-export matches the base class."""
    assert AcnDialogue is BaseAcnDialogue


def test_acn_dialogues_is_base() -> None:
    """Test AcnDialogues re-export matches the base class."""
    assert AcnDialogues is BaseAcnDialogues


def test_srr_dialogue_is_base() -> None:
    """Test SrrDialogue re-export matches the base class."""
    assert SrrDialogue is BaseSrrDialogue


class TestSrrDialogues:
    """Tests for the SrrDialogues class."""

    def test_init(self) -> None:
        """Test SrrDialogues can be instantiated with a skill_context."""
        skill_context = MagicMock()
        skill_context.skill_id = PublicId.from_str("dummy/skill:0.1.0")
        dialogues = SrrDialogues(name="srr_dialogues", skill_context=skill_context)
        assert dialogues is not None

    def test_role_from_first_message(self) -> None:
        """Test the inner role_from_first_message returns SKILL role."""
        skill_context = MagicMock()
        skill_context.skill_id = PublicId.from_str("dummy/skill:0.1.0")
        dialogues = SrrDialogues(name="srr_dialogues", skill_context=skill_context)

        msg, dialogue = dialogues.create(
            counterparty="some_connection",
            performative=SrrMessage.Performative.REQUEST,
            payload="{}",
        )
        assert dialogue is not None
        assert dialogue.role == BaseSrrDialogue.Role.SKILL
