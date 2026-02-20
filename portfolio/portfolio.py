import os
import json
import time
import asyncio
from typing import Any, Dict
from economy import apply_flywheel
from onchain.nadfun_executor import NadfunExecutor

TRAILING_FACTOR = 0.7
EXIT_CHUNK_PCT = 0.20  # 20% fixed from ORIGINAL allocation


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
    return [
        p for p in memory.get("portfolio", {}).get("active_positions", [])
        if p.get("status") in ("EARLY", "ACTIVE", "EXITING", "MOON_BAG")
    ]


def get_blocking_positions(memory: Dict[str, Any]) -> list:
    return [
        p for p in memory.get("portfolio", {}).get("active_positions", [])
        if p.get("status") in ["EARLY", "ACTIVE", "EXITING"]
    ]


def manage_portfolio(memory: Dict[str, Any]) -> None:
    active_positions = memory.get("portfolio", {}).get("active_positions", [])
    if not active_positions:
        return

    current_ts = utc_now_ts()
    executor = NadfunExecutor()
    dry_run = os.getenv("EXECUTION_DRY_RUN", "0") == "1"

    def save_mem():
        path = os.getenv("MEMESEER_MEMORY_PATH", "memory.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(memory, f, indent=2, ensure_ascii=False, allow_nan=False)
        os.replace(tmp, path)

    # --------------------------------------------------
    # SELL HELPER (FIXED 20% OF ORIGINAL ALLOCATION)
    # --------------------------------------------------
    def execute_position_sell(pos, event_type, extra_event_data=None):
        ticker = pos.get("ticker", "TKN")
        token_address = pos.get("address")
        token_amount = pos.get("token_amount", 0)

        if token_amount <= 0:
            return False

        if pos.get("tx_pending", False):
            print(f"[{ticker}] Sell skipped: TX already pending")
            return False

        # Ensure original allocation exists
        if "original_token_amount" not in pos:
            pos["original_token_amount"] = token_amount

        original_amount = pos["original_token_amount"]

        # Fixed chunk from ORIGINAL
        chunk_amount = int(original_amount * EXIT_CHUNK_PCT)

        sell_amount = min(chunk_amount, token_amount)
        if sell_amount <= 0:
            return False

        pos["tx_pending"] = True
        save_mem()

        try:
            print(f"[{ticker}] Selling fixed chunk: {sell_amount} tokens")

            if dry_run:
                tx_hash = "0x" + "d" * 64
                receipt = {"status": 1}
            else:
                tx_hash = asyncio.run(executor.sell(token_address, sell_amount))
                append_event(memory, {"type": "onchain_sell_sent", "ticker": ticker, "tx_hash": tx_hash})
                receipt = asyncio.run(executor.wait_for_receipt(tx_hash))

            if not receipt or receipt.get("status") != 1:
                pos["tx_pending"] = False
                append_event(memory, {"type": "sell_failed", "ticker": ticker})
                save_mem()
                return False

            # Estimate payout
            total_val = pos.get("_current_valuation_mon", 0)
            payout_estimated = total_val * (sell_amount / token_amount)

            apply_flywheel(memory, payout_estimated, stake_mon=0.0, buyback_pct=0.5, burn_pct=0.0)

            # Update token balance
            pos["token_amount"] = token_amount - sell_amount

            # Linear sold %
            sold_fraction = sell_amount / original_amount
            pos["sold_pct_total"] = pos.get("sold_pct_total", 0.0) + (sold_fraction * 100.0)

            pos["tx_pending"] = False

            event_data = {
                "type": event_type,
                "ticker": ticker,
                "sell_pct_total": round(pos["sold_pct_total"], 2)
            }
            if extra_event_data:
                event_data.update(extra_event_data)

            append_event(memory, event_data)

            # Dust auto-close
            if pos["token_amount"] <= 1 or pos["sold_pct_total"] >= 99.9:
                pos["sold_pct_total"] = 100.0
                pos["status"] = "CLOSED"

            save_mem()
            return True

        except Exception as e:
            print(f"[{ticker}] Sell exception: {e}")
            pos["tx_pending"] = False
            save_mem()
            return False

    # --------------------------------------------------
    # MAIN LOOP
    # --------------------------------------------------
    for pos in list(active_positions):

        status = pos.get("status")
        if status not in ["EARLY", "ACTIVE", "EXITING", "MOON_BAG"]:
            continue

        ticker = pos.get("ticker", "TKN")
        token_address = pos.get("address")
        if not token_address:
            continue

        try:
            token_amount = pos.get("token_amount", 0)
            if token_amount <= 0:
                continue

            # Fetch valuation
            res = asyncio.run(executor.get_quote(token_address, float(token_amount), is_buy=False))
            current_value_mon = float(res.get("amount", 0.0)) / 10**18
            pos["_current_valuation_mon"] = current_value_mon

            entry_cost = pos.get("entry_cost_mon", 1.0)
            sold_pct = pos.get("sold_pct_total", 0.0)

            denominator = (1.0 - (sold_pct / 100.0))
            current_multiple = 0
            if denominator > 0 and entry_cost > 0:
                current_multiple = (current_value_mon / denominator) / entry_cost

            current_multiple = round(current_multiple, 4)
            roi = current_multiple - 1.0

            print(f"[{ticker}] Status: {status}, ROI: {roi*100:.1f}%")

            # ------------------------------------
            # LADDER
            # ------------------------------------
            if status in ["EARLY", "ACTIVE"]:
                ladder_targets = [1.0, 3.0, 6.0]
                for target in ladder_targets:
                    hit_key = f"{int(target*100)}"
                    if roi >= target and hit_key not in pos.get("ladder_hits", []):
                        if execute_position_sell(pos, "ladder_hit", {"target": hit_key}):
                            pos.setdefault("ladder_hits", []).append(hit_key)
                            break

            # ------------------------------------
            # DEAD TOKEN RULE
            # ------------------------------------
            days_passed = (current_ts - pos.get("timestamp", 0)) / (24 * 3600)
            if days_passed >= 4 and not pos.get("ladder_hits"):
                pos["status"] = "EXITING"

            # ------------------------------------
            # EXITING → keep selling until closed
            # ------------------------------------
            if pos.get("status") == "EXITING":
                execute_position_sell(pos, "exit_progress")

            # ------------------------------------
            # MOON BAG
            # ------------------------------------
            if status == "MOON_BAG":
                mb = pos.get("moonbag", {})
                if current_multiple > mb.get("ath_multiple", 0):
                    mb["ath_multiple"] = current_multiple

                ath = mb.get("ath_multiple", 0)
                threshold = ath * TRAILING_FACTOR

                if current_multiple < round(threshold, 4):
                    execute_position_sell(pos, "moonbag_trailing_sell")

            # ------------------------------------
            # FINAL CLOSE HANDLING
            # ------------------------------------
            if pos.get("status") == "CLOSED":
                memory.setdefault("portfolio", {}).setdefault("closed_positions", [])
                if pos not in memory["portfolio"]["closed_positions"]:
                    memory["portfolio"]["closed_positions"].append(pos)
                if pos in memory["portfolio"]["active_positions"]:
                    memory["portfolio"]["active_positions"].remove(pos)

                append_event(memory, {
                    "type": "position_closed",
                    "ticker": ticker,
                    "roi": round(roi, 4)
                })

                save_mem()

        except Exception as e:
            print(f"Error managing position {ticker}: {e}")
            if pos.get("tx_pending"):
                pos["tx_pending"] = False
                save_mem()



