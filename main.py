from __future__ import annotations

import os
import json
import time
import copy
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from economy import (
    ensure_economy_state,
    can_launch,
    fund_launch_by_selling_seer,
    spend_mon_for_launch,
    simulate_meme_outcome,        # returns {"payout_mon": float, "outcome": "...", "note": "..."}
    apply_payout_and_policy,      
    read_balances,
    write_balances,
)
from policy import (
    compute_edge,
    select_mode,
    get_prev_balances,
    set_prev_balances,
    compute_reward,
    update_bandit,
)
from social_ritual import prepare_ritual_post
import asyncio
from web3 import Web3
from onchain.nadfun_executor import NadfunExecutor
from scripts.generate_token_image import generate_token_image as generate_image
from portfolio import manage_portfolio, get_blocking_positions

AGENT_NAME = "MemeSeer"

MAX_ACTIVE_POSITIONS = 3

MEMORY_PATH = os.getenv("MEMESEER_MEMORY_PATH", "memory.json")
OUTBOX_DIR = os.getenv("MEMESEER_OUTBOX_DIR", "outbox")
RITUAL_COOLDOWN_SECONDS = int(os.getenv("MEMESEER_RITUAL_COOLDOWN_SECONDS", str(6 * 60 * 60)))

DEFAULT_SEER_INITIAL = float(os.getenv("SEER_INITIAL", "1000"))
DEFAULT_SEER_PRICE_MON = float(os.getenv("SEER_PRICE_MON", "1.0"))
DEFAULT_MON_PER_LAUNCH = float(os.getenv("MON_PER_LAUNCH", "5.0"))
DEFAULT_MAX_SEER_SELL_FRAC = float(os.getenv("MAX_SEER_SELL_FRAC", "0.25"))

SEER_TOKEN_ADDRESS = os.getenv("SEER_TOKEN_ADDRESS")
if not SEER_TOKEN_ADDRESS:
    raise Exception("SEER_TOKEN_ADDRESS not configured")

# ----------------
# OpenRouter HTTP Client
# ----------------
def get_openrouter_key() -> str:
    """Get OpenRouter API key from environment."""
    return os.getenv("OPENROUTER_API_KEY", "")


def get_openrouter_model() -> str:
    """Get OpenRouter model from environment, default to gpt-4o-mini."""
    return os.getenv("OPENROUTER_MODEL", "gpt-4o-mini")


def openrouter_chat(messages: list[dict], model: str, api_key: str, timeout_sec: int = 60) -> str:
    """
    Make HTTP POST to OpenRouter chat completions endpoint.
    Returns assistant message content.
    Raises RuntimeError on non-200 status.
    """
    import urllib.request
    import urllib.error
    
    url = "https://openrouter.ai/api/v1/chat/completions"
    
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.7
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "MemeSeer"
    }
    
    data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers)
    
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as response:
            resp_data = json.loads(response.read().decode('utf-8'))
            return resp_data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body_snippet = ""
        try:
            body_snippet = e.read().decode('utf-8')[:200]
        except:
            pass
        raise RuntimeError(f"OpenRouter HTTP {e.code}: {body_snippet}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"OpenRouter URL error: {e.reason}")
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise RuntimeError(f"OpenRouter response parse error: {e}")


# ----------------
# JSON helpers
# ----------------
def extract_first_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text or not isinstance(text, str):
        return None
    text = text.strip()

    # Fast path
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass

    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_str = False
    esc = False

    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    chunk = text[start : i + 1]
                    try:
                        obj = json.loads(chunk)
                        return obj if isinstance(obj, dict) else None
                    except Exception:
                        return None
    return None


# ----------------
# Time helpers
# ----------------
def utc_now_ts() -> int:
    return int(time.time())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ----------------
# Memory IO
# ----------------
def load_memory(path: str = MEMORY_PATH) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def save_memory(memory: Dict[str, Any], path: str = MEMORY_PATH) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2, ensure_ascii=False, allow_nan=False)
    os.replace(tmp, path)


def ensure_memory(memory: Dict[str, Any]) -> None:
    memory.setdefault("agent", AGENT_NAME)
    memory.setdefault("created_at", utc_now_iso())
    memory.setdefault("stats", {})
    memory.setdefault("events", [])
    memory.setdefault("launches", {})
    memory.setdefault("social", {})
    memory["social"].setdefault("outbox_dir", OUTBOX_DIR)
    memory["social"].setdefault("last_ritual_post_ts", None)
    memory.setdefault("portfolio", {"active_positions": []})
    memory.setdefault("launch_control", {
        "last_launch_timestamp": 0,
        "launch_in_progress": False
    })
    memory.setdefault("core_guard", {
        "daily_core_sold": 0.0,
        "daily_reset_ts": 0,
        "max_daily_sell_pct_treasury": 0.05,
        "max_single_launch_pct_treasury": 0.05,
        "loss_streak": 0,
        "launch_blocked_until": 0
    })
    memory.setdefault("system", {
        "kill_switch": False
    })


