from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


OUTBOX_DIR_DEFAULT = "outbox"


@dataclass
class RitualPostResult:
    launch_id: str
    outbox_path: str
    content_md: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_launch_id(*parts: str) -> str:
    raw = "|".join([p.strip() for p in parts if p is not None])
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return h[:16]


def render_ritual_post(launch_json: Dict[str, Any], reasoning: str, signals: Optional[Dict[str, Any]] = None, style: str = "default", extra: Optional[Dict[str, Any]] = None) -> str:
    signals = signals or {}
    extra = extra or {}

    name = str(launch_json.get("name", "")).strip()
    ticker = str(launch_json.get("ticker", "")).strip()
    narrative = str(launch_json.get("narrative", "")).strip()
    why_now = str(launch_json.get("why_now", "")).strip()

    reasoning_short = (reasoning or "").strip().replace("\n", " ")
    if len(reasoning_short) > 260:
        reasoning_short = reasoning_short[:257] + "…"

    policy_line = ""
    if isinstance(extra.get("policy"), dict):
        p = extra["policy"]
        policy_line = f"**Policy:** buyback={p.get('buyback_pct')} burn={p.get('burn_pct')} (mode={p.get('mode')})\n\n"

    balances_line = ""
    if isinstance(extra.get("balances"), dict):
        b = extra["balances"]
        balances_line = f"**Balances:** SEER={b.get('seer')} | MON={b.get('mon')} | burned={b.get('seer_burned', 0)}\n\n"

    header = "MemeSeer spotted a window 👁️"
    cta = "If this gets traction, next step = onchain on nad.fun. React/RT to summon it."

    md = f"""# {header}

{balances_line}{policy_line}**Thesis:** {narrative if narrative else "(no narrative)"}

**Why now:** {why_now if why_now else "(no why_now)"}

**Draft token idea:** `${ticker}` — “{name}”

> {reasoning_short}

{cta}

---
**Machine-readable draft (source):**
```json
{json.dumps(launch_json, ensure_ascii=False, indent=2)}
```
"""
    return md


def write_outbox(filename_seed: str, content_md: str, outbox_dir: str = OUTBOX_DIR_DEFAULT) -> str:
    Path(outbox_dir).mkdir(parents=True, exist_ok=True)
    # Use timestamp to ensure uniqueness and sorting
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path(outbox_dir) / f"post_{ts}_{filename_seed}.md"
    path.write_text(content_md, encoding="utf-8")
    
    # Auto-index the outbox
    try:
        import subprocess
        import sys
        script_path = Path(__file__).parent / "scripts" / "build_outbox_index.py"
        if script_path.exists():
            subprocess.run([sys.executable, str(script_path)], check=False)
    except Exception as e:
        print(f"Failed to auto-index outbox: {e}")
        
    return path.as_posix()


def prepare_ritual_post(launch_json: Dict[str, Any], reasoning: str, signals: Optional[Dict[str, Any]] = None, *, style: str = "default", outbox_dir: str = OUTBOX_DIR_DEFAULT, launch_id_seed: Optional[str] = None, extra: Optional[Dict[str, Any]] = None) -> RitualPostResult:
    ticker = str(launch_json.get("ticker", "")).strip()
    name = str(launch_json.get("name", "")).strip()
    seed = launch_id_seed or _utc_now_iso()
    launch_id = make_launch_id(seed, ticker, name, (reasoning or "")[:80])
    content_md = render_ritual_post(launch_json, reasoning, signals=signals, style=style, extra=extra or {})
    outbox_path = write_outbox(f"launch_{launch_id}", content_md, outbox_dir=outbox_dir)
    return RitualPostResult(launch_id=launch_id, outbox_path=outbox_path, content_md=content_md)


def post_mood_update(memory: Dict[str, Any], mood: str, edge: float, bucket: str, mode: str, why: list[str], world_text: str, outbox_dir: str = OUTBOX_DIR_DEFAULT) -> str:
    """
    Writes a Mood Update post to the outbox.
    """
    signals = memory.get("world", {}).get("signals", {})
    
    # Format signals string
    sig_str = " ".join([f"{k}={v:.2f}" for k, v in signals.items() if isinstance(v, (int, float))])
    
    # Format why bullet points
    why_formatted = "\n".join([f"- {w}" for w in why])
    
    balances = memory.get("economy", {}).get("balances", {})
    bal_str = f"SEER={balances.get('seer', 0):.2f} | MON={balances.get('mon', 0):.2f}"

    content = f"""# MemeSeer Mood: {mood} ({edge:+.2f})

**Bucket:** {bucket} | **Policy:** {mode}
**Signals:** `{sig_str}`
**Balances:** {bal_str}

### Why?
{why_formatted}

### World View
{world_text}

---
*MemeSeer is observing the Moltiverse.*
"""
    
    # Filename based on mood
    filename_seed = f"mood_{bucket}_{mode}"
    return write_outbox(filename_seed, content, outbox_dir=outbox_dir)
