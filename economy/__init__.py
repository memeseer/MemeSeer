from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List


@dataclass
class Balances:
    seer: float
    mon: float
    seer_burned: float = 0.0


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def get_mock_seer_price_mon(state: Dict[str, Any], *, default_price: float = 1.0) -> float:
    p = state.get("seer_price_mon", default_price)
    try:
        p = float(p)
    except Exception:
        p = default_price
    return max(1e-9, p)


def ensure_economy_state(memory: Dict[str, Any]) -> None:
    eco = memory.setdefault("economy", {})
    eco.setdefault("balances", {"seer": 0.0, "mon": 0.0, "seer_burned": 0.0})
    eco.setdefault("treasury_mon", 0.0)
    eco.setdefault("stats", {
        "seer_sold_total": 0.0,
        "buyback_mon_total": 0.0,
        "seer_bought_total": 0.0,
        "seer_burned_total": 0.0
    })
    eco.setdefault(
        "params",
        {
            "min_seer_to_live": 1.0,
            "mon_per_launch": 5.0,
            "max_seer_sell_frac": 0.25,
            "treasury_pct_of_profit": 0.30,
            "min_operating_mon": 5.0,
            "sell_frac_scale_bad": 0.25,
            "sell_frac_scale_neutral": 0.60,
            "sell_frac_scale_good": 1.00,
        },
    )
    eco.setdefault("seer_price_mon", 1.0)


def read_balances(memory: Dict[str, Any]) -> Balances:
    b = (memory.get("economy", {}) or {}).get("balances", {}) or {}
    return Balances(
        seer=float(b.get("seer", 0.0) or 0.0),
        mon=float(b.get("mon", 0.0) or 0.0),
        seer_burned=float(b.get("seer_burned", 0.0) or 0.0),
    )


def write_balances(memory: Dict[str, Any], bal: Balances) -> None:
    memory["economy"]["balances"] = {
        "seer": round(bal.seer, 8),
        "mon": round(bal.mon, 8),
        "seer_burned": round(bal.seer_burned, 8),
    }


def can_launch(memory: Dict[str, Any]) -> Tuple[bool, str]:
    ensure_economy_state(memory)
    params = memory["economy"]["params"]
    bal = read_balances(memory)
    min_live = float(params.get("min_seer_to_live", 1.0))
    if bal.seer < min_live:
        return False, f"SEER below min_seer_to_live ({bal.seer:.4f} < {min_live:.4f})"
    return True, "ok"


def fund_launch_by_selling_seer(memory: Dict[str, Any], bucket: str = "neutral", edge: float = 0.0) -> Dict[str, Any]:
    ensure_economy_state(memory)
    eco = memory["economy"]
    params = eco["params"]
    bal = read_balances(memory)

    price = get_mock_seer_price_mon(eco)
    mon_needed = float(params.get("mon_per_launch", 5.0))
    base_max_sell_frac = float(params.get("max_seer_sell_frac", 0.25))
    
    # Dynamic scaling based on bucket
    scale_bad = float(params.get("sell_frac_scale_bad", 0.25))
    scale_neutral = float(params.get("sell_frac_scale_neutral", 0.60))
    scale_good = float(params.get("sell_frac_scale_good", 1.00))
    
    if bucket == "bad":
        scale = scale_bad
    elif bucket == "good":
        scale = scale_good
    else:
        scale = scale_neutral
    
    max_sell_frac = base_max_sell_frac * scale

    if bal.mon >= mon_needed:
        return {"sold_seer": 0.0, "got_mon": 0.0, "price": price, "mon_needed": mon_needed, "note": "already_funded", "bucket": bucket, "scale": scale}

    mon_gap = mon_needed - bal.mon
    seer_required = mon_gap / price

    seer_cap = bal.seer * _clamp(max_sell_frac, 0.0, 1.0)
    sold_seer = min(seer_required, seer_cap)

    got_mon = sold_seer * price
    bal.seer -= sold_seer
    bal.mon += got_mon
    
    # Update stats
    eco["stats"]["seer_sold_total"] = float(eco["stats"].get("seer_sold_total", 0.0)) + sold_seer

    write_balances(memory, bal)

    return {
        "sold_seer": round(sold_seer, 8),
        "got_mon": round(got_mon, 8),
        "price": price,
        "mon_needed": mon_needed,
        "note": "sold_seer_for_funding",
        "bucket": bucket,
        "scale": scale,
    }