def append_event(memory: Dict[str, Any], event: Dict[str, Any]) -> None:
    event = dict(event)
    event.setdefault("ts", utc_now_ts())
    memory["events"].append(event)
    max_events = int(os.getenv("MEMESEER_MAX_EVENTS", "500"))
    if len(memory["events"]) > max_events:
        memory["events"] = memory["events"][-max_events:]


def is_rate_limited(memory: Dict[str, Any]) -> bool:
    last = memory.get("social", {}).get("last_ritual_post_ts")
    if not isinstance(last, int):
        return False
    return (utc_now_ts() - last) < RITUAL_COOLDOWN_SECONDS


def duplicate_ticker(memory: Dict[str, Any], token_idea: Dict[str, Any]) -> bool:
    ticker = str(token_idea.get("ticker", "")).strip().upper()
    if not ticker:
        return True
    launches = memory.get("launches") or {}
    for _, item in launches.items():
        tj = (item or {}).get("token_idea") or {}
        if str(tj.get("ticker", "")).strip().upper() == ticker:
            return True
    return False


# Portfolio helpers
def get_active_position_count(memory: Dict[str, Any]) -> int:
    """
    Returns number of ACTIVE positions in memory.
    """
    portfolio = memory.get("portfolio", {})
    active = portfolio.get("active_positions", [])
    return sum(1 for p in active if p.get("status") == "active")

# Portfolio logic moved to portfolio/portfolio.py


# ----------------
# Agent cognition
# ----------------
# ----------------
# Agent cognition
# ----------------

# ----------------
# Data loading
# ----------------
def load_external_feed(path: str = "external_feed.json") -> Dict[str, Any]:
    """
    Loads external feed from JSON. 
    Supports list of strings or dict with "posts".
    Returns {"posts": [str], "meta": dict}
    """
    if not os.path.exists(path):
        return {"posts": [], "meta": {"source": "none", "status": "missing"}}
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        posts = []
        meta = {"source": "unknown", "status": "ok", "updated_at": utc_now_iso()}
        
        if isinstance(data, list):
            # Format A: Simple list of strings
            posts = [str(x)[:500] for x in data if x]
            meta["source"] = "list"
        elif isinstance(data, dict):
            # Format B: Object with posts
            raw_posts = data.get("posts", [])
            if isinstance(raw_posts, list):
                for p in raw_posts:
                    if isinstance(p, dict):
                        text = str(p.get("text", "") or "")
                        if text:
                            posts.append(text[:500])
                    elif isinstance(p, str):
                        posts.append(p[:500])
            meta["source"] = str(data.get("source", "dict"))
            if "updated_at" in data:
                meta["updated_at"] = str(data["updated_at"])
                
        # Limit to 30 posts
        return {"posts": posts[:30], "meta": meta}
        
    except Exception as e:
        return {"posts": [], "meta": {"source": "error", "status": str(e)}}


