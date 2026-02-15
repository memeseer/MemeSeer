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

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "MemeSeer",
    }

    for attempt in range(max_retries):
        resp = requests.post(
            OPENROUTER_URL,
            headers=headers,
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
Create a viral crypto memecoin logo.

1:1 square format.
Bold, chaotic, internet-native energy.
Big expressive mascot character in the center.
Exaggerated facial expression (crazy, euphoric, degen energy).
Thick outlines, high contrast, vibrant colors.

Large readable ticker text: {ticker}
Make the ticker feel powerful and meme-worthy.

Mood: {mood}

Style:
- Crypto Twitter culture
- Degen energy
- Slight absurdity
- Bold vector illustration
- Clean but explosive composition

No watermark.
No extra random text.
No realistic photography.
No blur.
"""

    payload = {
        "model": "google/gemini-2.5-flash-image",
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "modalities": ["image"],
        "size": "1024x1024"
    }

    print("[IMAGE] Sending request to OpenRouter...")
    data = _post_with_retry(payload)

    image_bytes = None

    # Debug info (можешь убрать потом)
    print("[IMAGE] Response keys:", list(data.keys()))

    if "choices" in data and len(data["choices"]) > 0:
        message = data["choices"][0]["message"]

        # Variant 1: images array
        if "images" in message and len(message["images"]) > 0:
            image_info = message["images"][0]

            # Case A: base64 directly
            if "b64_json" in image_info:
                image_bytes = base64.b64decode(image_info["b64_json"])

            # Case B: image_url
            elif "image_url" in image_info:
                url = image_info["image_url"]["url"]

                # 🟢 Handle base64 data URL
                if url.startswith("data:image"):
                    header, encoded = url.split(",", 1)
                    image_bytes = base64.b64decode(encoded)
                else:
                    img_resp = requests.get(url, timeout=60)
                    img_resp.raise_for_status()
                    image_bytes = img_resp.content

    if not image_bytes:
        raise Exception(f"No image returned from OpenRouter. Raw: {data}")

    filename = f"{ticker.lower()}_{int(time.time())}.png"
    output_path = os.path.join(OUTPUT_DIR, filename)

    with open(output_path, "wb") as f:
        f.write(image_bytes)

    # Safety: file size < 5MB
    if os.path.getsize(output_path) > 5 * 1024 * 1024:
        raise Exception("Generated image exceeds 5MB limit")

    rel_path = os.path.relpath(
        output_path,
        os.path.join(os.path.dirname(__file__), "..")
    )

    print(f"[IMAGE] Saved: {rel_path}")

    return rel_path.replace("\\", "/")



