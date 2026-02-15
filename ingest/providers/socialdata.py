import json
import urllib.request
import urllib.parse
import urllib.error
import os
from datetime import datetime, timezone

def fetch_social_posts(config: dict) -> list[dict]:
    """
    Fetch social posts from Twitter via socialdata.py with hardening.
    """
    api_key = os.environ.get("SOCIALDATA_API_KEY")
    if not api_key:
        print("[SOCIALDATA] Error: SOCIALDATA_API_KEY not found in environment.")
        return []

    accounts = config.get("accounts", [])
    if not accounts:
        print("[SOCIALDATA] No accounts configured.")
        return []

    all_posts = []
    base_url = "https://api.socialdata.tools/twitter/search"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": "MemeSeer/1.0"
    }

    for account in accounts:
        query = f"from:{account} -filter:replies -filter:retweets"
        params = {
            "query": query,
            "type": "Latest"
        }
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        
        req = urllib.request.Request(url, headers=headers)
        
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                status_code = response.getcode()
                raw_body = response.read().decode('utf-8')
                
                # Debug log raw response
                print(f"[SOCIALDATA] RAW Response (first 300 chars): {raw_body[:300]}")

                if not raw_body.strip():
                    print(f"[SOCIALDATA] Received empty response for {account}")
                    continue

                try:
                    data = json.loads(raw_body)
                except json.JSONDecodeError:
                    print(f"[SOCIALDATA] FAILED TO PARSE JSON for {account}")
                    continue

                tweets = data.get("tweets", [])
                if not isinstance(tweets, list):
                    tweets = data.get("data", [])
                
                if isinstance(tweets, list):
                    for tweet in tweets:
                        likes = tweet.get("favorite_count", 0)
                        retweets = tweet.get("retweet_count", 0)
                        replies = tweet.get("reply_count", 0)
                        engagement = int(likes) + int(retweets) + int(replies)
                        
                        created_at = tweet.get("created_at")
                        # Standardize Twitter timestamp to ISO if possible, though Twitter usually provides it
                        
                        post = {
                            "text": tweet.get("full_text") or tweet.get("text") or "",
                            "source": "twitter",
                            "engagement": engagement,
                            "timestamp": created_at
                        }
                        if post["text"]:
                            all_posts.append(post)
                            
        except urllib.error.HTTPError as e:
            try:
                error_body = e.read().decode('utf-8')
                print(f"[SOCIALDATA] HTTP Error {e.code}: {error_body[:300]}")
            except:
                print(f"[SOCIALDATA] HTTP Error {e.code}")
            
            if e.code == 429:
                print("[SOCIALDATA] Rate limit hit (429).")
                break 
        except Exception as e:
            print(f"[SOCIALDATA] Error fetching for {account}: {e}")
            continue

    return all_posts
