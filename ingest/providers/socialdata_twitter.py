import os
import json
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone


class SocialDataTwitterProvider:
    BASE_URL = "https://api.socialdata.tools"
    
    def __init__(self):
        self.api_key = os.environ.get("SOCIALDATA_API_KEY")
        if not self.api_key:
            raise ValueError("SOCIALDATA_API_KEY environment variable not set")
    
    def fetch(self, query: str, count: int = 10) -> List[Dict[str, Any]]:
        try:
            url = f"{self.BASE_URL}/twitter/search?query={urllib.parse.quote(query)}&type=Latest"
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json"
            }
            
            req = urllib.request.Request(url, headers=headers)
            
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))
            
            tweets = data.get("tweets", [])
            posts = []
            
            for tweet in tweets[:count]:
                post = self._normalize_tweet(tweet)
                if post:
                    posts.append(post)
            
            return posts
            
        except urllib.error.HTTPError as e:
            print(f"HTTP error fetching tweets: {e.code} - {e.reason}")
            return []
        except urllib.error.URLError as e:
            print(f"URL error fetching tweets: {e.reason}")
            return []
        except Exception as e:
            print(f"Error fetching tweets: {e}")
            return []
    
    def _normalize_tweet(self, tweet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            tweet_id = tweet.get("id_str") or str(tweet.get("id", ""))
            if not tweet_id:
                return None
            
            user = tweet.get("user", {})
            username = user.get("screen_name", "")
            
            created_at = tweet.get("created_at", "")
            created_at_iso = self._parse_twitter_date(created_at)
            
            post = {
                "id": f"tweet:{tweet_id}",
                "source": "twitter",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "created_at": created_at_iso,
                "author": {
                    "id": user.get("id_str") or str(user.get("id", "")),
                    "username": username,
                    "name": user.get("name", "")
                },
                "text": tweet.get("full_text") or tweet.get("text", ""),
                "url": f"https://x.com/{username}/status/{tweet_id}" if username else None,
                "metrics": {
                    "like_count": tweet.get("favorite_count"),
                    "retweet_count": tweet.get("retweet_count"),
                    "reply_count": tweet.get("reply_count"),
                    "quote_count": tweet.get("quote_count")
                },
                "lang": tweet.get("lang"),
                "raw": {
                    "id": tweet.get("id"),
                    "conversation_id": tweet.get("conversation_id_str") or tweet.get("conversation_id"),
                    "possibly_sensitive": tweet.get("possibly_sensitive")
                }
            }
            
            return post
            
        except Exception as e:
            print(f"Error normalizing tweet: {e}")
            return None
    
    def _parse_twitter_date(self, date_str: str) -> Optional[str]:
        if not date_str:
            return None
        
        try:
            from datetime import datetime
            dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
            return dt.isoformat()
        except Exception:
            return date_str
