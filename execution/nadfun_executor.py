import os
import asyncio
import logging
from typing import Dict, Any, Optional

try:
    from nadfun_sdk import Trade, BuyParams, SellParams, QuoteResult
    from nadfun_sdk.utils import parseMon, calculate_slippage
except ImportError:
    # Fallback for environments where SDK is not fully installed or for mocking
    Trade = None
    BuyParams = None
    SellParams = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NadFunExecutor")

class NadFunExecutor:
    def __init__(self):
        self.rpc_url = os.getenv("RPC_URL", "")
        self.private_key = os.getenv("PRIVATE_KEY", "")
        self.dry_run = os.getenv("EXECUTION_DRY_RUN", "0") == "1"
        
        if not self.dry_run:
            if not self.rpc_url or not self.private_key:
                logger.warning("RPC_URL or PRIVATE_KEY not set. Falling back to DRY_RUN mode.")
                self.dry_run = True
            else:
                self.trade = Trade(self.rpc_url, self.private_key)
        else:
            logger.info("EXECUTION_DRY_RUN is active. No real transactions will be sent.")
            self.trade = None

    async def get_quote(self, token_address: str, amount_mon: float, is_buy: bool) -> Dict[str, Any]:
        """Gets a quote for a trade."""
        if self.dry_run or not self.trade:
            logger.info(f"[DRY_RUN] Quote for {'buy' if is_buy else 'sell'} {amount_mon} MON on {token_address}")
            # Return a mock quote result
            return {
                "router": "0x" + "0" * 40,
                "amount": int(amount_mon * 10**18 * 1000) if is_buy else int(amount_mon * 10**18 / 1000)
            }
        
        try:
            # SDK amount_in for buy is MON (wei), for sell is Token
            amount_raw = parseMon(amount_mon) if is_buy else int(amount_mon) 
            result = await self.trade.get_amount_out(token_address, amount_raw, is_buy)
            return {
                "router": result.router,
                "amount": result.amount
            }
        except Exception as e:
            logger.error(f"Failed to get quote: {e}")
            raise

    async def buy(self, token_address: str, mon_amount: float, slippage_pct: int = 5) -> str:
        """Executes a buy transaction."""
        if self.dry_run or not self.trade:
            logger.info(f"[DRY_RUN] BUY {mon_amount} MON for {token_address} (Slippage: {slippage_pct}%)")
            return "0x" + "d" * 64 # Mock tx hash
        
        try:
            logger.info("BUY STEP 1: Getting quote...")
            logger.info(f"  Token: {token_address}")
            logger.info(f"  MON amount: {mon_amount}")
            logger.info(f"  Slippage: {slippage_pct}%")
            quote = await self.get_quote(token_address, mon_amount, is_buy=True)
            amount_in_wei = parseMon(mon_amount)
            amount_out_min = calculate_slippage(quote["amount"], slippage_pct)
            logger.info(f"BUY STEP 1 DONE: quote.amount={quote['amount']}, router={quote['router']}")
            logger.info(f"  amount_in_wei={amount_in_wei}, amount_out_min={amount_out_min}")
            
            params = BuyParams(
                token=token_address,
                amount_in=amount_in_wei,
                amount_out_min=amount_out_min,
                to=self.trade.address
            )
            
            logger.info("BUY STEP 2: Executing trade.buy()...")
            logger.info(f"  Owner: {self.trade.address}")
            tx_hash = await self.trade.buy(params, quote["router"])
            logger.info(f"BUY STEP 2 DONE: tx_hash={tx_hash}")
            return tx_hash
        except Exception as e:
            logger.exception("BUY FULL TRACE:")
            raise

    async def sell(self, token_address: str, token_amount: int, slippage_pct: float = 5.0) -> str:
        if not self.trade:
            raise Exception("Trade object not initialized")

        token_address = self.trade.w3.to_checksum_address(token_address)

        logger.info(f"=== SELL START ===")
        logger.info(f"  Token: {token_address}")
        logger.info(f"  Amount in: {token_amount}")
        logger.info(f"  Slippage: {slippage_pct}%")
        logger.info(f"  Owner: {self.trade.address}")

        try:
            # --- 1️⃣ Get quote first (needed for router address + expected out) ---
            logger.info("SELL STEP 1: Getting quote...")
            quote = await self.trade.get_amount_out(token_address, int(token_amount), is_buy=False)
            amount_out_min = calculate_slippage(quote.amount, slippage_pct)
            router_address = quote.router
            logger.info(f"SELL STEP 1 DONE: quote.amount={quote.amount}, router={router_address}")
            logger.info(f"  Min amount out (after {slippage_pct}% slippage): {amount_out_min}")

            # --- 2️⃣ Ensure allowance ---
            logger.info("SELL STEP 2: Checking allowance / approving token spend...")
            ERC20_ABI = [
                {
                    "constant": True,
                    "inputs": [
                        {"name": "_owner", "type": "address"},
                        {"name": "_spender", "type": "address"}
                    ],
                    "name": "allowance",
                    "outputs": [{"name": "", "type": "uint256"}],
                    "type": "function"
                },
                {
                    "constant": False,
                    "inputs": [
                        {"name": "_spender", "type": "address"},
                        {"name": "_value", "type": "uint256"}
                    ],
                    "name": "approve",
                    "outputs": [{"name": "", "type": "bool"}],
                    "type": "function"
                }
            ]

            token_contract = self.trade.w3.eth.contract(
                address=token_address,
                abi=ERC20_ABI
            )

            owner = self.trade.address
            current_allowance = await token_contract.functions.allowance(owner, router_address).call()
            logger.info(f"  Current allowance: {current_allowance}, needed: {token_amount}")

            if current_allowance < token_amount:
                logger.info("  Allowance insufficient. Sending approve transaction...")
                approve_tx = await token_contract.functions.approve(router_address, 2**256 - 1).transact({
                    "from": owner
                })
                await self.trade.wait_for_transaction(approve_tx)
                logger.info("SELL STEP 2 DONE: Approve confirmed")
            else:
                logger.info("SELL STEP 2 DONE: Allowance sufficient, skipping approve")

            # --- 3️⃣ Execute sell ---
            logger.info("SELL STEP 3: Executing trade.sell()...")
            logger.info(f"  Token: {token_address}")
            logger.info(f"  Amount in: {int(token_amount)}")
            logger.info(f"  Min amount out: {amount_out_min}")
            logger.info(f"  Router: {router_address}")

            sell_params = SellParams(
                token=token_address,
                to=self.trade.address,
                amount_in=int(token_amount),
                amount_out_min=amount_out_min,
                deadline=None
            )

            tx_hash = await self.trade.sell(sell_params, router_address)
            logger.info(f"SELL STEP 3 DONE: tx_hash={tx_hash}")
            return tx_hash

        except Exception as e:
            logger.exception("SELL FULL TRACE:")
            raise

    # ----------------
    # BondingCurveRouter Integration
    # ----------------
    async def launch_token_onchain(
        self,
        name: str,
        symbol: str,
        token_uri: str,
        initial_mon: float
    ) -> str:
        """Launch a new token on Monad via nad.fun BondingCurveRouter."""
        if not self.trade:
            raise Exception("Trade object not initialized")

        BONDING_CURVE_ROUTER = "0x6F6B8F1a20703309951a5127c45B49b1CD981A22"
        
        BONDING_CURVE_ROUTER_ABI = [
            {
                "inputs": [
                    {
                        "components": [
                            {"internalType": "string", "name": "name", "type": "string"},
                            {"internalType": "string", "name": "symbol", "type": "string"},
                            {"internalType": "string", "name": "tokenURI", "type": "string"},
                            {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
                            {"internalType": "bytes32", "name": "salt", "type": "bytes32"},
                            {"internalType": "uint8", "name": "actionId", "type": "uint8"}
                        ],
                        "internalType": "struct CreateParams",
                        "name": "params",
                        "type": "tuple"
                    }
                ],
                "name": "create",
                "outputs": [],
                "stateMutability": "payable",
                "type": "function"
            },
            {
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "internalType": "address", "name": "creator", "type": "address"},
                    {"indexed": True, "internalType": "address", "name": "token", "type": "address"},
                    {"indexed": False, "internalType": "address", "name": "pool", "type": "address"},
                    {"indexed": False, "internalType": "string", "name": "name", "type": "string"},
                    {"indexed": False, "internalType": "string", "name": "symbol", "type": "string"},
                    {"indexed": False, "internalType": "string", "name": "tokenURI", "type": "string"},
                    {"indexed": False, "internalType": "uint256", "name": "virtualMonReserve", "type": "uint256"},
                    {"indexed": False, "internalType": "uint256", "name": "virtualTokenReserve", "type": "uint256"},
                    {"indexed": False, "internalType": "uint256", "name": "targetTokenAmount", "type": "uint256"}
                ],
                "name": "CurveCreate",
                "type": "event"
            }
        ]

        logger.info("=== LAUNCH TOKEN START ===")
        logger.info(f"  Name: {name}")
        logger.info(f"  Symbol: {symbol}")
        logger.info(f"  Token URI: {token_uri}")
        logger.info(f"  Initial MON: {initial_mon}")

        try:
            # Instantiate router contract
            router = self.trade.w3.eth.contract(
                address=self.trade.w3.to_checksum_address(BONDING_CURVE_ROUTER),
                abi=BONDING_CURVE_ROUTER_ABI
            )

            # Convert MON to wei
            initial_mon_wei = self.trade.w3.to_wei(initial_mon, 'ether')

            # Generate random salt
            salt = os.urandom(32)

            logger.info("LAUNCH STEP 1: Sending create transaction...")
            logger.info(f"  Router: {BONDING_CURVE_ROUTER}")
            logger.info(f"  Initial MON (wei): {initial_mon_wei}")
            logger.info(f"  Salt: 0x{salt.hex()}")

            # Build create params tuple
            create_params = (
                name,
                symbol,
                token_uri,
                0,              # amountOut (we rely on value)
                salt,
                0               # actionId
            )

            # Send create transaction
            tx_hash = router.functions.create(create_params).transact({
                "from": self.trade.address,
                "value": initial_mon_wei
            })

            logger.info(f"LAUNCH STEP 2: Waiting for receipt (tx: {tx_hash})...")

            # Wait for receipt
            receipt = await self.trade.wait_for_transaction(tx_hash)

            if not receipt or receipt.get("status") != 1:
                raise Exception(f"Launch transaction failed. Receipt: {receipt}")

            logger.info("LAUNCH STEP 3: Parsing CurveCreate event...")

            # Parse CurveCreate event
            events = router.events.CurveCreate().process_receipt(receipt)

            if not events:
                raise Exception("CurveCreate event not found in receipt")

            token_address = events[0]['args']['token']
            token_address_checksum = self.trade.w3.to_checksum_address(token_address)

            logger.info(f"LAUNCH STEP 4: Token address found: {token_address_checksum}")
            logger.info(f"  Pool: {events[0]['args']['pool']}")
            logger.info(f"  Virtual MON Reserve: {events[0]['args']['virtualMonReserve']}")
            logger.info(f"  Virtual Token Reserve: {events[0]['args']['virtualTokenReserve']}")

            return token_address_checksum

        except Exception as e:
            logger.exception("LAUNCH FULL TRACE:")
            raise

    async def wait_for_receipt(self, tx_hash: str, timeout: int = 60) -> Optional[Dict[str, Any]]:
        """Waits for transaction receipt."""
        if self.dry_run or not self.trade:
            logger.info(f"[DRY_RUN] Waiting for receipt of {tx_hash}")
            return {"status": 1, "transactionHash": tx_hash}
        
        try:
            receipt = await self.trade.wait_for_transaction(tx_hash, timeout)
            if not receipt:
                logger.error(f"Receipt is None for {tx_hash}")
                return None
            logger.info(f"Receipt received for {tx_hash}: status={receipt.get('status')}")
            return receipt
        except Exception as e:
            logger.error(f"Failed to get receipt: {e}")
            raise

# Synchronous wrappers for easier integration if needed
def sync_buy(token_address, mon_amount, slippage_pct=5):
    executor = NadFunExecutor()
    return asyncio.run(executor.buy(token_address, mon_amount, slippage_pct))

def sync_sell(token_address, token_amount, slippage_pct=5):
    executor = NadFunExecutor()
    return asyncio.run(executor.sell(token_address, token_amount, slippage_pct))

def sync_wait_for_receipt(tx_hash, timeout=60):
    executor = NadFunExecutor()
    return asyncio.run(executor.wait_for_receipt(tx_hash, timeout))
