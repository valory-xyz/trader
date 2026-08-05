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

"""Tests for the CLOB v2 DepositWallet handlers on the Polymarket connection."""

from unittest.mock import MagicMock, patch

from eth_utils import to_checksum_address

from packages.valory.connections.polymarket_client.connection import (
    PolymarketClientConnection,
    SIGNATURE_TYPE_POLY_1271,
)
from packages.valory.connections.polymarket_client.relayer_proxy import (
    DW_FACTORY,
    RelayerProxyError,
)

COLLAT = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
EXCH = "0xE111180000d2663C0091e4f400237545B87B996B"
NRX = "0xe2222d279d744050d28e00520010520000310F59"
NRA = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
SAFE = "0x1111111111111111111111111111111111111111"
DW = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"


class _Conn(PolymarketClientConnection):
    """Shadow the read-only configuration property for direct assignment."""

    configuration = None  # type: ignore[assignment]


def _make_conn() -> _Conn:
    """Build a connection bypassing __init__ with DW attributes stubbed."""
    conn = object.__new__(_Conn)
    conn.logger = MagicMock()
    conn.relayer_proxy = MagicMock()
    conn.dw_address = None
    conn._client_funder = SAFE
    conn._host = "https://clob.example"
    conn._chain_id = 137
    conn.builder_config = None
    conn.connection_private_key = "0x" + "1" * 64
    conn.collateral_address = COLLAT
    conn.ctf_address = CTF
    conn.ctf_exchange = EXCH
    conn.neg_risk_ctf_exchange = NRX
    conn.neg_risk_adapter = NRA
    conn.w3 = MagicMock()
    conn.client = MagicMock()
    configuration_mock = MagicMock()
    configuration_mock.config.get.side_effect = lambda key, *a, **k: (
        {"polygon": SAFE} if key == "safe_contract_addresses" else (a[0] if a else None)
    )
    conn.configuration = configuration_mock
    return conn


class TestEncoders:
    """Encoder / read helpers."""

    def test_encode_erc20_transfer(self) -> None:
        """ERC20 transfer calldata has the transfer selector."""
        conn = _make_conn()
        data = conn._encode_erc20_transfer(DW, 1000)
        assert data.startswith("0xa9059cbb")
        assert len(data) == 2 + 8 + 64 + 64

    def test_erc20_balance_of(self) -> None:
        """_erc20_balance_of decodes the eth_call result as a big-endian int."""
        conn = _make_conn()
        conn.w3.keccak.return_value.hex.return_value = "deadbeef"
        conn.w3.to_checksum_address.side_effect = lambda a: a
        conn.w3.eth.call.return_value = (12345).to_bytes(32, "big")
        assert conn._erc20_balance_of(COLLAT, DW) == 12345

    def test_dw_collateral_balance_reads_pusd(self) -> None:
        """The DW pUSD base-unit balance is returned scaled to float USDC."""
        conn = _make_conn()
        conn.w3.keccak.return_value.hex.return_value = "deadbeef"
        conn.w3.to_checksum_address.side_effect = lambda a: a
        conn.w3.eth.call.return_value = (2_500_000).to_bytes(32, "big")
        assert conn._dw_collateral_balance(DW, fallback=9.9) == 2.5

    def test_dw_collateral_balance_no_dw_returns_fallback(self) -> None:
        """A missing DW short-circuits to the fallback (no RPC call)."""
        conn = _make_conn()
        assert conn._dw_collateral_balance(None, fallback=4.2) == 4.2
        conn.w3.eth.call.assert_not_called()

    def test_dw_collateral_balance_rpc_error_returns_fallback(self) -> None:
        """An RPC failure logs a warning and falls back to the nominal amount."""
        conn = _make_conn()
        conn.w3.keccak.return_value.hex.return_value = "deadbeef"
        conn.w3.to_checksum_address.side_effect = lambda a: a
        conn.w3.eth.call.side_effect = RuntimeError("rpc down")
        assert conn._dw_collateral_balance(DW, fallback=1.0) == 1.0
        conn.logger.warning.assert_called_once()

    def test_erc1155_balance_of(self) -> None:
        """_erc1155_balance_of decodes the eth_call result as a big-endian int."""
        conn = _make_conn()
        conn.w3.keccak.return_value.hex.return_value = "00fdd58e"
        conn.w3.to_checksum_address.side_effect = lambda a: a
        conn.w3.eth.call.return_value = (777).to_bytes(32, "big")
        assert conn._erc1155_balance_of(CTF, DW, 42) == 777

    def test_encode_erc1155_safe_transfer(self) -> None:
        """ERC1155 safeTransferFrom calldata has the safeTransferFrom selector."""
        conn = _make_conn()
        data = conn._encode_erc1155_safe_transfer(DW, SAFE, 42, 5)
        # 0xf242432a is the first 4 bytes of the safeTransferFrom selector hash.
        assert data.startswith("0xf242432a")