# ----------------
# Agent cognition
# ----------------
def observe(memory: Dict[str, Any]) -> str:
    """
    Observation with external feed integration.
    Extracts signals, computes edge/bucket/mood, updates memory["world"].
    Returns world_text.
    """
    # 1. Context
    events = memory.get("events", [])[-5:]
    balances = memory.get("economy", {}).get("balances", {})
    
    # Load External Feed
    feed_data = load_external_feed()
    posts = feed_data.get("posts", [])
    feed_meta = feed_data.get("meta", {})
    
    # 2. Defaults / Fallback
    default_signals = {"trend": 0.5, "sentiment": 0.5, "novelty": 0.5, "liquidity": 0.5, "competition": 0.5}
    
    # 3. LLM Call or Heuristic Extraction
    if os.getenv("MEMESEER_DISABLE_LLM") != "1":
        # Construct facts prompt
        posts_text = "\n".join([f"- {p}" for p in posts]) if posts else "(No external posts)"
        
        prompt = f"""
You are MemeSeer. Observe the current crypto/meme market state based ONLY on the facts below.

EXTERNAL POSTS (most recent first):
{posts_text}

INTERNAL CONTEXT:
Last 5 events: {json.dumps(events, default=str)}
Balances: {json.dumps(balances)}

Instructions:
- If external_posts is empty, default signals to 0.5.
- If external_posts show hype/pumps -> trend/sentiment > 0.6.
- If external_posts show fear/cautious -> sentiment/liquidity < 0.4.
- Competition: If many launches mentioned -> competition > 0.7.

Extract market signals as JSON.
Schema:
{{
  "trend": 0.0-1.0,
  "sentiment": 0.0-1.0, 
  "novelty": 0.0-1.0, 
  "liquidity": 0.0-1.0,
  "competition": 0.0-1.0,
  "why": ["reason1", "reason2"],
  "world_text": "One short paragraph summary (max 400 chars)"
}}
"""
        try:
            api_key = get_openrouter_key()
            if not api_key:
                raise RuntimeError("OPENROUTER_API_KEY not set")
            
            model = get_openrouter_model()
            messages = [{"role": "user", "content": prompt}]
            
            raw = openrouter_chat(messages, model, api_key, timeout_sec=30)
            data = extract_first_json_object(raw)
        except Exception as e:
            print(f"Observe LLM failed: {e}")
            data = None
    else:
        # LLM disabled - use heuristic extraction
        data = None
        if posts:
            # Build world_text from first 10 posts
            world_lines = []
            for p in posts[:10]:
                if isinstance(p, dict):
                    author = p.get("author", {})
                    username = author.get("username", "unknown") if isinstance(author, dict) else "unknown"
                    text = str(p.get("text", ""))[:200]
                    world_lines.append(f"- @{username}: {text}")
                elif isinstance(p, str):
                    world_lines.append(f"- {p[:200]}")
            
            world_text_heuristic = "\n".join(world_lines)
            
            # Compute signals heuristically
            all_text = " ".join([str(p.get("text", "") if isinstance(p, dict) else p).lower() for p in posts])
            
            trend_keywords = ["just in", "breaking", "new", "launch", "pump", "surge", "rally", "etf", "fed", "sec", "listing"]
            sentiment_pos = ["surge", "bull", "up", "win", "record", "approve", "moon"]
            sentiment_neg = ["down", "crash", "hack", "lawsuit", "ban", "rug", "scam", "bear"]
            novelty_keywords = ["new", "launch", "first", "now", "today", "breaking"]
            liquidity_keywords = ["volume", "liquidity", "dex", "cex", "listing", "order book"]
            competition_keywords = ["vs", "competition", "rival", "beats", "dominates", "market share"]
            
            trend_count = sum(1 for kw in trend_keywords if kw in all_text)
            pos_count = sum(1 for kw in sentiment_pos if kw in all_text)
            neg_count = sum(1 for kw in sentiment_neg if kw in all_text)
            novelty_count = sum(1 for kw in novelty_keywords if kw in all_text)
            ticker_count = all_text.count("$")
            liquidity_count = sum(1 for kw in liquidity_keywords if kw in all_text)
            competition_count = sum(1 for kw in competition_keywords if kw in all_text)
            
            num_posts = len(posts)
            
            trend_signal = min(1.0, trend_count / max(1, num_posts * 0.3))
            sentiment_signal = 0.5 + (pos_count - neg_count) / max(1, num_posts * 2.0)
            sentiment_signal = max(0.0, min(1.0, sentiment_signal))
            novelty_signal = min(1.0, (novelty_count + ticker_count * 0.5) / max(1, num_posts * 0.4))
            liquidity_signal = min(1.0, 0.3 + liquidity_count / max(1, num_posts * 0.5))
            competition_signal = min(1.0, 0.3 + competition_count / max(1, num_posts * 0.5))
            
            signals_heuristic = {
                "trend": trend_signal,
                "sentiment": sentiment_signal,
                "novelty": novelty_signal,
                "liquidity": liquidity_signal,
                "competition": competition_signal
            }
            
            data = {
                "trend": signals_heuristic["trend"],
                "sentiment": signals_heuristic["sentiment"],
                "novelty": signals_heuristic["novelty"],
                "liquidity": signals_heuristic["liquidity"],
                "competition": signals_heuristic["competition"],
                "why": ["heuristic extraction from external feed"],
                "world_text": world_text_heuristic[:400]
            }

    # 4. Process Data
    if not data:
        # Fallback: Merge default + existing
        existing = (memory.get("world", {}) or {}).get("signals", {}) or {}
        signals = dict(default_signals)
        
        # Overlay existing numerical values
        for k, v in existing.items():
            if k in signals:
                try:
                    signals[k] = float(v)
                except (ValueError, TypeError):
                    pass
        
        # Clamp all
        for k in signals:
            signals[k] = max(0.0, min(1.0, float(signals[k])))

        why = ["fallback: no external feed"]
        world_text = "Market is uncertain. No external data available."
    else:
        signals = {
            k: max(0.0, min(1.0, float(data.get(k, 0.5)))) 
            for k in ["trend", "sentiment", "novelty", "liquidity", "competition"]
        }
        why = [str(w) for w in data.get("why", [])][:5]
        world_text = str(data.get("world_text", "")).strip()[:400]

    # 5. Compute Edge & Mood
    edge = compute_edge(signals)
    
    # Determine bucket locally (logic matches policy.py)
    if edge < -0.2:
        bucket_val = "bad"
        mood = "🔴 Bearish"
    elif edge > 0.2:
        bucket_val = "good"
        mood = "🟢 Bullish"
    else:
        bucket_val = "neutral"
        mood = "🟡 Neutral"

    # 6. Update Memory
    feed_source = feed_meta.get("source", "none")
    posts_used = len(posts)
    feed_meta["count"] = posts_used
    feed_meta["source"] = feed_source
    
    memory["world"] = {
        "signals": signals,
        "edge": edge,
        "bucket": bucket_val,
        "mood": mood,
        "why": why,
        "world_text": world_text,
        "ts": utc_now_iso(),
        "feed": feed_meta,
        "feed_source": feed_source,
        "posts_used": posts_used
    }
    
    return world_text


