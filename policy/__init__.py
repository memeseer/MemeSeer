from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

# Base modes as defined in economy + NO_LAUNCH
DEFAULT_MODES = [
    "conservative",
    "balanced",
    "growth",
    "signal",
    "aggressive",
    "no_launch"
]

UCB_INF_CAP = 1e9

def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))

def compute_edge(world: Dict[str, float]) -> float:
    """
    Computes market edge based on world signals.
    Inputs are clamped to [0.0, 1.0].
    
    Formula: 
      0.35*Trend + 0.25*Sentiment + 0.20*Novelty + 0.20*Liquidity - 0.80*Competition
      
    Max Positive: 1.0 (all pros 1.0, comp 0.0)
    Max Negative: -0.8 (all pros 0.0, comp 1.0)
    
    Bucket Thresholds:
      Bad: < -0.2
      Good: > 0.2
    """
    trend = _clamp01(world.get("trend", 0.5))
    sentiment = _clamp01(world.get("sentiment", 0.5))
    novelty = _clamp01(world.get("novelty", 0.5))
    liquidity = _clamp01(world.get("liquidity", 0.5))
    competition = _clamp01(world.get("competition", 0.5))
    
    raw = (
        0.35 * trend +
        0.25 * sentiment +
        0.20 * novelty +
        0.20 * liquidity -
        0.80 * competition
    )
    return max(-1.0, min(1.0, raw))


def get_bucket(edge: float) -> str:
    """
    Discretizes edge into buckets for Contextual Bandit.
    """
    if edge < -0.2:
        return "bad"
    elif edge > 0.2:
        return "good"
    return "neutral"


def ensure_learning_state(memory: Dict[str, Any]) -> None:
    learning = memory.setdefault("learning", {})
    bandit = learning.setdefault("bandit", {})
    
    # Structure: buckets -> { "bad": { "mode": {n, mean}, ... }, ... }
    buckets = bandit.setdefault("buckets", {})
    
    for b_name in ["bad", "neutral", "good"]:
        b_data = buckets.setdefault(b_name, {})
        for m in DEFAULT_MODES:
            b_data.setdefault(m, {"n": 0, "mean_reward": 0.0})

    learning.setdefault("last_balances", None)
    # Params for policy (if needed)
    learning.setdefault("params", {"exploration_c": 1.5})


def _ucb_score(mean: float, n: int, t: int, c: float = 1.5) -> float:
    if n <= 0:
        return UCB_INF_CAP
    return mean + c * math.sqrt(math.log(max(2, t)) / n)


def select_mode(memory: Dict[str, Any], edge: float) -> Dict[str, Any]:
    """
    Selects a strategy mode for the current context (bucket derived from edge).
    Includes 'no_launch' as a competitor.
    """
    ensure_learning_state(memory)
    bucket_name = get_bucket(edge)
    buckets = memory["learning"]["bandit"]["buckets"]
    
    # Get stats for the current bucket
    modes_stats = buckets[bucket_name]
    
    # Total pulls in this bucket
    t = sum(int(v.get("n", 0)) for v in modes_stats.values()) + 1
    c = float(memory["learning"].get("params", {}).get("exploration_c", 1.5))

    best_mode = None
    best_score = -1e18
    
    # Policy mapping for return values
    policy_defaults = {
        "conservative": {"buyback_pct": 0.80, "burn_pct": 0.00},
        "balanced":     {"buyback_pct": 0.50, "burn_pct": 0.00},
        "growth":       {"buyback_pct": 0.65, "burn_pct": 0.01},
        "signal":       {"buyback_pct": 0.40, "burn_pct": 0.02},
        "aggressive":   {"buyback_pct": 0.30, "burn_pct": 0.03},
        "no_launch":    {"buyback_pct": 0.00, "burn_pct": 0.00},
    }

    for name, st in modes_stats.items():
        n = int(st.get("n", 0))
        mean = float(st.get("mean_reward", 0.0))
        score = _ucb_score(mean, n, t, c)
        
        if score > best_score:
            best_score = score
            best_mode = name

    # Fallback
    if not best_mode:
        best_mode = "balanced"

    chosen = {
        "mode": best_mode,
        "bucket": bucket_name,
        "edge": edge,
        "ucb_score": float(best_score),
        "t": int(t),
        **policy_defaults.get(best_mode, {"buyback_pct": 0.5, "burn_pct": 0.0})
    }
    return chosen


def compute_reward(payout: float, stake: float, mode: str, bucket: str = "neutral", edge: float = 0.0) -> float:
    """
    Computes reward as ROI minus action cost.
    If mode is no_launch, reward is 0.0.
    
    Action Cost is Edge-Dependent:
      base = 0.01
      neg_edge = max(0, -edge)
      cost = base + 0.20 * neg_edge
      
    Example:
      Edge -1.0 -> Cost 0.21
      Edge -0.5 -> Cost 0.11
      Edge  0.0 -> Cost 0.01
      Edge +1.0 -> Cost 0.01
    """
    if mode == "no_launch":
        return 0.0
    
    if stake <= 0:
        return 0.0
        
    roi = (payout - stake) / stake
    
    # Edge-dependent action cost
    # We ignore the bucket parameter for cost calculation, 
    # but keep it in signature for compatibility/logging if needed.
    
    base_cost = 0.01
    neg_factor = max(0.0, -edge)
    cost = base_cost + 0.80 * neg_factor
    
    return roi - cost


def update_bandit(memory: Dict[str, Any], bucket: str, mode: str, reward: float) -> Dict[str, Any]:
    ensure_learning_state(memory)
    buckets = memory["learning"]["bandit"]["buckets"]
    
    # Safety check for migration/integrity
    if bucket not in buckets:
        buckets[bucket] = {}
    if mode not in buckets[bucket]:
        buckets[bucket][mode] = {"n": 0, "mean_reward": 0.0}
        
    st = buckets[bucket][mode]
    n = int(st.get("n", 0)) + 1
    mean = float(st.get("mean_reward", 0.0))
    
    # Incremental mean update
    mean = mean + (reward - mean) / n
    
    st["n"] = n
    st["mean_reward"] = round(mean, 8)
    
    return {
        "bucket": bucket,
        "mode": mode,
        "n": n,
        "mean_reward": st["mean_reward"],
        "reward": round(float(reward), 8)
    }


def get_prev_balances(memory: Dict[str, Any]) -> Dict[str, float] | None:
    ensure_learning_state(memory)
    lb = memory["learning"].get("last_balances")
    if isinstance(lb, dict) and "seer" in lb and "mon" in lb:
        return {"seer": float(lb["seer"]), "mon": float(lb["mon"])}
    return None


def set_prev_balances(memory: Dict[str, Any], balances: Dict[str, float]) -> None:
    ensure_learning_state(memory)
    memory["learning"]["last_balances"] = {"seer": float(balances.get("seer", 0.0)), "mon": float(balances.get("mon", 0.0))}
