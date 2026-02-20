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
            raise Exception("Missing RPC_URL or PRIVATE_KEY")

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

    # --------------------------------------------------
    # Balance
    # --------------------------------------------------

    def get_mon_balance(self):
        balance_wei = self.w3.eth.get_balance(self.address)
        return float(self.w3.from_wei(balance_wei, "ether"))

    # --------------------------------------------------
    # Funding (SAFE)
    # --------------------------------------------------

    def ensure_mon_balance(self) -> bool:
        current = self.get_mon_balance()
        print(f"Current MON balance: {current:.2f}")

        if current >= REQUIRED_FUNDING_MON:
            print("Balance sufficient.")
            return True

        shortfall = REQUIRED_FUNDING_MON - current
        print(f"Shortfall detected: {shortfall:.2f} MON")

        return self.sell_core_for_mon(shortfall)

    def sell_core_for_mon(self, amount_mon_needed: float) -> bool:
        print(f"Attempting CORE sell for {amount_mon_needed:.2f} MON")

        # --- ERC20 minimal ABI ---
        erc20 = self.w3.eth.contract(
            address=self.SEER_TOKEN,
            abi=[
                {
                    "name": "balanceOf",
                    "type": "function",
                    "stateMutability": "view",
                    "inputs": [{"name": "account", "type": "address"}],
                    "outputs": [{"name": "", "type": "uint256"}],
                },
                {
                    "name": "allowance",
                    "type": "function",
                    "stateMutability": "view",
                    "inputs": [
                        {"name": "owner", "type": "address"},
                        {"name": "spender", "type": "address"},
                    ],
                    "outputs": [{"name": "", "type": "uint256"}],
                },
                {
                    "name": "approve",
                    "type": "function",
                    "stateMutability": "nonpayable",
                    "inputs": [
                        {"name": "spender", "type": "address"},
                        {"name": "amount", "type": "uint256"},
                    ],
                    "outputs": [{"name": "", "type": "bool"}],
                },
            ],
        )

        balance_raw = erc20.functions.balanceOf(self.address).call()
        amount_out_target = self.w3.to_wei(amount_mon_needed, "ether")

        try:
            router_addr, required_in = self.lens.functions.getAmountIn(
                self.SEER_TOKEN,
                amount_out_target,
                False
            ).call()
        except Exception as e:
            print(f"[FUNDING QUOTE ERROR] {e}")
            return False

        if required_in > balance_raw:
            print("Not enough SEER to fund launch.")
            return False

        allowance = erc20.functions.allowance(
            self.address,
            self.ROUTER_ADDR
        ).call()

        if allowance < required_in:
            nonce = self.w3.eth.get_transaction_count(self.address)

            approve_tx = erc20.functions.approve(
                self.ROUTER_ADDR,
                required_in
            ).build_transaction({
                "from": self.address,
                "nonce": nonce,
                "gasPrice": self.w3.eth.gas_price,
                "chainId": self.w3.eth.chain_id,
            })

            approve_tx["gas"] = int(self.w3.eth.estimate_gas(approve_tx) * 1.2)

            signed = self.w3.eth.account.sign_transaction(approve_tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            self.w3.eth.wait_for_transaction_receipt(tx_hash)

        print("Funding possible.")
        return True

    # --------------------------------------------------
    # Sell Meme Token (UNCHANGED WORKING LOGIC)
    # --------------------------------------------------

    async def sell(self, token_address: str, amount_raw: int):

        token_address = Web3.to_checksum_address(token_address)

        nonce = self.w3.eth.get_transaction_count(self.address)

        erc20 = self.w3.eth.contract(
            address=token_address,
            abi=[{
                "name": "approve",
                "type": "function",
                "stateMutability": "nonpayable",
                "inputs": [
                    {"name": "spender", "type": "address"},
                    {"name": "amount", "type": "uint256"},
                ],
                "outputs": [{"name": "", "type": "bool"}],
            }]
        )

        approve_tx = erc20.functions.approve(
            self.ROUTER_ADDR,
            amount_raw
        ).build_transaction({
            "from": self.address,
            "nonce": nonce,
            "gasPrice": self.w3.eth.gas_price,
            "chainId": self.w3.eth.chain_id,
        })

        approve_tx["gas"] = int(self.w3.eth.estimate_gas(approve_tx) * 1.2)

        signed_approve = self.w3.eth.account.sign_transaction(approve_tx, self.private_key)
        approve_hash = self.w3.eth.send_raw_transaction(signed_approve.raw_transaction)
        self.w3.eth.wait_for_transaction_receipt(approve_hash)

        router_addr, amount_out = self.lens.functions.getAmountOut(
            token_address,
            amount_raw,
            False
        ).call()

        if amount_out <= 0:
            raise Exception("No liquidity")

        router = self.w3.eth.contract(
            address=Web3.to_checksum_address(router_addr),
            abi=self.router_abi
        )

        amount_out_min = int(amount_out * 0.95)
        deadline = int(time.time() + 1200)

        params = (
            amount_raw,
            amount_out_min,
            token_address,
            self.address,
            deadline
        )

        nonce = self.w3.eth.get_transaction_count(self.address)

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

    # --------------------------------------------------
    # Receipt
    # --------------------------------------------------

    def wait_for_receipt(self, tx_hash):
        if isinstance(tx_hash, str):
            tx_hash = Web3.to_bytes(hexstr=tx_hash)
        return self.w3.eth.wait_for_transaction_receipt(tx_hash)

    # --------------------------------------------------
    # Launch (SAFE)
    # --------------------------------------------------

    def launch_token(self, name, symbol, description, image_path):

        if not self.ensure_mon_balance():
            print("Launch aborted: insufficient funding")
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
            json={
                "image_uri": image_uri,
                "name": name,
                "symbol": symbol,
                "description": description
            }
        )
        meta_resp.raise_for_status()
        metadata_uri = meta_resp.json()["metadata_uri"]

        salt_resp = requests.post(
            "https://api.nad.fun/token/salt",
            json={
                "creator": self.address,
                "name": name,
                "symbol": symbol,
                "metadata_uri": metadata_uri
            }
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

        params = (
            name,
            symbol,
            metadata_uri,
            amount_out_min,
            salt,
            1,
        )

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

        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)

        if receipt.status != 1:
            raise Exception("Launch failed")

        print(f"Launch successful! Token: {predicted_address}")

        return {
            "token_address": predicted_address,
            "tx_hash": tx_hash.hex(),
            "tokens_received_raw": int(expected_out)
        }