def spend_mon_for_launch(memory: Dict[str, Any]) -> Dict[str, Any]:
    ensure_economy_state(memory)
    params = memory["economy"]["params"]
    bal = read_balances(memory)

    mon_needed = float(params.get("mon_per_launch", 5.0))
    if bal.mon < mon_needed:
        return {"ok": False, "spent_mon": 0.0, "mon_needed": mon_needed, "mon_before": round(bal.mon, 8), "note": "insufficient_mon"}

    before = bal.mon
    bal.mon -= mon_needed
    write_balances(memory, bal)
    return {"ok": True, "spent_mon": round(mon_needed, 8), "mon_needed": mon_needed, "mon_before": round(before, 8), "mon_after": round(bal.mon, 8), "note": "spent_for_launch"}


# -------------------------------------------------------------------------
# Simulation Logic: Mode-Based + Edge-Based + Calibrated
# -------------------------------------------------------------------------

OUTCOME_PROBABILITIES = {
    "conservative": {
        "RUG": 0.02,        # Lower rug chance
        "FLOP": 0.18,
        "BREAKEVEN": 0.60,
        "PUMP": 0.20,
        "MOON": 0.00,
    },
    "balanced": {
        "RUG": 0.20,
        "FLOP": 0.20,
        "BREAKEVEN": 0.30,
        "PUMP": 0.25,
        "MOON": 0.05,
    },
    "growth": {
        "RUG": 0.15,
        "FLOP": 0.15,
        "BREAKEVEN": 0.30,
        "PUMP": 0.30,
        "MOON": 0.10,
    },
    "signal": {
        "RUG": 0.25,
        "FLOP": 0.20,
        "BREAKEVEN": 0.20,
        "PUMP": 0.25,
        "MOON": 0.10,
    },
    "aggressive": {
        "RUG": 0.40,
        "FLOP": 0.10,
        "BREAKEVEN": 0.10,
        "PUMP": 0.30,
        "MOON": 0.10,
    },
    "default": {
        "RUG": 0.20,
        "FLOP": 0.20,
        "BREAKEVEN": 0.30,
        "PUMP": 0.25,
        "MOON": 0.05,
    },
}

MODE_SENSITIVITY = {
    "conservative": 0.2,
    "balanced": 0.8,
    "growth": 0.9,
    "signal": 1.0,
    "aggressive": 1.0,
    "default": 0.5,
}


