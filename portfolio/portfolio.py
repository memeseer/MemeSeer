import os
import json
import time
import asyncio
from typing import Any, Dict, Optional
from economy import apply_flywheel
from onchain.nadfun_executor import NadfunExecutor

# Constants
TRAILING_FACTOR = 0.7

def utc_now_ts() -> int:
    return int(time.time())

def append_event(memory: Dict[str, Any], event: Dict[str, Any]) -> None:
    event = dict(event)
    event.setdefault("ts", utc_now_ts())
    memory.setdefault("events", [])
    memory["events"].append(event)
    max_events = int(os.getenv("MEMESEER_MAX_EVENTS", "500"))
    if len(memory["events"]) > max_events:
        memory["events"] = memory["events"][-max_events:]

def get_active_positions(memory: Dict[str, Any]) -> list:
    """Returns all positions that are currently being managed (not closed)."""
    return [
        p for p in memory.get("portfolio", {}).get("active_positions", []) 
        if p.get("status") in ("EARLY", "ACTIVE", "EXITING", "MOON_BAG")
    ]

def get_blocking_positions(memory: Dict[str, Any]) -> list:
    """Returns positions that count toward the active limit (excludes MOON_BAG)."""
    return [
        p for p in memory.get("portfolio", {}).get("active_positions", [])
        if p.get("status") in ["EARLY", "ACTIVE", "EXITING"]
    ]