def think(world: str) -> str:
    if os.getenv("MEMESEER_DISABLE_LLM") == "1":
        raise RuntimeError("LLM call blocked by MEMESEER_DISABLE_LLM")

    api_key = get_openrouter_key()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    prompt = f"""
You are MemeSeer, an autonomous AI agent living in Moltiverse.

World signal:
{world}

Think briefly about current meme narratives in 5-8 sentences.
"""
    
    model = get_openrouter_model()
    messages = [{"role": "user", "content": prompt}]
    
    return openrouter_chat(messages, model, api_key, timeout_sec=60).strip()


def decide(thought: str) -> Dict[str, Any]:
    if os.getenv("MEMESEER_DISABLE_LLM") == "1":
        raise RuntimeError("LLM call blocked by MEMESEER_DISABLE_LLM")

    api_key = get_openrouter_key()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    prompt = f"""
You are MemeSeer, an autonomous AI agent.

Based on the thought below, decide whether to launch a memecoin today.

Thought:
{thought}

Return ONLY valid JSON (no markdown, no extra text).
JSON schema:
{{
  "launch": true,
  "reason": "short explanation"
}}
or
{{
  "launch": false,
  "reason": "short explanation"
}}
"""
    
    model = get_openrouter_model()
    messages = [{"role": "user", "content": prompt}]
    
    raw = openrouter_chat(messages, model, api_key, timeout_sec=60).strip()
    obj = extract_first_json_object(raw)
    if obj is None:
        return {"launch": False, "reason": "JSON parse failed", "_raw": raw}

    return {
        "launch": bool(obj.get("launch", False)),
        "reason": str(obj.get("reason", "")).strip() or "No reason.",
        "_raw": raw,
    }


def generate_token_idea(thought: str) -> Dict[str, Any]:
    if os.getenv("MEMESEER_DISABLE_LLM") == "1":
        raise RuntimeError("LLM call blocked by MEMESEER_DISABLE_LLM")

    api_key = get_openrouter_key()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    prompt = f"""
You are MemeSeer, an autonomous AI agent.

You have decided to launch a memecoin.

Based on the thought below, generate a memecoin concept.
Keep it simple, legible, and meme-native.

Thought:
{thought}

Return ONLY valid JSON (no markdown, no extra text).
Rules:
- ticker: 3-6 uppercase letters
- name: max 20 chars

JSON schema:
{{
  "name": "Token name",
  "ticker": "TICKER",
  "narrative": "Short meme-native description",
  "why_now": "Why this works right now"
}}
"""
    
    model = get_openrouter_model()
    messages = [{"role": "user", "content": prompt}]
    
    raw = openrouter_chat(messages, model, api_key, timeout_sec=60).strip()
    obj = extract_first_json_object(raw)
    if obj is None:
        return {
            "name": "NO_LAUNCH",
            "ticker": "NOPE",
            "narrative": "JSON parse failed",
            "why_now": "Invalid output",
            "_raw": raw,
        }

    return {
        "name": str(obj.get("name", "")).strip()[:20] or "UNKNOWN",
        "ticker": str(obj.get("ticker", "")).strip().upper()[:6] or "NOPE",
        "narrative": str(obj.get("narrative", "")).strip() or "No narrative.",
        "why_now": str(obj.get("why_now", "")).strip() or "No why_now.",
        "_raw": raw,
    }