def sample_multiplier(outcome: str, mode: str, edge: float) -> float:
    """
    Sample a multiplier based on outcome, shaped by mode and edge.
    Calibrated for Balanced EV ~ 1.0 (0% ROI) at edge 0.0.
    """
    # Simple logic: positive edge slightly boosts PUMP/MOON magnitude, negative hurts it
    # Mode determines the volatility/range.
    
    if outcome == "RUG":
        return 0.0

    elif outcome == "BREAKEVEN":
        # Almost always 1.0 +/- small noise
        # Aggressive might be slightly wider spreads
        return random.uniform(0.9, 1.1)

    elif outcome == "FLOP":
        # Conservative: softer flops (0.5 - 0.9)
        # Aggressive: harder flops (0.01 - 0.4)
        if mode == "conservative":
            return random.uniform(0.5, 0.9)
        elif mode == "aggressive":
            return random.uniform(0.01, 0.5)
        else:
            # Balanced
            return random.uniform(0.3, 0.7)

    elif outcome == "PUMP":
        # Fat tails?
        # Balanced Target Avg ~1.5
        # Lognormal guide: Mean = exp(mu + sigma^2/2)
        # Try Triangular for simpler bounded control or Lognorm for tails. 
        # User asked for tails.
        
        if mode == "conservative":
            # Modest returns: 1.1 to 1.8
            return random.uniform(1.1, 1.8)
        
        elif mode == "aggressive":
            # Volatile pumps: 1.2 to 5.0+
            # Lognorm. Median 2.0.
            val = random.lognormvariate(0.7, 0.4) 
            return _clamp(val, 1.1, 8.0)
            
        else:
            # Balanced: Target avg 1.5
            # Median ~1.4
            val = random.lognormvariate(0.35, 0.3) 
            return _clamp(val, 1.1, 4.0)

    elif outcome == "MOON":
        # Balanced Target Avg ~5.0 - 6.0
        
        if mode == "conservative":
             # Should not happen prob=0, but safe fallback
             return 2.0
        
        if mode == "aggressive":
            # Huge moons possible
            # Median 6.0
            val = random.lognormvariate(1.8, 0.6)
            return _clamp(val, 3.0, 50.0) # Cap at 50x
            
        else:
            # Balanced
            # Median 4.5
            val = random.lognormvariate(1.5, 0.5)
            return _clamp(val, 3.0, 15.0)

    return 0.0


def _apply_edge(probs: Dict[str, float], edge: float, sensitivity: float) -> Dict[str, float]:
    edge = _clamp(edge, -1.0, 1.0)
    sensitivity = _clamp(sensitivity, 0.0, 2.0)
    p = probs.copy()
    
    # Approx 30-40% mass shift max
    transfer_amount = abs(edge) * sensitivity * 0.4
    
    bad_outcomes = ["RUG", "FLOP"]
    good_outcomes = ["PUMP", "MOON"]
    
    bad_mass = sum(p[k] for k in bad_outcomes)
    good_mass = sum(p[k] for k in good_outcomes)
    
    if edge > 0:
        actual_transfer = min(transfer_amount, bad_mass)
        if bad_mass > 0:
            for k in bad_outcomes:
                p[k] -= actual_transfer * (p[k] / bad_mass)
        if good_mass > 0:
            for k in good_outcomes:
                p[k] += actual_transfer * (p[k] / good_mass)
        else:
            for k in good_outcomes:
                p[k] += actual_transfer / len(good_outcomes)
                
    elif edge < 0:
        actual_transfer = min(transfer_amount, good_mass)
        if good_mass > 0:
            for k in good_outcomes:
                p[k] -= actual_transfer * (p[k] / good_mass)
        if bad_mass > 0:
            for k in bad_outcomes:
                p[k] += actual_transfer * (p[k] / bad_mass)
        else:
            for k in bad_outcomes:
                p[k] += actual_transfer / len(bad_outcomes)

    total = sum(p.values())
    if total <= 0:
        return probs.copy()
        
    for k in p:
        p[k] /= total
        
    return p


def simulate_meme_outcome(memory: Dict[str, Any], mode: str = "balanced", edge: float = 0.0, *, rng_seed: Optional[int] = None) -> Dict[str, Any]:
    ensure_economy_state(memory)
    params = memory["economy"]["params"]
    if rng_seed is not None:
        random.seed(rng_seed)

    stake = float(params.get("mon_per_launch", 5.0))
    
    base_probs = OUTCOME_PROBABILITIES.get(mode, OUTCOME_PROBABILITIES["default"])
    sensitivity = MODE_SENSITIVITY.get(mode, MODE_SENSITIVITY["default"])
    final_probs = _apply_edge(base_probs, edge, sensitivity)
    
    outcomes_list = list(final_probs.keys())
    weights_list = list(final_probs.values())
    outcome_type = random.choices(outcomes_list, weights=weights_list, k=1)[0]
    
    multiplier = sample_multiplier(outcome_type, mode, edge)
    payout = stake * multiplier
    
    if payout < 0:
        payout = 0.0

    return {
        "payout_mon": round(payout, 8),
        "outcome": outcome_type,
        "mode": mode, 
        "edge": edge,
        "probs": {k: round(v, 4) for k, v in final_probs.items()},
        "multiplier": round(multiplier, 4),
        "note": "simulated_calibrated"
    }


