# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2026 Valory AG
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

"""This module contains the class to connect to the `MechActivityContract` contract."""

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from web3.exceptions import BadFunctionCallOutput, ContractLogicError

# "No such function" surfaces as one of these: an absent ``VERSION`` /
# ``activityChecker`` getter either reverts (``ContractLogicError``) or returns
# empty data that fails ABI decoding (``BadFunctionCallOutput``). We deliberately
# do NOT catch ``ValueError``: web3 raises a ``ValueError`` subclass for
# transient RPC blips (e.g. "Skipping the filtering operation as the RPC is
# misbehaving"), so swallowing it would mis-classify a passing failure as "old
# checker" and cache that for the whole process lifetime. Connection / RPC /
# timeout errors (including ``ValueError``) must propagate so the caller retries.
_NO_SUCH_FUNCTION = (BadFunctionCallOutput, ContractLogicError)


class MechActivityContract(Contract):
    """The Service Staking contract."""

    contract_id = PublicId.from_str("valory/mech_activity:0.1.0")

    @classmethod
    def liveness_ratio(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
    ) -> JSONLike:
        """Retrieve the liveness ratio."""
        contract = cls.get_instance(ledger_api, contract_address)
        liveness_ratio = contract.functions.livenessRatio().call()
        return dict(data=liveness_ratio)

    @classmethod
    def get_activity_checker(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
    ) -> JSONLike:
        """Retrieve the activity checker address from a staking contract.

        Called against a *staking* contract address (the ABI only supplies the
        ``activityChecker()`` selector). ``data=None`` means the getter is
        genuinely absent (e.g. an old ``ServiceStakingToken``). Only
        ``_NO_SUCH_FUNCTION`` is swallowed; transient RPC/connection failures
        are re-raised so the caller can retry rather than silently treating the
        contract as checker-less.

        :param ledger_api: the ledger API object.
        :param contract_address: the staking contract address.
        :return: a ``{"data": <checker address or None>}`` mapping.
        """
        contract = cls.get_instance(ledger_api, contract_address)
        try:
            return dict(data=contract.functions.activityChecker().call())
        except _NO_SUCH_FUNCTION:
            return dict(data=None)

    @classmethod
    def version(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
    ) -> JSONLike:
        """Retrieve the activity checker ``VERSION``.

        ``data=None`` means the ``VERSION`` getter is genuinely absent (an old
        activity checker). Only ``_NO_SUCH_FUNCTION`` is swallowed; transient
        RPC/connection failures are re-raised so the caller can retry rather
        than silently treating the checker as "old".

        :param ledger_api: the ledger API object.
        :param contract_address: the activity checker contract address.
        :return: a ``{"data": <version str or None>}`` mapping.
        """
        contract = cls.get_instance(ledger_api, contract_address)
        try:
            return dict(data=contract.functions.VERSION().call())
        except _NO_SUCH_FUNCTION:
            return dict(data=None)
