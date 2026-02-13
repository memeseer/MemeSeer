import os
import json
import time
import requests
from web3 import Web3
from eth_account import Account

# Constants
REQUIRED_FUNDING_MON = 230.0
LAUNCH_BUDGET_MON = 200.0
SLIPPAGE_BPS = 9500
BUFFER_MON = 0.01


class NadfunExecutor:
    def __init__(self, rpc_url=None, private_key=None):
        self.rpc_url = rpc_url or os.getenv("RPC_URL")
        self.private_key = private_key or os.getenv("PRIVATE_KEY")

        if not self.rpc_url or not self.private_key:
            raise Exception("NadfunExecutor: Missing RPC_URL or PRIVATE_KEY")

        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        self.account = Account.from_key(self.private_key)
        self.address = self.account.address

        self.ROUTER_ADDR = Web3.to_checksum_address("0x6F6B8F1a20703309951a5127c45B49b1CD981A22")
        self.CURVE_ADDR = Web3.to_checksum_address("0xA7283d07812a02AFB7C09B60f8896bCEA3F90aCE")
        self.LENS_ADDR = Web3.to_checksum_address("0x7e78A8DE94f21804F7a17F4E8BF9EC2c872187ea")
        self.SEER_TOKEN = Web3.to_checksum_address(
            os.getenv("SEER_TOKEN_ADDRESS", "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270")
        )

        self.router_abi = self._load_abi("onchain/abi/IBondingCurveRouter.json")
        self.curve_abi = self._load_abi("onchain/abi/BondingCurve.json")
        self.lens_abi = self._load_abi("onchain/abi/Lens.json")

        self.router = self.w3.eth.contract(address=self.ROUTER_ADDR, abi=self.router_abi)
        self.curve = self.w3.eth.contract(address=self.CURVE_ADDR, abi=self.curve_abi)
        self.lens = self.w3.eth.contract(address=self.LENS_ADDR, abi=self.lens_abi)

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
            return

        shortfall = REQUIRED_FUNDING_MON - current
        print(f"Shortfall detected: {shortfall:.2f} MON. Funding via CORE...")
        self.sell_core_for_mon(shortfall)

    def sell_core_for_mon(self, amount_mon_needed):
        print(f"Executing sell for {amount_mon_needed:.2f} MON shortfall...")

        # 1️⃣ decimals
        token_contract = self.w3.eth.contract(
            address=self.SEER_TOKEN,
            abi=[
                {
                    "inputs": [],
                    "name": "decimals",
                    "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
                    "stateMutability": "view",
                    "type": "function",
                }
            ],
        )
        decimals = token_contract.functions.decimals().call()

        # 2️⃣ curve reserves
        reserves = self.curve.functions.curves(self.SEER_TOKEN).call()
        virt_mon = reserves[2]
        virt_token = reserves[3]

        dy = self.w3.to_wei(amount_mon_needed, "ether")
        dy_with_fee = int(dy * 1.01)

        needed_raw = (virt_token * dy_with_fee) // (virt_mon - dy_with_fee)
        print(f"  Quoted {needed_raw / (10**decimals):.6f} SEER for {amount_mon_needed:.2f} MON")

        # 3️⃣ approve first
        erc20 = self.w3.eth.contract(
            address=self.SEER_TOKEN,
            abi=[
                {
                    "name": "approve",
                    "type": "function",
                    "stateMutability": "nonpayable",
                    "inputs": [
                        {"name": "spender", "type": "address"},
                        {"name": "amount", "type": "uint256"},
                    ],
                    "outputs": [{"name": "", "type": "bool"}],
                }
            ],
        )

        nonce = self.w3.eth.get_transaction_count(self.address)

        approve_tx = erc20.functions.approve(
            self.ROUTER_ADDR, needed_raw
        ).build_transaction(
            {
                "from": self.address,
                "nonce": nonce,
                "gasPrice": self.w3.eth.gas_price,
                "chainId": self.w3.eth.chain_id,
            }
        )

        approve_tx["gas"] = int(self.w3.eth.estimate_gas(approve_tx) * 1.2)

        signed_approve = self.w3.eth.account.sign_transaction(approve_tx, self.private_key)
        approve_hash = self.w3.eth.send_raw_transaction(signed_approve.raw_transaction)

        print(f"Approve TX sent: {approve_hash.hex()}")
        approve_receipt = self.w3.eth.wait_for_transaction_receipt(approve_hash)

        if approve_receipt.status != 1:
            raise Exception("Approve failed")

        print("Approve successful.")

        # 4️⃣ sell
        amount_out_min = int(dy * 0.95)
        deadline = int(time.time() + 1200)

        params = (
            needed_raw,
            amount_out_min,
            self.SEER_TOKEN,
            self.address,
            deadline,
        )

        nonce += 1

        sell_tx = self.router.functions.sell(params).build_transaction(
            {
                "from": self.address,
                "nonce": nonce,
                "gasPrice": self.w3.eth.gas_price,
                "chainId": self.w3.eth.chain_id,
            }
        )

        sell_tx["gas"] = int(self.w3.eth.estimate_gas(sell_tx) * 1.2)

        signed_sell = self.w3.eth.account.sign_transaction(sell_tx, self.private_key)
        sell_hash = self.w3.eth.send_raw_transaction(signed_sell.raw_transaction)

        print(f"Sell TX sent: {sell_hash.hex()}")
        receipt = self.w3.eth.wait_for_transaction_receipt(sell_hash)

        if receipt.status != 1:
            raise Exception("CORE sell failed")

        print("CORE sell successful.")

    def launch_token(self, name, symbol, description, image_path):
        self.ensure_mon_balance()
    
        print(f"Launching token {name} ({symbol})...")
    
        # ---------- Retry helper ----------
        def _post_with_retry(url, **kwargs):
            max_retries = 5
            for attempt in range(max_retries):
                resp = requests.post(url, **kwargs)
    
                if resp.status_code == 429:
                    wait_time = 2 ** attempt
                    print(f"[RateLimit] 429 received. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
    
                try:
                    resp.raise_for_status()
                    return resp
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    wait_time = 2 ** attempt
                    print(f"[HTTP Error] Retrying in {wait_time}s...")
                    time.sleep(wait_time)
    
            raise Exception("Max retries exceeded for API call")
    
        # ---------- 1. Upload Image ----------
        with open(image_path, "rb") as f:
            img_resp = _post_with_retry(
                "https://api.nad.fun/metadata/image",
                headers={"Content-Type": "image/png"},
                data=f.read(),
            )
            image_uri = img_resp.json()["image_uri"]
    
        # ---------- 2. Upload Metadata ----------
        meta_resp = _post_with_retry(
            "https://api.nad.fun/metadata/metadata",
            json={
                "image_uri": image_uri,
                "name": name,
                "symbol": symbol,
                "description": description,
            },
        )
        metadata_uri = meta_resp.json()["metadata_uri"]
    
        # ---------- 3. Mine Salt ----------
        salt_resp = _post_with_retry(
            "https://api.nad.fun/token/salt",
            json={
                "creator": self.address,
                "name": name,
                "symbol": symbol,
                "metadata_uri": metadata_uri,
            },
        )
        salt_data = salt_resp.json()
        salt = salt_data["salt"]
        predicted_address = salt_data["address"]
    
        # ---------- 4. On-chain Logic ----------
        deploy_fee = self.curve.functions.feeConfig().call()[0]
        amount_in_wei = self.w3.to_wei(LAUNCH_BUDGET_MON, "ether")
    
        expected_out = self.lens.functions.getInitialBuyAmountOut(amount_in_wei).call()
        amount_out_min = expected_out * SLIPPAGE_BPS // 10000
    
        buffer_wei = self.w3.to_wei(BUFFER_MON, "ether")
        total_value = deploy_fee + amount_in_wei + buffer_wei
    
        params = (
            name,
            symbol,
            metadata_uri,
            amount_out_min,
            salt,
            1,
        )
    
        nonce = self.w3.eth.get_transaction_count(self.address)
    
        tx = self.router.functions.create(params).build_transaction(
            {
                "from": self.address,
                "value": total_value,
                "nonce": nonce,
                "gasPrice": self.w3.eth.gas_price,
                "chainId": self.w3.eth.chain_id,
            }
        )
    
        tx["gas"] = int(self.w3.eth.estimate_gas(tx) * 1.2)
    
        signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
    
        print(f"Launch TX sent: {tx_hash.hex()}")
    
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status != 1:
            raise Exception(f"Launch failed. Status: {receipt.status}")
    
        print(f"Launch successful! Token: {predicted_address}")
    
        return {
            "token_address": predicted_address,
            "tx_hash": tx_hash.hex(),
            "tokens_received_raw": int(expected_out),
        }