class TestEnsureDwFunder:
    """Funder rebinding."""

    def test_noop_when_none(self) -> None:
        """A None funder is a no-op."""
        conn = _make_conn()
        before = conn.client
        conn._ensure_dw_funder(None)
        assert conn.client is before

    def test_noop_when_same(self) -> None:
        """The same funder does not rebuild the client."""
        conn = _make_conn()
        conn._client_funder = to_checksum_address(DW)
        before = conn.client
        conn._ensure_dw_funder(DW)
        assert conn.client is before

    def test_rebuilds_on_new_funder(self) -> None:
        """A new funder rebuilds the CLOB client with POLY_1271."""
        conn = _make_conn()
        new_client = MagicMock()
        with patch.object(
            _Conn, "_build_clob_client", return_value=new_client
        ) as build:
            conn._ensure_dw_funder(DW)
        build.assert_called_once()
        assert build.call_args.kwargs["signature_type"] == SIGNATURE_TYPE_POLY_1271
        assert conn.client is new_client
        assert conn.dw_address == to_checksum_address(DW)

    def test_build_clob_client(self) -> None:
        """_build_clob_client constructs a client and sets API creds."""
        conn = _make_conn()
        with patch(
            "packages.valory.connections.polymarket_client.connection.ClobClient"
        ) as clob:
            client = conn._build_clob_client(DW, SIGNATURE_TYPE_POLY_1271)
        clob.assert_called_once()
        client.set_api_creds.assert_called_once()


class TestDwNonce:
    """The on-chain DW batch-nonce read."""

    def test_dw_nonce(self) -> None:
        """_dw_nonce decodes the eth_call result as a big-endian int."""
        conn = _make_conn()
        conn.w3.keccak.return_value.hex.return_value = "11223344"
        conn.w3.to_checksum_address.side_effect = lambda a: a
        conn.w3.eth.call.return_value = (5).to_bytes(32, "big")
        assert conn._dw_nonce(DW) == 5


class TestDeployDw:
    """deploy_dw handler: idempotent relayer provisioning of the DW."""

    def test_deploy_existing(self) -> None:
        """_deploy_dw returns a registered DW without redeploying."""
        conn = _make_conn()
        conn.dw_address = DW
        conn.relayer_proxy.deployed.return_value = True
        with patch.object(_Conn, "_ensure_dw_funder"):
            resp, err = conn._deploy_dw()
        assert err is None
        assert resp["deployed"] is True
        assert resp["dw_address"] == DW
        conn.relayer_proxy.deploy_dw.assert_not_called()

    def test_deploy_new(self) -> None:
        """_deploy_dw submits a deploy when the DW is not yet registered."""
        conn = _make_conn()
        conn.dw_address = DW
        conn.relayer_proxy.deployed.return_value = False
        conn.relayer_proxy.deploy_dw.return_value = "tx1"
        resp, err = conn._deploy_dw()
        assert err is None
        assert resp["deployed"] is False
        assert resp["transaction_id"] == "tx1"

    def test_deploy_error(self) -> None:
        """_deploy_dw wraps relayer errors."""
        conn = _make_conn()
        conn.dw_address = DW
        conn.relayer_proxy.deployed.side_effect = RelayerProxyError("boom")
        resp, err = conn._deploy_dw()
        assert err