# ----------------
# Economy bootstrap
# ----------------
def bootstrap_economy_if_needed(memory: Dict[str, Any]) -> None:
    ensure_economy_state(memory)
    eco = memory["economy"]

    b = eco.get("balances", {}) or {}
    if float(b.get("seer", 0.0) or 0.0) == 0.0 and float(b.get("mon", 0.0) or 0.0) == 0.0:
        eco["balances"]["seer"] = DEFAULT_SEER_INITIAL
        eco["balances"]["mon"] = 0.0
        eco["balances"]["seer_burned"] = 0.0

    eco["seer_price_mon"] = DEFAULT_SEER_PRICE_MON
    eco["params"]["mon_per_launch"] = DEFAULT_MON_PER_LAUNCH
    eco["params"]["max_seer_sell_frac"] = DEFAULT_MAX_SEER_SELL_FRAC


# ----------------
# LLM Guard
# ----------------
def should_call_llm(action: str) -> bool:
    """
    Return True iff LLM should be invoked.
    Conditions:
      - MEMESEER_DISABLE_LLM env var set to "1" -> False
      - action == "no_launch" -> False
      - otherwise True
    """
    if os.getenv("MEMESEER_DISABLE_LLM") == "1":
        return False
    if action == "no_launch":
        return False
    return True


# ----------------
# ERC20 decimals helper
# ----------------
ERC20_DECIMALS_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    }
]


async def get_token_decimals(executor, token_address: str) -> int:
    """Fetch ERC20 token decimals from chain via the executor's web3 instance."""
    contract = executor.trade.w3.eth.contract(
        address=Web3.to_checksum_address(token_address),
        abi=ERC20_DECIMALS_ABI,
    )
    return contract.functions.decimals().call()


# ----------------
# AMM pair-based quote
# ----------------
PAIR_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "getReserves",
        "outputs": [
            {"name": "reserve0", "type": "uint112"},
            {"name": "reserve1", "type": "uint112"},
            {"name": "blockTimestampLast", "type": "uint32"},
        ],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "token0",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "token1",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function",
    },
]

SEER_PAIR_ADDRESS = "0xA7283d07812a02AFB7C09B60f8896bCEA3F90aCE"


def get_amount_out_from_pair(w3, pair_address, token_in, amount_in_raw):
    """Compute expected output using Uniswap V2 AMM formula from pair reserves."""
    pair = w3.eth.contract(
        address=Web3.to_checksum_address(pair_address),
        abi=PAIR_ABI,
    )

    reserve0, reserve1, _ = pair.functions.getReserves().call()
    token0 = pair.functions.token0().call()
    token1 = pair.functions.token1().call()

    token_in = Web3.to_checksum_address(token_in)
    token0 = Web3.to_checksum_address(token0)
    token1 = Web3.to_checksum_address(token1)

    if token_in == token0:
        reserve_in = reserve0
        reserve_out = reserve1
    elif token_in == token1:
        reserve_in = reserve1
        reserve_out = reserve0
    else:
        raise Exception("Token not found in pair")

    if reserve_in == 0 or reserve_out == 0:
        raise Exception("Pair has zero liquidity")

    # Uniswap V2 0.3% fee model
    amount_in_with_fee = amount_in_raw * 997
    numerator = amount_in_with_fee * reserve_out
    denominator = reserve_in * 1000 + amount_in_with_fee

    return numerator // denominator


