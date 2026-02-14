import os
import time
from PIL import Image, ImageDraw, ImageFont


def generate_token_image(name, ticker, mood):
    # ---- Try AI first ----
    try:
        try:
            from generate_token_image_ai import generate_ai_token_image
        except ImportError:
            from .generate_token_image_ai import generate_ai_token_image

        print("[IMAGE] Trying AI generation...")
        return generate_ai_token_image(name, ticker, mood)

    except Exception as e:
        print(f"[AI IMAGE FAILED] {e}")
        print("Falling back to deterministic generator...")

    # ---- Fallback deterministic generator ----

    WIDTH, HEIGHT = 1024, 1024

    MASCOT_PATH = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "assets", "mascot.png")
    )
    OUTPUT_DIR = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "assets", "token_images")
    )

    if not os.path.exists(MASCOT_PATH):
        raise Exception(f"Mascot file not found at {MASCOT_PATH}. Launch aborted.")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    MOOD_COLORS = {
        "euphoric": "#2fff00",
        "bullish": "#4da6ff",
        "neutral": "#e6d3b3",
        "cautious": "#ffb347",
        "bearish": "#cc0000"
    }

    bg_color = MOOD_COLORS.get(mood.lower(), "#e6d3b3")

    img = Image.new("RGBA", (WIDTH, HEIGHT), bg_color)
    draw = ImageDraw.Draw(img)

    mascot = Image.open(MASCOT_PATH).convert("RGBA")
    target_width = int(WIDTH * 0.7)
    aspect_ratio = mascot.height / mascot.width
    target_height = int(target_width * aspect_ratio)
    mascot = mascot.resize((target_width, target_height), Image.Resampling.LANCZOS)

    paste_x = (WIDTH - target_width) // 2
    paste_y = (HEIGHT - target_height) // 2
    img.paste(mascot, (paste_x, paste_y), mascot)

    def draw_text_with_stroke(draw_obj, text, position, font, text_color="white", stroke_color="black", stroke_width=2):
        offsets = [
            (-stroke_width, -stroke_width), (0, -stroke_width), (stroke_width, -stroke_width),
            (-stroke_width, 0),                                (stroke_width, 0),
            (-stroke_width, stroke_width), (0, stroke_width), (stroke_width, stroke_width)
        ]

        for ox, oy in offsets:
            draw_obj.text((position[0] + ox, position[1] + oy),
                          text, font=font, fill=stroke_color, anchor="mm")

        draw_obj.text(position, text, font=font, fill=text_color, anchor="mm")

    ticker_size = 120
    name_size = 60

    try:
        font_ticker = ImageFont.load_default(size=ticker_size)
        font_name = ImageFont.load_default(size=name_size)
    except TypeError:
        font_ticker = ImageFont.load_default()
        font_name = ImageFont.load_default()

    draw_text_with_stroke(draw, ticker.upper(), (WIDTH // 2, HEIGHT // 2), font_ticker)
    draw_text_with_stroke(draw, name, (WIDTH // 2, HEIGHT // 8), font_name)

    filename = f"{ticker.lower()}_{int(time.time())}.png"
    output_path = os.path.join(OUTPUT_DIR, filename)

    img_to_save = img.convert("RGB")
    img_to_save.save(output_path, "PNG")

    if os.path.getsize(output_path) > 5 * 1024 * 1024:
        img_to_save.save(output_path, "PNG", optimize=True)

    rel_path = os.path.relpath(
        output_path,
        os.path.join(os.path.dirname(__file__), "..")
    )

    return rel_path.replace("\\", "/")
