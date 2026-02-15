import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone

def fetch_dex_data(config: dict) -> list[dict]:
    """
    Fetch data from DexScreener API.
    """
    search_terms = config.get("dexscreener_monad_search_terms", ["MON", "Monad", "SEER"])
    all_data = []
    
    headers = {
        "Accept": "application/json",
        "User-Agent": "MemeSeer/1.0"
    }

    seen_pairs = set()

    for term in search_terms:
        encoded_term = urllib.parse.quote(term)
        url = f"https://api.dexscreener.com/latest/dex/search?q={encoded_term}"
        
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode('utf-8'))
                pairs = data.get("pairs", [])
                
                if not isinstance(pairs, list):
                    continue
                
                for pair in pairs:
                    pair_addr = pair.get("pairAddress")
                    if not pair_addr or pair_addr in seen_pairs:
                        continue
                    
                    seen_pairs.add(pair_addr)
                    
                    base_token = pair.get("baseToken", {})
                    symbol = base_token.get("symbol", "???")
                    
                    liq_usd = float(pair.get("liquidity", {}).get("usd", 0) or 0)
                    vol_24h = float(pair.get("volume", {}).get("h24", 0) or 0)
                    
                    # Use liquidity as engagement for Dex data
                    engagement = liq_usd if liq_usd > 0 else vol_24h
                    
                    text = f"Token {symbol} liquidity surge to ${liq_usd/1e6:.1f}M" if liq_usd > 1000000 else f"Token {symbol} data: liq ${liq_usd:,.0f}, vol ${vol_24h:,.0f}"
                    
                    item = {
                        "text": text,
                        "source": "dex",
                        "engagement": float(engagement),
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    all_data.append(item)
                    
        except Exception as e:
            print(f"[DEX] Error fetching data for {term}: {e}")
            continue

    return all_data