# ----------------
# Main
# ----------------
def main() -> None:
    print(f"[{AGENT_NAME}] booted.")

    memory = load_memory(MEMORY_PATH)
    ensure_memory(memory)

    # 🛑 KILL SWITCH CHECK
    if memory.get("system", {}).get("kill_switch", False):
        append_event(memory, {
            "type": "kill_switch_active",
            "timestamp": utc_now_ts()
        })
        print("[KILL SWITCH] Execution halted.")
        save_memory(memory)
        return

    bootstrap_economy_if_needed(memory)

    # Manage existing portfolio first
    manage_portfolio(memory)

    # Initialize variables for safe failure paths
    outbox_path = None
    token_idea = None
    thought = None
    spend = None
    launch_successful = False
    decision = {"launch": False}
    chosen_policy = None

    prev = get_prev_balances(memory)
    if prev is None:
        b0 = read_balances(memory)
        prev = {"seer": b0.seer, "mon": b0.mon}
        set_prev_balances(memory, prev)

    # --- Observe / Edge / Policy-first gating ---
    from social_ritual import post_mood_update
    
    world_text = observe(memory)

    world_data = memory.get("world", {})
    edge = world_data.get("edge", 0.0)
    
    chosen_policy = select_mode(memory, edge)
    mode = chosen_policy.get("mode", "balanced")
    bucket = chosen_policy.get("bucket", "neutral")
    append_event(memory, {"type": "policy_chosen", **chosen_policy, "edge": edge})
    
    mood = world_data.get("mood", "🟡 Neutral")
    why = world_data.get("why", [])
    post_mood_update(memory, mood, edge, bucket, mode, why, world_text, outbox_dir=OUTBOX_DIR)

    # Policy gate
    if mode == "no_launch":
        append_event(memory, {"type": "gating_no_launch", "mode": mode, "bucket": bucket, "edge": edge})
        bandit_update = update_bandit(memory, bucket, mode, 0.0)
        append_event(memory, {"type": "learning_update", **bandit_update})

        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "timestamp_utc": utc_now_iso(),
            "agent": AGENT_NAME,
            "world_edge": edge,
            "decision": {"launch": False, "reason": "Policy gate: NO_LAUNCH"},
            "mode": mode,
            "bucket": bucket,
            "reward": bandit_update.get("reward"),
        }
        append_event(memory, {"type": "run", "record": record})
        print(f"World Edge: {edge:.2f}")
        print(f"Policy: {mode} ({bucket})")
        print(f"Selected action: {mode} (LLM: no, reason: policy gate no_launch)")
        save_memory(memory, MEMORY_PATH)
        print("memory.json saved.")
        return

    # Economy gate
    ok, why_eco = can_launch(memory)
    if not ok:
        append_event(memory, {"type": "gating_economy", "mode": mode, "bucket": bucket, "edge": edge, "why": why_eco})
        bandit_update = update_bandit(memory, bucket, mode, 0.0)
        append_event(memory, {"type": "learning_update", **bandit_update})

        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "timestamp_utc": utc_now_iso(),
            "agent": AGENT_NAME,
            "world_edge": edge,
            "decision": {"launch": False, "reason": f"ECONOMY_GATED: {why_eco}"},
            "mode": mode,
            "bucket": bucket,
            "reward": bandit_update.get("reward"),
        }
        append_event(memory, {"type": "run", "record": record})
        print(f"World Edge: {edge:.2f}")
        print(f"Policy: {mode} ({bucket})")
        print(f"Selected action: {mode} (LLM: no, reason: economy gate {why_eco})")
        save_memory(memory, MEMORY_PATH)
        print("memory.json saved.")
        return

    # Portfolio gate
    active_count = get_active_position_count(memory)
    if active_count >= MAX_ACTIVE_POSITIONS:
        reason = f"Portfolio full: {active_count} active positions (max {MAX_ACTIVE_POSITIONS})"
        append_event(memory, {
            "type": "gating_portfolio",
            "mode": mode,
            "bucket": bucket,
            "edge": edge,
            "reason": reason
        })

        bandit_update = update_bandit(memory, bucket, mode, 0.0)
        append_event(memory, {"type": "learning_update", **bandit_update})

        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "timestamp_utc": utc_now_iso(),
            "agent": AGENT_NAME,
            "world_edge": edge,
            "decision": {"launch": False, "reason": reason},
            "mode": mode,
            "bucket": bucket,
            "reward": bandit_update.get("reward"),
        }

        append_event(memory, {"type": "run", "record": record})
        print(f"World Edge: {edge:.2f}")
        print(f"Policy: {mode} ({bucket})")
        print(f"GATED: {reason}")
        save_memory(memory, MEMORY_PATH)
        print("memory.json saved.")
        return

    # Check if LLM should be called
    if not should_call_llm(mode):
        llm_reason = "MEMESEER_DISABLE_LLM=1" if os.getenv("MEMESEER_DISABLE_LLM") == "1" else "no_launch"
        append_event(memory, {"type": "gating_llm_disabled", "mode": mode, "bucket": bucket, "edge": edge, "reason": llm_reason})
        bandit_update = update_bandit(memory, bucket, mode, 0.0)
        append_event(memory, {"type": "learning_update", **bandit_update})

        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "timestamp_utc": utc_now_iso(),
            "agent": AGENT_NAME,
            "world_edge": edge,
            "decision": {"launch": False, "reason": f"LLM disabled: {llm_reason}"},
            "mode": mode,
            "bucket": bucket,
            "reward": bandit_update.get("reward"),
        }
        append_event(memory, {"type": "run", "record": record})
        print(f"World Edge: {edge:.2f}")
        print(f"Policy: {mode} ({bucket})")
        print(f"Selected action: {mode} (LLM: no, reason: {llm_reason})")
        save_memory(memory, MEMORY_PATH)
        print("memory.json saved.")
        return

    # Check API key
    api_key = get_openrouter_key()
    if not api_key:
        print("LLM unavailable (no OPENROUTER_API_KEY), forcing no_launch")
        append_event(memory, {"type": "gating_no_api_key", "mode": mode, "bucket": bucket, "edge": edge})
        bandit_update = update_bandit(memory, bucket, mode, 0.0)
        append_event(memory, {"type": "learning_update", **bandit_update})

        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "timestamp_utc": utc_now_iso(),
            "agent": AGENT_NAME,
            "world_edge": edge,
            "decision": {"launch": False, "reason": "No OPENROUTER_API_KEY"},
            "mode": mode,
            "bucket": bucket,
            "reward": bandit_update.get("reward"),
        }
        append_event(memory, {"type": "run", "record": record})
        save_memory(memory, MEMORY_PATH)
        print("memory.json saved.")
        return

    # --- LLM Branch ---
    print(f"Selected action: {mode} (LLM: yes)")
    
    try:
        thought = think(world_text + f"\nCalculated Market Edge: {edge:.2f}")
        decision = decide(thought)
    except RuntimeError as e:
        error_msg = str(e)
        print(f"LLM error: {error_msg}, forcing no_launch")
        append_event(memory, {"type": "gating_llm_error", "mode": mode, "bucket": bucket, "edge": edge, "error": error_msg})
        bandit_update = update_bandit(memory, bucket, mode, 0.0)
        append_event(memory, {"type": "learning_update", **bandit_update})

        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "timestamp_utc": utc_now_iso(),
            "agent": AGENT_NAME,
            "world_edge": edge,
            "decision": {"launch": False, "reason": f"LLM error: {error_msg}"},
            "mode": mode,
            "bucket": bucket,
            "reward": bandit_update.get("reward"),
        }
        append_event(memory, {"type": "run", "record": record})
        save_memory(memory, MEMORY_PATH)
        print("memory.json saved.")
        return

    # Decision gate
    if not decision.get("launch", False):
        append_event(memory, {"type": "gating_decide_no_launch", "mode": mode, "bucket": bucket, "edge": edge, "reason": decision.get("reason")})
        bandit_update = update_bandit(memory, bucket, mode, 0.0)
        append_event(memory, {"type": "learning_update", **bandit_update})

        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "timestamp_utc": utc_now_iso(),
            "agent": AGENT_NAME,
            "world_edge": edge,
            "decision": decision,
            "mode": mode,
            "bucket": bucket,
            "reward": bandit_update.get("reward"),
        }
        append_event(memory, {"type": "run", "record": record})
        print(f"World Edge: {edge:.2f}")
        print(f"Policy: {mode} ({bucket})")
        print(f"GATED: decide.launch=false (skipping execution). Reason: {decision.get('reason')}")
        save_memory(memory, MEMORY_PATH)
        print("memory.json saved.")
        return

    if decision.get("launch"):
        token_idea = generate_token_idea(thought)
        
        if not isinstance(token_idea, dict) or not token_idea.get("ticker"):
            print("Invalid token idea generated, skipping.")
            return

        # 1️⃣ Launch Lock Check
        control = memory.setdefault("launch_control", {"last_launch_timestamp": 0, "launch_in_progress": False})
        if control.get("launch_in_progress"):
            append_event(memory, {"type": "launch_blocked", "reason": "launch already in progress"})
            save_memory(memory, MEMORY_PATH)
            return

        # 2️⃣ Daily Cooldown Check
        now = utc_now_ts()
        last_launch = control.get("last_launch_timestamp", 0)
        cooldown_period = 86400 # 24 hours
        if now - last_launch < cooldown_period:
            append_event(memory, {"type": "launch_blocked", "reason": "daily cooldown active"})
            save_memory(memory, MEMORY_PATH)
            return

        # 3️⃣ Execute Launch via NadfunExecutor
        try:
            memory["launch_control"]["launch_in_progress"] = True
            save_memory(memory, MEMORY_PATH) # Save immediately to lock

            # 3.1 Rate limit check
            if is_rate_limited(memory):
                append_event(memory, {"type": "launch_blocked", "reason": "rate_limited"})
                raise Exception("Rate limited")

            # 3.2 Image generation
            print(f"[LAUNCH] Generating image for {token_idea.get('ticker')}...")
            img_path = generate_image(
                token_idea.get("name", "Unknown"),
                token_idea.get("ticker", "TKN"),
                memory.get("world", {}).get("mood", "Neutral")
            )
            
            # 3.3 On-chain Launch
            executor = NadfunExecutor()
            print(f"[LAUNCH] Executing on-chain launch for {token_idea.get('ticker')}...")
            
            launch_result = executor.launch_token(
                name=token_idea.get("name"),
                symbol=token_idea.get("ticker"),
                description=token_idea.get("narrative", "Generated by MemeSeer"),
                image_path=img_path
            )
            
            # 3.4 Success: Update memory and positions
            token_address = launch_result["token_address"]
            tx_hash = launch_result["tx_hash"]
            
            new_position = {
                "address": token_address,
                "symbol": token_idea.get("ticker"),
                "entry_mon": 200,
                "tx_hash": tx_hash,
                "mode": mode,
                "status": "active",
                "timestamp": utc_now_ts(),
                "iso_date": utc_now_iso(),
                "image_path": img_path
            }
            
            memory["portfolio"]["active_positions"].append(new_position)
            memory["launch_control"]["last_launch_timestamp"] = utc_now_ts()
            memory["launch_control"]["launch_in_progress"] = False
            
            append_event(memory, {"type": "portfolio_entry", **new_position})
            
            # 3.5 Social Ritual
            signals = {
                "social": {"highlights": ["On-chain launch successful", "Position ACTIVE"]},
                "onchain": {"highlights": [f"TX confirmed: {tx_hash}"]},
            }
            result = prepare_ritual_post(
                launch_json={k: v for k, v in token_idea.items() if k in ("name", "ticker", "narrative", "why_now")},
                reasoning=str(decision.get("reason", "")),
                signals=signals,
                outbox_dir=memory["social"].get("outbox_dir", OUTBOX_DIR),
                extra={
                    "balances": memory.get("economy", {}).get("balances", {}),
                    "policy": chosen_policy,
                },
            )
            outbox_path = result.outbox_path
            
            memory["launches"][result.launch_id] = {
                "created_at": utc_now_iso(),
                "ts": utc_now_ts(),
                "status": "LAUNCH_COMPLETE",
                "token_idea": {k: v for k, v in token_idea.items() if k in ("name", "ticker", "narrative", "why_now")},
                "world": world_text,
                "thought": thought,
                "decision": {k: v for k, v in decision.items() if k != "_raw"},
                "outbox_path": outbox_path,
                "tx_hash": tx_hash
            }
            memory["social"]["last_ritual_post_ts"] = utc_now_ts()
            memory["stats"]["ritual_posts_total"] = int(memory["stats"].get("ritual_posts_total", 0)) + 1
            append_event(memory, {"type": "ritual_post_written", "launch_id": result.launch_id, "outbox_path": outbox_path})
            
            launch_successful = True
            save_memory(memory, MEMORY_PATH)
            print(f"[LAUNCH SUCCESS] Token: {token_address}, Tx: {tx_hash}")

        except Exception as e:
            print(f"[LAUNCH ERROR] {e}")
            memory["launch_control"]["launch_in_progress"] = False
            append_event(memory, {"type": "launch_failed", "reason": str(e)})
            save_memory(memory, MEMORY_PATH)

    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "timestamp_utc": utc_now_iso(),
        "agent": AGENT_NAME,
        "world": world_text,
        "thought": thought,
        "decision": decision,
        "token_idea": token_idea,
        "outbox_path": outbox_path if outbox_path else None,
        "economy": memory.get("economy", {}),
        "learning": memory.get("learning", {}),
    }
    append_event(memory, {"type": "run", "record": record})

    print("World:", world_text)
    print("Thought:", thought)
    print("Decision:", {k: v for k, v in decision.items() if k != "_raw"})
    if launch_successful and token_idea:
        print("Token idea:", {k: v for k, v in token_idea.items() if k != "_raw"})
    if chosen_policy:
        print("Policy:", {k: chosen_policy[k] for k in chosen_policy if k in ("mode", "buyback_pct", "burn_pct")})
    if launch_successful and outbox_path:
        print("Ritual post:", outbox_path)
    print("Balances:", memory.get("economy", {}).get("balances"))

    save_memory(memory, MEMORY_PATH)
    print("memory.json saved.")


if __name__ == "__main__":
    main()