class TestExecWalletBatch:
    """exec_wallet_batch handler — maps to {target,data} calls + nonce read."""

    def test_with_explicit_transactions(self) -> None:
        """Explicit transactions are mapped and forwarded with the DW nonce."""
        conn = _make_conn()
        conn.dw_address = DW
        conn.relayer_proxy.exec_wallet_batch.return_value = "tx2"
        txs = [{"to": COLLAT, "data": "0xab", "value": "0"}]
        with patch.object(_Conn, "_dw_nonce", return_value=5):
            resp, err = conn._exec_wallet_batch(transactions=txs, dw_address=DW)
        assert err is None
        assert resp["transaction_id"] == "tx2"
        call = conn.relayer_proxy.exec_wallet_batch.call_args
        assert call.args[0] == to_checksum_address(DW)
        assert call.args[1] == 5
        assert call.args[2] == [{"target": COLLAT, "data": "0xab"}]

    def test_error(self) -> None:
        """exec_wallet_batch errors are wrapped."""
        conn = _make_conn()
        conn.dw_address = DW
        conn.relayer_proxy.exec_wallet_batch.side_effect = RelayerProxyError("x")
        with patch.object(_Conn, "_dw_nonce", return_value=0):
            resp, err = conn._exec_wallet_batch(transactions=[])
        assert err

    def test_no_dw_address_returns_clear_error(self) -> None:
        """Both arg and instance DW unset yields a clear error, not a TypeError."""
        conn = _make_conn()
        conn.dw_address = None
        resp, err = conn._exec_wallet_batch(transactions=[])
        assert err == "DepositWallet address not available"
        assert resp["error"] == "DepositWallet address not available"

    def test_zero_dw_address_returns_clear_error(self) -> None:
        """A zero-address DW is rejected before signing a meaningless batch."""
        conn = _make_conn()
        resp, err = conn._exec_wallet_batch(transactions=[], dw_address="0x" + "0" * 40)
        assert err == "DepositWallet address not available"
        conn.relayer_proxy.exec_wallet_batch.assert_not_called()