def apply_flywheel(memory: Dict[str, Any], payout_mon: float, stake_mon: float, buyback_pct: float, burn_pct: float) -> Dict[str, Any]:
    """
    Apply CORE flywheel: treasury from profit, buyback/burn from remaining profit.
    Only operates on profit (payout - stake), protects operating reserve.
    """
    ensure_economy_state(memory)
    eco = memory["economy"]
    params = eco["params"]
    bal = read_balances(memory)
    price = get_mock_seer_price_mon(eco)

    payout_mon = max(0.0, float(payout_mon))
    stake_mon = max(0.0, float(stake_mon))
    
    # Add payout to balance
    mon_before = bal.mon
    bal.mon += payout_mon
    
    # Calculate profit
    profit = max(0.0, payout_mon - stake_mon)
    
    # Treasury take from profit
    treasury_pct = _clamp(float(params.get("treasury_pct_of_profit", 0.30)), 0.0, 1.0)
    treasury_take = profit * treasury_pct
    
    # Remaining profit for buyback
    profit_after_treasury = profit - treasury_take
    
    buyback_pct = _clamp(float(buyback_pct), 0.0, 1.0)
    burn_pct = _clamp(float(burn_pct), 0.0, 0.05)
    
    # Buyback budget from remaining profit
    buyback_budget_raw = profit_after_treasury * buyback_pct
    
    # Protect operating reserve
    min_operating = float(params.get("min_operating_mon", 5.0))
    operating_mon = bal.mon
    max_buyback = max(0.0, operating_mon - min_operating)
    buyback_budget = min(buyback_budget_raw, max_buyback)
    
    # Execute buyback
    bought_seer = 0.0
    
    if buyback_budget > 0 and price > 0:
        bought_seer = buyback_budget / price
        bal.mon -= buyback_budget
        bal.seer += bought_seer
    
    # Update treasury
    eco["treasury_mon"] = float(eco.get("treasury_mon", 0.0)) + treasury_take
    
    # Update cumulative stats
    stats = eco["stats"]
    stats["buyback_mon_total"] = float(stats.get("buyback_mon_total", 0.0)) + buyback_budget
    stats["seer_bought_total"] = float(stats.get("seer_bought_total", 0.0)) + bought_seer
    
    write_balances(memory, bal)

    return {
        "payout_mon": round(payout_mon, 8),
        "stake_mon": round(stake_mon, 8),
        "profit": round(profit, 8),
        "treasury_take": round(treasury_take, 8),
        "profit_after_treasury": round(profit_after_treasury, 8),
        "buyback_budget_raw": round(buyback_budget_raw, 8),
        "buyback_budget": round(buyback_budget, 8),
        "bought_seer": round(bought_seer, 8),
        "mon_before": round(mon_before, 8),
        "mon_after": round(bal.mon, 8),
        "seer_price_mon": price,
        "buyback_pct": buyback_pct,
        "treasury_mon": round(eco["treasury_mon"], 8),
        "balances": memory["economy"]["balances"],
    }


# Legacy wrapper for compatibility
def apply_payout_and_policy(memory: Dict[str, Any], payout_mon: float, *, buyback_pct: float, burn_pct: float = 0.0, policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Legacy wrapper - uses stake=0 to maintain old behavior of buyback from entire balance."""
    if policy:
        buyback_pct = policy.get("buyback_pct", buyback_pct)
    return apply_flywheel(memory, payout_mon, stake_mon=0.0, buyback_pct=buyback_pct, burn_pct=0.0)
