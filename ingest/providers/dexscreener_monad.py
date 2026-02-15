import logging
import os
import re
from datetime import datetime, timezone
from urllib import request
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

def parse_formatted_value(val_str):
    """
    Parses strings like '$1.1M', '$116K', '113,893', '0.26%' into floats.
    """
    if not val_str or val_str == "-":
        return 0.0
    
    # Remove $, %, and commas
    clean_str = val_str.replace('$', '').replace('%', '').replace(',', '').strip()
    
    multiplier = 1.0
    if clean_str.endswith('M'):
        multiplier = 1_000_000.0
        clean_str = clean_str[:-1]
    elif clean_str.endswith('K'):
        multiplier = 1_000.0
        clean_str = clean_str[:-1]
    elif clean_str.endswith('B'):
        multiplier = 1_000_000_000.0
        clean_str = clean_str[:-1]
        
    try:
        return float(clean_str) * multiplier
    except ValueError:
        return 0.0

def fetch_monad_top_pairs(take=10):
    """
    Fetches top pairs from dexscreener.com/monad by parsing HTML table rows.
    """
    url = "https://dexscreener.com/monad"
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        req = request.Request(url, headers=headers)
        with request.urlopen(req) as response:
            html = response.read().decode('utf-8')
            
        # Debug: save HTML to file
        html_path = os.path.join(os.getcwd(), "dexscreener_monad.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
            f.flush()
            os.fsync(f.fileno())
        
        soup = BeautifulSoup(html, 'html.parser')
        rows = soup.find_all('a', class_=re.compile(r'ds-dex-table-row'))
        
        pairs = []
        for row in rows[:take]:
            pair_data = {}
            href = row.get('href', '')
            # href format: /monad/0x...
            pair_data['pairAddress'] = href.split('/')[-1]
            pair_data['url'] = f"https://dexscreener.com{href}"
            pair_data['chainId'] = "monad"
            
            # Base token symbol
            symbol_tag = row.find('span', class_='ds-dex-table-row-base-token-symbol')
            pair_data['baseTokenSymbol'] = symbol_tag.text if symbol_tag else "Unknown"
            
            # Name
            name_tag = row.find('span', class_='ds-dex-table-row-base-token-name-text')
            pair_data['baseTokenName'] = name_tag.text if name_tag else pair_data['baseTokenSymbol']
            
            # Price
            price_tag = row.find('div', class_='ds-dex-table-row-col-price')
            pair_data['priceUsd'] = parse_formatted_value(price_tag.text) if price_tag else 0.0
            
            # Liquidity
            liq_tag = row.find('div', class_='ds-dex-table-row-col-liquidity')
            pair_data['liquidityUsd'] = parse_formatted_value(liq_tag.text) if liq_tag else 0.0
            
            # Volume
            vol_tag = row.find('div', class_='ds-dex-table-row-col-volume')
            pair_data['volume24h'] = parse_formatted_value(vol_tag.text) if vol_tag else 0.0
            
            # Txns
            txns_tag = row.find('div', class_='ds-dex-table-row-col-txns')
            pair_data['txns24h'] = parse_formatted_value(txns_tag.text) if txns_tag else 0.0
            
            # Price Change 24h
            pc_tag = row.find('div', class_='ds-dex-table-row-col-price-change-h24')
            pair_data['priceChangeH24'] = parse_formatted_value(pc_tag.text) if pc_tag else 0.0
            
            pairs.append(pair_data)
            
        logger.info(f"Scraped {len(pairs)} monad pairs from DexScreener HTML table")
        return pairs
    except Exception as e:
        logger.error(f"Error fetching DexScreener Monad pairs: {e}")
        return []

def normalize_pair_to_post(pair: dict) -> dict | None:
    """
    Normalizes scraped pair data into external_feed post format.
    """
    try:
        fetched_at = datetime.now(timezone.utc).isoformat()
        symbol = pair.get('baseTokenSymbol', 'Unknown')
        price = pair.get('priceUsd', 0)
        liquidity = pair.get('liquidityUsd', 0)
        volume = pair.get('volume24h', 0)
        change = pair.get('priceChangeH24', 0)
        txns = pair.get('txns24h', 0)
        
        summary = f"🚀 Top Monad Pair: {symbol} at ${price:,.6f}. 24H Vol: ${volume:,.0f}, Liquidity: ${liquidity:,.0f}, 24H Change: {change}%"
        
        return {
            "id": f"dex:pair:monad:{pair['pairAddress']}",
            "source": "dexscreener",
            "fetched_at": fetched_at,
            "created_at": fetched_at,
            "author": {"id": None, "username": "dexscreener", "name": "DexScreener"},
            "text": summary,
            "url": pair['url'],
            "metrics": {
                "liquidity_usd": float(liquidity),
                "volume24h": float(volume),
                "txns24h": int(txns),
                "priceChange24h": float(change),
                "priceUsd": float(price)
            },
            "raw": pair
        }
    except Exception as e:
        logger.error(f"Error normalizing DexScreener pair: {e}")
        return None

def self_check_dex_monad():
    """
    Basic self-test for dexscreener_monad provider.
    """
    print("Running DexScreener Monad self-check...")
    pairs = fetch_monad_top_pairs(take=3)
    if not pairs:
        print("FAILED: No monad pairs fetched")
        return
    
    print(f"Successfully scraped {len(pairs)} pairs")
    for p in pairs:
        post = normalize_pair_to_post(p)
        if post:
            print(f"CHECK: {p['baseTokenSymbol']} | Price=${p['priceUsd']} | Liq=${p['liquidityUsd']} | URL={p['url']}")
        else:
            print(f"CHECK: Failed to normalize {p.get('pairAddress')}")
    print("Self-check completed.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    self_check_dex_monad()