def manage_portfolio(memory: Dict[str, Any]) -> None:
    """Manages active positions: profit ladder, dead token rules, and MOON_BAG trailing exit."""
    active_positions = memory.get("portfolio", {}).get("active_positions", [])
    if not active_positions:
        return

    current_ts = utc_now_ts()
    executor = NadfunExecutor()
    dry_run = os.getenv("EXECUTION_DRY_RUN", "0") == "1"


    def save_mem():
        # Using the same logic as main.py save_memory
        path = os.getenv("MEMESEER_MEMORY_PATH", "memory.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(memory, f, indent=2, ensure_ascii=False, allow_nan=False)
        os.replace(tmp, path)

    # ----------------
    # Sell Helper
    # ----------------
    def execute_position_sell(pos, sell_frac, event_type, extra_event_data=None):
        ticker = pos.get("ticker", "TKN")
        token_address = pos.get("address")
        token_amount = pos.get("token_amount", 0)
        
        if pos.get("tx_pending", False):
            print(f"[{ticker}] Sell skipped: TX already pending")
            return False

        sell_amount = int(token_amount * sell_frac)
        if sell_amount <= 0:
            return False

        # Mark as pending and save immediately
        pos["tx_pending"] = True
        save_mem()

        try:
            print(f"[{ticker}] Executing {event_type} sell: {sell_amount} tokens")
            tx_hash = ""
            if dry_run:
                tx_hash = "0x" + "d" * 64
                receipt = {"status": 1, "transactionHash": tx_hash}
            else:
                tx_hash = asyncio.run(executor.sell(token_address, sell_amount))
                append_event(memory, {"type": "onchain_sell_sent", "ticker": ticker, "tx_hash": tx_hash})
                receipt = asyncio.run(executor.wait_for_receipt(tx_hash))

            if not receipt or receipt.get("status") != 1:
                print(f"[{ticker}] Sell failed: Receipt status != 1")
                pos["tx_pending"] = False
                append_event(memory, {"type": "sell_failed", "ticker": ticker, "tx_hash": tx_hash, "reason": "receipt_failed"})
                save_mem()
                return False

            # SUCCESS - Commit changes
            # We need the current MON value for flywheel. 
            # We'll use a conservative estimate: (sell_amount / total_amount) * current_total_value
            # For simplicity, we'll pass the payout if we have it or calculate it.
            # (Note: In a real bot, we'd get payout from the receipt/logs)
            
            # For now, we'll use the valuation from the start of the loop
            # payout = current_value_mon * sell_frac
            # But wait, execute_position_sell needs access to current_value_mon
            # Let's assume we pass it in.
            
            payout_estimated = pos.get("_current_valuation_mon", 0) * sell_frac
            
            # Apply flywheel ONLY on success
            apply_flywheel(memory, payout_estimated, stake_mon=0.0, buyback_pct=0.5, burn_pct=0.0)
            
            # Update state
            pos["token_amount"] = token_amount - sell_amount
            
            # Update sold_pct_total correctly relative to total
            current_sold_pct = pos.get("sold_pct_total", 0.0)
            remaining_pct = 100.0 - current_sold_pct
            added_pct = remaining_pct * sell_frac
            pos["sold_pct_total"] = current_sold_pct + added_pct
            
            pos["tx_pending"] = False
            
            event_data = {
                "type": event_type, 
                "ticker": ticker, 
                "tx_hash": tx_hash, 
                "payout": payout_estimated,
                "sell_pct": sell_frac * 100.0
            }
            if extra_event_data:
                event_data.update(extra_event_data)
            append_event(memory, event_data)
            
            save_mem()
            return True

        except Exception as e:
            print(f"[{ticker}] Sell exception: {e}")
            pos["tx_pending"] = False
            append_event(memory, {"type": "sell_failed", "ticker": ticker, "reason": str(e)})
            save_mem()
            return False

    # ----------------
    # Main loop
    # ----------------
    # We iterate over a copy or handle list updates safely
    for pos in list(active_positions):
        status = pos.get("status")
        if status not in ["EARLY", "ACTIVE", "EXITING", "MOON_BAG"]:
            continue

        ticker = pos.get("ticker", "TKN")
        token_address = pos.get("address")
        if not token_address:
            continue

        try:
            # 1. Fetch current price/valuation
            token_amount = pos.get("token_amount", 0)
            if token_amount <= 0:
                continue

            # --- Fix get_quote misuse ---
            # get_quote for sell expects TOKEN amount. We'll ask for value of total position.
            token_amount_float = float(token_amount)
            res = asyncio.run(executor.get_quote(token_address, token_amount_float, is_buy=False))
            current_value_mon = float(res.get("amount", 0.0)) / 10**18
            
            pos["_current_valuation_mon"] = current_value_mon # Store for helper
            
            entry_cost = pos.get("entry_cost_mon", 1.0)
            sold_pct = pos.get("sold_pct_total", 0.0)
            
            denominator = (1.0 - (sold_pct / 100.0))
            if denominator <= 0: # already sold everything or error
                 current_multiple = 0
            else:
                 current_multiple = (current_value_mon / denominator) / entry_cost if entry_cost > 0 else 0
            
            # Round multiple to avoid floating point issues in comparisons and storage
            current_multiple = round(current_multiple, 4)
            roi = current_multiple - 1.0
            
            print(f"[{ticker}] Status: {status}, ROI: {roi*100:.1f}%, Multiple: {current_multiple:.2f}x")

            if status in ["EARLY", "ACTIVE", "EXITING"]:
                # --- LADDER LOGIC ---
                ladder_targets = [1.0, 3.0, 6.0] # ROI points (100%, 300%, 600%)
                for target in ladder_targets:
                    hit_key = f"{int(target*100)}"
                    if roi >= target and hit_key not in pos.get("ladder_hits", []):
                        # Hit! Sell 20% of CURRENT allocation
                        if execute_position_sell(pos, 0.2, "ladder_hit", {"target": hit_key}):
                            pos.setdefault("ladder_hits", []).append(hit_key)
                            # After sell, token_amount is updated, so we might skip further targets in this loop
                            # or just continue. The tx_pending will block if we try again immediately.
                            break

                # --- DEAD TOKEN RULE ---
                days_passed = (current_ts - pos.get("timestamp", 0)) / (24 * 3600)
                if days_passed >= 4 and not pos.get("ladder_hits"):
                    pos["status"] = "EXITING"
                    execute_position_sell(pos, 0.15, "dead_exit_step")

                # --- MOON_BAG TRANSITION CHECK ---
                if pos.get("status") == "ACTIVE":
                    hits = pos.get("ladder_hits", [])
                    sm = pos.get("sold_pct_total", 0)
                    if all(h in hits for h in ["100", "300", "600"]) and \
                       sm >= 60 and \
                       current_multiple >= 7.0:
                        
                        pos["status"] = "MOON_BAG"
                        pos["moonbag"] = {
                            "ath_multiple": current_multiple,
                            "last_trailing_sell_multiple": None,
                            "activated_timestamp": current_ts
                        }
                        append_event(memory, {"type": "moonbag_activated", "ticker": ticker, "multiple": current_multiple})
                        save_mem()

            elif status == "MOON_BAG":
                # --- MOON_BAG LOGIC ---
                mb = pos.get("moonbag", {})
                
                # Update ATH
                if current_multiple > mb.get("ath_multiple", 0):
                    mb["ath_multiple"] = current_multiple
                    
                # Trailing Exit Logic
                ath = mb.get("ath_multiple", 0)
                last = mb.get("last_trailing_sell_multiple")
                
                threshold = ath * TRAILING_FACTOR
                
                if current_multiple < round(threshold, 4):
                    if last is None or current_multiple < round(last * 0.95, 4):
                        # Trigger! Sell 20% of remaining allocation
                        if execute_position_sell(pos, 0.20, "moonbag_trailing_sell", {"multiple": current_multiple}):
                            mb["last_trailing_sell_multiple"] = current_multiple

            # --- CLOSE CONDITION ---
            if pos.get("sold_pct_total", 0.0) >= 99:
                pos["status"] = "CLOSED"
                
                # Update loss streak
                guard = memory.setdefault("core_guard", {})
                if roi < 0.0: # Loss = Multiple < 1.0 (ROI < 0)
                    guard["loss_streak"] = guard.get("loss_streak", 0) + 1
                else:
                    guard["loss_streak"] = 0
                
                if guard["loss_streak"] >= 3:
                    guard["launch_blocked_until"] = current_ts + (48 * 3600)
                    append_event(memory, {"type": "core_guard_blocked_loss_streak", "ticker": ticker, "streak": guard["loss_streak"]})

                # Move to closed positions safely
                memory.setdefault("portfolio", {}).setdefault("closed_positions", [])
                # Avoid duplicates if manage_portfolio runs twice before memory save
                if pos not in memory["portfolio"]["closed_positions"]:
                    memory["portfolio"]["closed_positions"].append(pos)
                if pos in memory["portfolio"]["active_positions"]:
                    memory["portfolio"]["active_positions"].remove(pos)
                
                append_event(memory, {"type": "position_closed", "ticker": ticker, "reason": "full_exit", "roi": round(roi, 4)})
                save_mem()

        except Exception as e:
            print(f"Error managing position {ticker}: {e}")
            # Reset tx_pending if it crashed unexpectedly during loop logic
            if pos.get("tx_pending"):
                pos["tx_pending"] = False
                save_mem()



