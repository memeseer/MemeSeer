import os
import time
import base64
import requests

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

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
            timeout=90,
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
        "model": "openai/gpt-4.1",  # image-capable multimodal model via OpenRouter
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "modalities": ["image"],
        "size": "1024x1024"
    }

    data = _post_with_retry(payload)

    choice = data["choices"][0]["message"]

    image_bytes = None

    # Handle multiple possible formats
    if "images" in choice:
        image_info = choice["images"][0]

        if "b64_json" in image_info:
            image_bytes = base64.b64decode(image_info["b64_json"])

        elif "imageUrl" in image_info:
            url = image_info["imageUrl"]["url"]
            img_resp = requests.get(url, timeout=60)
            img_resp.raise_for_status()
            image_bytes = img_resp.content

    if not image_bytes:
        raise Exception("No image returned from OpenRouter")

    filename = f"{ticker.lower()}_{int(time.time())}.png"
    output_path = os.path.join(OUTPUT_DIR, filename)

    with open(output_path, "wb") as f:
        f.write(image_bytes)

    # Ensure <5MB
    if os.path.getsize(output_path) > 5 * 1024 * 1024:
        raise Exception("Generated image exceeds 5MB limit")

    rel_path = os.path.relpath(
        output_path,
        os.path.join(os.path.dirname(__file__), "..")
    )

    return rel_path.replace("\\", "/")
