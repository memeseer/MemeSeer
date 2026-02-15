import json
import os
import sys
from datetime import datetime, timezone
import traceback

# Ensure the project root is in sys.path to allow absolute imports like 'from ingest.providers...'
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from ingest.providers.socialdata import fetch_social_posts
    from ingest.providers.dexscreener import fetch_dex_data
except ImportError:
    # Fallback for local execution within ingest/
    try:
        from providers.socialdata import fetch_social_posts
        from providers.dexscreener import fetch_dex_data
    except ImportError:
        print("[INGEST] Critical Error: Could not import providers.")
        def fetch_social_posts(c): return []
        def fetch_dex_data(c): return []

def generate_external_feed(output_path="external_feed.json"):
    """
    Aggregate data from multiple providers and generate external_feed.json.
    """
    try:
        print("[INGEST] Starting ingestion process...")
        
        # Load config
        config_path = os.path.join(current_dir, "config.json")
        config = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception as e:
                print(f"[INGEST] Warning: Could not load config.json: {e}")
        else:
            print("[INGEST] Warning: config.json not found, using defaults.")

        # Fetch from providers
        social_posts = []
        try:
            social_posts = fetch_social_posts(config)
            print(f"[INGEST] Twitter count: {len(social_posts)}")
        except Exception as e:
            print(f"[INGEST] Error fetching from SocialData: {e}")

        dex_posts = []
        try:
            dex_posts = fetch_dex_data(config)
            print(f"[INGEST] Dex count: {len(dex_posts)}")
        except Exception as e:
            print(f"[INGEST] Error fetching from DexScreener: {e}")

        # Merge and sort
        # To ensure both sources are present, we take top Twitter and top Dex posts separately first
        social_posts.sort(key=lambda x: float(x.get("engagement", 0)), reverse=True)
        dex_posts.sort(key=lambda x: float(x.get("engagement", 0)), reverse=True)
        
        # Priority: Twitter first, then Dex. Within each, higher engagement first.
        def sort_key(post):
            # source_priority: twitter (0) > dex (1)
            source_priority = 0 if post.get("source") == "twitter" else 1
            # engagement: negated to sort descending
            engagement = float(post.get("engagement", 0))
            return (source_priority, -engagement)

        # Take top 20 from Twitter and top 10 from Dex (or adjust if one is empty)
        balanced_posts = social_posts[:20] + dex_posts[:10]
        
        # If we have less than 30, fill up with remaining
        if len(balanced_posts) < 30:
            remaining_social = social_posts[20:]
            remaining_dex = dex_posts[10:]
            # Sort remaining by engagement across both? Or just greedily fill.
            # Let's just fill greedily starting with Twitter for now
            total_needed = 30 - len(balanced_posts)
            balanced_posts.extend(remaining_social[:total_needed])
            
            total_needed = 30 - len(balanced_posts)
            if total_needed > 0:
                balanced_posts.extend(remaining_dex[:total_needed])

        balanced_posts.sort(key=sort_key)
        
        # Keep max 30 entries
        final_posts = balanced_posts[:30]
        print(f"[INGEST] Final count: {len(final_posts)}")
        
        # Prepare output
        feed = {
            "source": "ingestion_v1",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "posts": final_posts
        }
        
        # Write to file
        full_output_path = os.path.abspath(os.path.join(project_root, "external_feed.json"))
        with open(full_output_path, "w", encoding="utf-8") as f:
            json.dump(feed, f, indent=2, ensure_ascii=False)
            
        print(f"[INGEST] Successfully generated {full_output_path}")
        
    except Exception as e:
        print(f"[INGEST] CRITICAL ERROR in generate_external_feed: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    generate_external_feed()
