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
            quote = await self.get_quote(token_address, mon_amount, is_buy=True)
            amount_in_wei = parseMon(mon_amount)
            amount_out_min = calculate_slippage(quote["amount"], slippage_pct)
            
            params = BuyParams(
                token=token_address,
                amount_in=amount_in_wei,
                amount_out_min=amount_out_min,
                to=self.trade.address
            )
            
            tx_hash = await self.trade.buy(params, quote["router"])
            logger.info(f"Buy TX sent: {tx_hash}")
            return tx_hash
        except Exception as e:
            logger.error(f"Buy failed: {e}")
            raise

    async def sell(self, token_address: str, token_amount: int, slippage_pct: int = 5) -> str:
        """Executes a sell transaction."""
        if self.dry_run or not self.trade:
            logger.info(f"[DRY_RUN] SELL {token_amount} tokens of {token_address} (Slippage: {slippage_pct}%)")
            return "0x" + "e" * 64 # Mock tx hash
        
        try:
            # For sell, we need to convert token_amount to mon to get a quote, 
            # OR we can just use get_amount_out directly.
            # get_amount_out(token, amount_in, is_buy=False)
            quote = await self.trade.get_amount_out(token_address, int(token_amount), is_buy=False)
            amount_out_min = calculate_slippage(quote.amount, slippage_pct)
            
            params = SellParams(
                token=token_address,
                amount_in=int(token_amount),
                amount_out_min=amount_out_min,
                to=self.trade.address
            )
            
            tx_hash = await self.trade.sell(params, quote.router)
            logger.info(f"Sell TX sent: {tx_hash}")
            return tx_hash
        except Exception as e:
            logger.error(f"Sell failed: {e}")
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
