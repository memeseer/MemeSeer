import os
import json
import time
import requests
import secrets
import asyncio
from web3 import Web3
from eth_account import Account

# Constants
REQUIRED_FUNDING_MON = 230.0  # Threshold to trigger funding
LAUNCH_BUDGET_MON = 200.0     # Final budget for launch
SLIPPAGE_BPS = 9500           # 95% for min amount out
BUFFER_MON = 0.01

def utc_now_ts():
    return int(time.time())

class NadfunExecutor:
    def __init__(self, rpc_url=None, private_key=None):
        self.rpc_url = rpc_url or os.getenv("RPC_URL")
        self.private_key = private_key or os.getenv("PRIVATE_KEY")
        if not self.rpc_url or not self.private_key:
            raise Exception("NadfunExecutor: Missing RPC_URL or PRIVATE_KEY")

        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        self.account = Account.from_key(self.private_key)
        self.address = self.account.address

        # Addresses
        self.ROUTER_ADDR = Web3.to_checksum_address("0x6F6B8F1a20703309951a5127c45B49b1CD981A22")
        self.CURVE_ADDR = Web3.to_checksum_address("0xA7283d07812a02AFB7C09B60f8896bCEA3F90aCE")
        self.LENS_ADDR = Web3.to_checksum_address("0x7e78A8DE94f21804F7a17F4E8BF9EC2c872187ea")
        self.SEER_TOKEN = Web3.to_checksum_address(os.getenv("SEER_TOKEN_ADDRESS", "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"))

        # Load ABIs
        self.router_abi = self._load_abi("onchain/abi/IBondingCurveRouter.json")
        self.curve_abi = self._load_abi("onchain/abi/BondingCurve.json")
        self.lens_abi = self._load_abi("onchain/abi/Lens.json")

        self.router = self.w3.eth.contract(address=self.ROUTER_ADDR, abi=self.router_abi)
        self.curve = self.w3.eth.contract(address=self.CURVE_ADDR, abi=self.curve_abi)
        self.lens = self.w3.eth.contract(address=self.LENS_ADDR, abi=self.lens_abi)

        self.dry_run = os.getenv("EXECUTION_DRY_RUN", "0") == "1"

        # Track skipped launches
        self.skip_until = {}

    def _load_abi(self, path):
        with open(path, "r") as f:
            return json.load(f)

    def get_mon_balance(self):
        balance_wei = self.w3.eth.get_balance(self.address)
        return float(self.w3.from_wei(balance_wei, "ether"))

    def ensure_mon_balance(self):
        current = self.get_mon_balance()
        print(f"Current MON balance: {current:.2f}")
        if current >= REQUIRED_FUNDING_MON:
            print("Balance sufficient.")
            return True
        shortfall = REQUIRED_FUNDING_MON - current
        print(f"Shortfall detected: {shortfall:.2f} MON. Funding via CORE...")
        return self.sell_core_for_mon(shortfall)

    def sell_core_for_mon(self, amount_mon_needed):
        print(f"Executing sell for {amount_mon_needed:.2f} MON shortfall...")

        ERC20_ABI = [
            {"constant": True, "inputs": [{"name":"_owner","type":"address"}], "name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},
            {"constant": True, "inputs": [], "name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"},
            {"constant": False, "inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}], "name":"approve","outputs":[{"name":"success","type":"bool"}],"type":"function"}
        ]

        try:
            token_contract = self.w3.eth.contract(address=self.SEER_TOKEN, abi=ERC20_ABI)
            decimals = token_contract.functions.decimals().call()
            balance_seer = token_contract.functions.balanceOf(self.address).call()
        except Exception as e:
            print(f"[WARN] Cannot access SEER ERC20 contract: {e}, skipping sell")
            return False

        if balance_seer <= 0:
            print("[WARN] No SEER balance available for sale, skipping")
            return False

        try:
            reserves = self.curve.functions.curves(self.SEER_TOKEN).call()
            virt_mon = reserves[2]
            virt_token = reserves[3]
            dy = self.w3.to_wei(amount_mon_needed, "ether")
            dy_with_fee = int(dy * 1.01)
            needed_raw = (virt_token * dy_with_fee) // (virt_mon - dy_with_fee)
        except Exception as e:
            print(f"[WARN] Cannot read curve reserves: {e}, skipping sell")
            return False

        if needed_raw > balance_seer:
            print(f"[WARN] Not enough SEER ({balance_seer/10**decimals:.6f}) for required {needed_raw/10**decimals:.6f}, skipping")
            return False

        print(f"  Selling {needed_raw / 10**decimals:.6f} SEER for ~{amount_mon_needed:.2f} MON")

        try:
            erc20 = self.w3.eth.contract(address=self.SEER_TOKEN, abi=ERC20_ABI)
            nonce = self.w3.eth.get_transaction_count(self.address)
            approve_tx = erc20.functions.approve(self.ROUTER_ADDR, needed_raw).build_transaction({
                "from": self.address,
                "nonce": nonce,
                "gasPrice": self.w3.eth.gas_price,
                "chainId": self.w3.eth.chain_id,
            })
            approve_tx["gas"] = int(self.w3.eth.estimate_gas(approve_tx) * 1.2)
            signed_approve = self.w3.eth.account.sign_transaction(approve_tx, self.private_key)
            approve_hash = self.w3.eth.send_raw_transaction(signed_approve.raw_transaction)
            self.w3.eth.wait_for_transaction_receipt(approve_hash)
            print("Approve successful.")
        except Exception as e:
            print(f"[WARN] Approve failed: {e}, skipping sell")
            return False

        try:
            amount_out_min = int(dy * 0.95)
            deadline = int(time.time() + 1200)
            params = (needed_raw, amount_out_min, self.SEER_TOKEN, self.address, deadline)
            nonce += 1
            sell_tx = self.router.functions.sell(params).build_transaction({
                "from": self.address,
                "nonce": nonce,
                "gasPrice": self.w3.eth.gas_price,
                "chainId": self.w3.eth.chain_id,
            })
            sell_tx["gas"] = int(self.w3.eth.estimate_gas(sell_tx) * 1.2)
            signed_sell = self.w3.eth.account.sign_transaction(sell_tx, self.private_key)
            sell_hash = self.w3.eth.send_raw_transaction(signed_sell.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(sell_hash)
            if receipt.status != 1:
                print("[WARN] Sell failed on-chain")
                return False
            print("CORE sell successful.")
            return True
        except Exception as e:
            print(f"[WARN] Sell execution failed: {e}, skipping")
            return False

    async def get_quote(self, token_address: str, amount: float, is_buy: bool):
        token_address = Web3.to_checksum_address(token_address)
        try:
            if is_buy:
                amount_wei = self.w3.to_wei(amount, "ether")
                router, amount_out = self.lens.functions.getAmountOut(token_address, amount_wei, True).call()
            else:
                router, amount_out = self.lens.functions.getAmountOut(token_address, int(amount), False).call()
            return {"amount": int(amount_out)}
        except Exception as e:
            print(f"[QUOTE ERROR] {e}")
            return {"amount": 0}

    async def sell(self, token_address: str, amount_raw: int):
        token_address = Web3.to_checksum_address(token_address)
        if self.dry_run:
            print(f"[DRY RUN] Sell {amount_raw} tokens skipped")
            return "0x" + "d"*64

        nonce = self.w3.eth.get_transaction_count(self.address)
        erc20 = self.w3.eth.contract(
            address=token_address,
            abi=[{
                "name": "approve",
                "type": "function",
                "stateMutability": "nonpayable",
                "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
                "outputs": [{"name": "", "type": "bool"}],
            }]
        )
        approve_tx = erc20.functions.approve(self.ROUTER_ADDR, amount_raw).build_transaction({
            "from": self.address,
            "nonce": nonce,
            "gasPrice": self.w3.eth.gas_price,
            "chainId": self.w3.eth.chain_id,
        })
        approve_tx["gas"] = int(self.w3.eth.estimate_gas(approve_tx) * 1.2)
        signed_approve = self.w3.eth.account.sign_transaction(approve_tx, self.private_key)
        approve_hash = self.w3.eth.send_raw_transaction(signed_approve.raw_transaction)
        self.w3.eth.wait_for_transaction_receipt(approve_hash)

        router_addr, amount_out = self.lens.functions.getAmountOut(token_address, amount_raw, False).call()
        router_addr = Web3.to_checksum_address(router_addr)
        router = self.w3.eth.contract(address=router_addr, abi=self.router_abi)

        amount_out_min = int(amount_out * 0.95)
        deadline = int(time.time() + 1200)
        params = (amount_raw, amount_out_min, token_address, self.address, deadline)

        nonce += 1
        sell_tx = router.functions.sell(params).build_transaction({
            "from": self.address,
            "nonce": nonce,
            "gasPrice": self.w3.eth.gas_price,
            "chainId": self.w3.eth.chain_id,
        })
        sell_tx["gas"] = int(self.w3.eth.estimate_gas(sell_tx) * 1.2)
        signed_sell = self.w3.eth.account.sign_transaction(sell_tx, self.private_key)
        sell_hash = self.w3.eth.send_raw_transaction(signed_sell.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(sell_hash)
        if receipt.status != 1:
            raise Exception("Sell failed")
        return sell_hash.hex()

    def wait_for_receipt(self, tx_hash):
        if isinstance(tx_hash, str):
            tx_hash = Web3.to_bytes(hexstr=tx_hash)
        return self.w3.eth.wait_for_transaction_receipt(tx_hash)

    def launch_token(self, name, symbol, description, image_path):
        # Check 24h skip
        if symbol in self.skip_until and utc_now_ts() < self.skip_until[symbol]:
            print(f"[SKPT] Skipping launch for {symbol}, wait until {self.skip_until[symbol]}")
            return None

        # Ensure MON balance
        if not self.ensure_mon_balance():
            print(f"[SKPT] Not enough MON to launch {symbol}, skipping 24h")
            self.skip_until[symbol] = utc_now_ts() + 24*3600
            return None

        print(f"Launching token {name} ({symbol})...")

        with open(image_path, "rb") as f:
            img_resp = requests.post(
                "https://api.nad.fun/metadata/image",
                headers={"Content-Type": "image/png"},
                data=f.read()
            )
            img_resp.raise_for_status()
            image_uri = img_resp.json()["image_uri"]

        meta_resp = requests.post(
            "https://api.nad.fun/metadata/metadata",
            json={"image_uri": image_uri, "name": name, "symbol": symbol, "description": description}
        )
        meta_resp.raise_for_status()
        metadata_uri = meta_resp.json()["metadata_uri"]

        salt_resp = requests.post(
            "https://api.nad.fun/token/salt",
            json={"creator": self.address, "name": name, "symbol": symbol, "metadata_uri": metadata_uri}
        )
        salt_resp.raise_for_status()
        salt_data = salt_resp.json()
        salt = salt_data["salt"]
        predicted_address = salt_data["address"]

        deploy_fee = self.curve.functions.feeConfig().call()[0]
        amount_in_wei = self.w3.to_wei(LAUNCH_BUDGET_MON, "ether")
        expected_out = self.lens.functions.getInitialBuyAmountOut(amount_in_wei).call()
        amount_out_min = expected_out * SLIPPAGE_BPS // 10000
        buffer_wei = self.w3.to_wei(BUFFER_MON, "ether")
        total_value = deploy_fee + amount_in_wei + buffer_wei

        params = (name, symbol, metadata_uri, amount_out_min, salt, 1)
        nonce = self.w3.eth.get_transaction_count(self.address)
        tx = self.router.functions.create(params).build_transaction({
            "from": self.address,
            "value": total_value,
            "nonce": nonce,
            "gasPrice": self.w3.eth.gas_price,
            "chainId": self.w3.eth.chain_id
        })
        tx["gas"] = int(self.w3.eth.estimate_gas(tx) * 1.2)
        signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"Launch TX sent: {tx_hash.hex()}")

        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status != 1:
            raise Exception(f"Launch failed. Status: {receipt.status}")

        print(f"Launch successful! Token: {predicted_address}")
        return {"token_address": predicted_address, "tx_hash": tx_hash.hex(), "tokens_received_raw": int(expected_out)}





