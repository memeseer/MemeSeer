import os
import time
import base64
import requests

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

OPENROUTER_URL = "https://openrouter.ai/api/v1/images/generations"

OUTPUT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "assets", "token_images")
)


def _post_with_retry(payload):
    max_retries = 4

    for attempt in range(max_retries):
        resp = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120,
        )

        if resp.status_code == 429:
            wait = 2 ** attempt
            print(f"[OpenRouter RateLimit] Waiting {wait}s...")
            time.sleep(wait)
            continue

        resp.raise_for_status()
        return resp.json()

    raise Exception("OpenRouter request failed after retries")


def generate_ai_token_image(name, ticker, mood):
    if not OPENROUTER_API_KEY:
        raise Exception("Missing OPENROUTER_API_KEY")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    prompt = f"""
Create a high quality crypto memecoin logo.
1:1 square format.
Clean solid background.
Bold centered mascot-style character.
Large readable ticker text: {ticker}.
Theme mood: {mood}.
Style: modern crypto branding, vector illustration, high contrast.
No watermark. No extra text.
"""

    payload = {
        "model": "openai/dall-e-3",
        "prompt": prompt,
        "size": "1024x1024",
    }

    data = _post_with_retry(payload)

    image_bytes = None

    # OpenRouter returns either url or b64_json
    if "data" in data and len(data["data"]) > 0:
        img_data = data["data"][0]

        if "b64_json" in img_data:
            image_bytes = base64.b64decode(img_data["b64_json"])

        elif "url" in img_data:
            img_resp = requests.get(img_data["url"], timeout=60)
            img_resp.raise_for_status()
            image_bytes = img_resp.content

    if not image_bytes:
        raise Exception("No image returned from OpenRouter")

    filename = f"{ticker.lower()}_{int(time.time())}.png"
    output_path = os.path.join(OUTPUT_DIR, filename)

    with open(output_path, "wb") as f:
        f.write(image_bytes)

    # Safety: <5MB
    if os.path.getsize(output_path) > 5 * 1024 * 1024:
        raise Exception("Generated image exceeds 5MB limit")

    rel_path = os.path.relpath(
        output_path,
        os.path.join(os.path.dirname(__file__), "..")
    )

    return rel_path.replace("\\", "/")

