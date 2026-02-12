import os
import json
from pathlib import Path

def build_index(outbox_dir: str = "outbox", target_file: str = "outbox/index.json", max_posts: int = 20):
    """
    Scans the outbox directory for markdown posts, sorts them by newest first,
    and writes an index.json file for the static frontend.
    """
    outbox_path = Path(outbox_dir)
    if not outbox_path.exists():
        print(f"Directory {outbox_dir} not found.")
        return

    # Find all .md files
    posts = [f.name for f in outbox_path.glob("*.md")]
    
    # Sort by filename (which includes YYYYMMDD_HHMMSS) in reverse order
    # Example: post_20260210_175410_launch_e291427887d5e6fd.md
    posts.sort(reverse=True)

    # Take the latest 20
    latest_posts = posts[:max_posts]

    index_data = {
        "posts": latest_posts,
        "updated_at": Path(target_file).parent.name if Path(target_file).exists() else "new",
        "count": len(latest_posts)
    }
    
    # Add a timestamp to updated_at for cache busting if needed
    import time
    index_data["updated_at"] = int(time.time())

    with open(target_file, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2)
    
    print(f"Indexed {len(latest_posts)} posts to {target_file}")

if __name__ == "__main__":
    # If run from scripts/ folder, adjust paths
    base_dir = Path(__file__).parent.parent
    build_index(
        outbox_dir=str(base_dir / "outbox"),
        target_file=str(base_dir / "outbox" / "index.json")
    )