class TestSweepDw:
    """sweep_dw handler."""

    def test_empty_dw_noop(self) -> None:
        """A zero balance is a successful no-op."""
        conn = _make_conn()
        conn.dw_address = DW
        with patch.object(_Conn, "_erc20_balance_of", return_value=0):
            resp, err = conn._sweep_dw()
        assert err is None
        assert resp["swept"] is False
        conn.relayer_proxy.exec_wallet_batch.assert_not_called()

    def test_sweeps_balance(self) -> None:
        """A non-zero balance is transferred DW→Safe via the proxy batch."""
        conn = _make_conn()
        conn.dw_address = DW
        conn.relayer_proxy.exec_wallet_batch.return_value = "tx4"
        with (
            patch.object(_Conn, "_erc20_balance_of", return_value=999),
            patch.object(_Conn, "_dw_nonce", return_value=2),
        ):
            resp, err = conn._sweep_dw()
        assert err is None
        assert resp["swept"] is True
        assert resp["amount"] == 999
        assert resp["transaction_id"] == "tx4"
        call = conn.relayer_proxy.exec_wallet_batch.call_args
        assert call.args[1] == 2
        assert call.args[2][0]["target"] == COLLAT

    def test_sweeps_ctf_position(self) -> None:
        """CTF balances for the given token ids are swept DW→Safe via the batch."""
        conn = _make_conn()
        conn.dw_address = DW
        conn.relayer_proxy.exec_wallet_batch.return_value = "tx5"
        with (
            patch.object(_Conn, "_erc20_balance_of", return_value=0),
            patch.object(_Conn, "_erc1155_balance_of", return_value=4847456),
            patch.object(_Conn, "_dw_nonce", return_value=3),
        ):
            resp, err = conn._sweep_dw(token_ids=[42])
        assert err is None
        assert resp["swept"] is True
        call = conn.relayer_proxy.exec_wallet_batch.call_args
        # a single ERC1155 transfer call targeting the CTF contract
        assert call.args[2][0]["target"] == CTF

    def test_skips_zero_ctf_balance(self) -> None:
        """A token id the DW does not hold is skipped; an empty batch is a no-op."""
        conn = _make_conn()
        conn.dw_address = DW
        with (
            patch.object(_Conn, "_erc20_balance_of", return_value=0),
            patch.object(_Conn, "_erc1155_balance_of", return_value=0),
        ):
            resp, err = conn._sweep_dw(token_ids=[42])
        assert err is None
        assert resp["swept"] is False
        conn.relayer_proxy.exec_wallet_batch.assert_not_called()

    def test_error(self) -> None:
        """sweep_dw errors are wrapped."""
        conn = _make_conn()
        conn.dw_address = DW
        with patch.object(
            _Conn, "_erc20_balance_of", side_effect=RelayerProxyError("x")
        ):
            resp, err = conn._sweep_dw()
        assert err

    def test_no_dw_address_returns_clear_error(self) -> None:
        """Both arg and instance DW unset yields a clear error, not a TypeError."""
        conn = _make_conn()
        conn.dw_address = None
        resp, err = conn._sweep_dw()
        assert err == "DepositWallet address not available"
        assert resp["error"] == "DepositWallet address not available"

    def test_zero_dw_address_returns_clear_error(self) -> None:
        """A zero-address DW is rejected before any balance read or relay."""
        conn = _make_conn()
        resp, err = conn._sweep_dw(dw_address="0x" + "0" * 40)
        assert err == "DepositWallet address not available"
        conn.relayer_proxy.exec_wallet_batch.assert_not_called()


class TestExtractDwFromReceipt:
    """DW address discovery from the deploy receipt's factory log."""

    @staticmethod
    def _topic(hex_str):  # type: ignore[no-untyped-def]
        t = MagicMock()
        t.hex.return_value = hex_str
        return t

    def test_extracts_dw_from_factory_log(self) -> None:
        """topic1 of the factory log decodes to the DW address."""
        conn = _make_conn()
        topic1 = "0x" + "00" * 12 + DW[2:]
        receipt = {
            "logs": [
                {"address": "0xother", "topics": [self._topic("0x00")]},
                {
                    "address": DW_FACTORY,
                    "topics": [self._topic("0xsig"), self._topic(topic1)],
                },
            ]
        }
        conn.w3.eth.get_transaction_receipt.return_value = receipt
        assert conn._extract_dw_from_receipt("0xtx") == to_checksum_address(DW)

    def test_no_factory_log_returns_none(self) -> None:
        """A receipt without a factory log yields None."""
        conn = _make_conn()
        conn.w3.eth.get_transaction_receipt.return_value = {
            "logs": [{"address": "0xother", "topics": [MagicMock()]}]
        }
        assert conn._extract_dw_from_receipt("0xtx") is None

    def test_none_receipt_returns_none(self) -> None:
        """A not-yet-indexed receipt (RPC returns None) yields None, not a crash."""
        conn = _make_conn()
        conn.w3.eth.get_transaction_receipt.return_value = None
        assert conn._extract_dw_from_receipt("0xtx") is None


class TestRelayerTx:
    """Cooperative relayer-tx state poll + deploy-address discovery."""

    def test_in_flight(self) -> None:
        """A non-terminal state is reported as not terminal / not ok."""
        conn = _make_conn()
        conn.relayer_proxy.transaction.return_value = ("STATE_NEW", None)
        resp, err = conn._relayer_tx("tx")
        assert err is None
        assert resp["terminal"] is False
        assert resp["ok"] is False
        assert resp["dw_address"] is None

    def test_mined_deploy_discovers_dw(self) -> None:
        """A mined deploy (is_deploy=True) returns the DW and binds the funder."""
        conn = _make_conn()
        conn.relayer_proxy.transaction.return_value = ("STATE_MINED", "0xhash")
        with (
            patch.object(_Conn, "_extract_dw_from_receipt", return_value=DW),
            patch.object(_Conn, "_ensure_dw_funder") as ensure,
        ):
            resp, err = conn._relayer_tx("tx", is_deploy=True)
        assert err is None
        assert resp["ok"] is True
        assert resp["terminal"] is True
        assert resp["dw_address"] == DW
        ensure.assert_called_once_with(DW)

    def test_mined_deploy_no_dw_in_receipt(self) -> None:
        """A mined deploy whose receipt has no DW log reports ok with no DW."""
        conn = _make_conn()
        conn.relayer_proxy.transaction.return_value = ("STATE_MINED", "0xhash")
        with (
            patch.object(_Conn, "_extract_dw_from_receipt", return_value=None),
            patch.object(_Conn, "_ensure_dw_funder") as ensure,
        ):
            resp, err = conn._relayer_tx("tx", is_deploy=True)
        assert resp["ok"] is True
        assert resp["dw_address"] is None
        ensure.assert_not_called()

    def test_mined_non_deploy_skips_receipt_scan(self) -> None:
        """A mined non-deploy (approval-batch) poll never scans the receipt.

        Deploy and exec_wallet_batch both submit ``to=DW_FACTORY``; scanning a
        non-deploy receipt could otherwise bind a garbage CLOB funder.
        """
        conn = _make_conn()
        conn.relayer_proxy.transaction.return_value = ("STATE_CONFIRMED", "0xhash")
        with (
            patch.object(_Conn, "_extract_dw_from_receipt") as extract,
            patch.object(_Conn, "_ensure_dw_funder") as ensure,
        ):
            resp, err = conn._relayer_tx("tx")
        assert resp["ok"] is True
        assert resp["dw_address"] is None
        extract.assert_not_called()
        ensure.assert_not_called()

    def test_failed(self) -> None:
        """A failed state is terminal but not ok."""
        conn = _make_conn()
        conn.relayer_proxy.transaction.return_value = ("STATE_FAILED", None)
        resp, err = conn._relayer_tx("tx")
        assert resp["terminal"] is True
        assert resp["ok"] is False

    def test_error(self) -> None:
        """relayer_tx wraps relayer errors."""
        conn = _make_conn()
        conn.relayer_proxy.transaction.side_effect = RelayerProxyError("boom")
        resp, err = conn._relayer_tx("tx")
        assert err

    def test_empty_transaction_id(self) -> None:
        """An empty transaction id is rejected without a proxy round-trip."""
        conn = _make_conn()
        resp, err = conn._relayer_tx("")
        assert err == "transaction_id is required"
        conn.relayer_proxy.transaction.assert_not_called()


class TestFunderThreading:
    """place_bet / sell_position bind the DW funder before signing."""

    def test_place_bet_calls_ensure_funder(self) -> None:
        """_place_bet binds the funder before posting the order."""
        conn = _make_conn()
        conn.client.create_market_order.return_value = MagicMock()
        conn.client.post_order.return_value = {"status": "matched"}
        with (
            patch.object(_Conn, "_ensure_dw_funder") as ensure,
            patch(
                "packages.valory.connections.polymarket_client.connection."
                "_serialize_signed_order_v2",
                return_value={},
            ),
        ):
            conn._place_bet(token_id="1", amount=1.0, funder=DW)
        ensure.assert_called_once_with(DW)

    def test_sell_position_calls_ensure_funder(self) -> None:
        """_sell_position binds the funder before posting the order."""
        conn = _make_conn()
        conn.client.create_market_order.return_value = MagicMock()
        conn.client.post_order.return_value = {
            "orderID": "o1",
            "status": "matched",
            "makingAmount": 1,
            "takingAmount": 1,
        }
        with patch.object(_Conn, "_ensure_dw_funder") as ensure:
            conn._sell_position(token_id="1", amount=1.0, funder=DW)
        ensure.assert_called_once_with(DW)
