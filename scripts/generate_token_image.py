import os
import time
from PIL import Image, ImageDraw, ImageFont

def generate_token_image(name, ticker, mood):
    """
    Generates a deterministic token image for MemeSeer.
    
    Args:
        name (str): The name of the token.
        ticker (str): The ticker/symbol of the token.
        mood (str): The sentiment mood (euphoric, bullish, neutral, cautious, bearish).
        
    Returns:
        str: Relative path to the saved image.
        
    Raises:
        Exception: If mascot.png is missing or saving fails.
    """
    # 1. Image Specifications
    WIDTH, HEIGHT = 1024, 1024
    MASCOT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "mascot.png"))
    OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "token_images"))
    
    if not os.path.exists(MASCOT_PATH):
        raise Exception(f"Mascot file not found at {MASCOT_PATH}. Launch aborted.")
    
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # 2. Mood Colors
    MOOD_COLORS = {
        "euphoric": "#2fff00",
        "bullish": "#4da6ff",
        "neutral": "#e6d3b3",
        "cautious": "#ffb347",
        "bearish": "#cc0000"
    }
    bg_color = MOOD_COLORS.get(mood.lower(), "#e6d3b3")
    
    # 3. Create Base Image
    img = Image.new("RGBA", (WIDTH, HEIGHT), bg_color)
    draw = ImageDraw.Draw(img)
    
    # 4. Load Mascot
    try:
        mascot = Image.open(MASCOT_PATH).convert("RGBA")
        # Resize to ~70% width
        target_width = int(WIDTH * 0.7)
        aspect_ratio = mascot.height / mascot.width
        target_height = int(target_width * aspect_ratio)
        mascot = mascot.resize((target_width, target_height), Image.Resampling.LANCZOS)
        
        # Center mascot
        paste_x = (WIDTH - target_width) // 2
        paste_y = (HEIGHT - target_height) // 2
        img.paste(mascot, (paste_x, paste_y), mascot)
    except Exception as e:
        raise Exception(f"Failed to process mascot: {str(e)}")
    
    # 5. Text Rendering
    def draw_text_with_stroke(draw_obj, text, position, font, text_color="white", stroke_color="black", stroke_width=2):
        x, y = position
        # Draw stroke (8 offsets)
        for offset_x in range(-stroke_width, stroke_width + 1):
            if offset_x == 0 and stroke_width > 0: continue # Skip center for center, but we do 8 points
            for offset_y in range(-stroke_width, stroke_width + 1):
                if offset_x == 0 and offset_y == 0:
                    continue
                # We specifically want 8 points as per requirements (-2 to +2 px)
                # But range(-2, 3) gives -2, -1, 0, 1, 2. 
                # The request says "8 times around offset (-2 to +2 px)"
        
        # Explicit 8 points for clarity and deterministic behavior
        offsets = [
            (-stroke_width, -stroke_width), (0, -stroke_width), (stroke_width, -stroke_width),
            (-stroke_width, 0),                                (stroke_width, 0),
            (-stroke_width, stroke_width), (0, stroke_width), (stroke_width, stroke_width)
        ]
        
        for ox, oy in offsets:
            draw_obj.text((x + ox, y + oy), text, font=font, fill=stroke_color, anchor="mm")
        
        # Draw main text
        draw_obj.text((x, y), text, font=font, fill=text_color, anchor="mm")

    # Font Setup
    # Ticker font size (Large)
    ticker_size = 120
    # Name font size (Smaller)
    name_size = 60
    
    try:
        # Try to find a system font first for better look, but fallback to default
        # Pillow 10+ supports size in load_default()
        font_ticker = ImageFont.load_default(size=ticker_size)
        font_name = ImageFont.load_default(size=name_size)
    except TypeError:
        # Fallback for older Pillow
        font_ticker = ImageFont.load_default()
        font_name = ImageFont.load_default()

    # Draw Ticker (Center)
    draw_text_with_stroke(draw, ticker.upper(), (WIDTH // 2, HEIGHT // 2), font_ticker, stroke_width=2)
    
    # Draw Name (Top Centered)
    draw_text_with_stroke(draw, name, (WIDTH // 2, HEIGHT // 8), font_name, stroke_width=2)
    
    # 6. Save and Verify
    timestamp = int(time.time())
    filename = f"{ticker.lower()}_{timestamp}.png"
    output_path = os.path.join(OUTPUT_DIR, filename)
    
    try:
        # Convert back to RGB for size check if needed, but PNG is fine. 
        # PNG 1024x1024 is usually < 5MB unless very noisy.
        img_to_save = img.convert("RGB") # Requirements say background is solid color
        img_to_save.save(output_path, "PNG")
        
        # Check file size
        file_size = os.path.getsize(output_path)
        if file_size > 5 * 1024 * 1024:
            # Try optimize
            img_to_save.save(output_path, "PNG", optimize=True)
            file_size = os.path.getsize(output_path)
            if file_size > 5 * 1024 * 1024:
                raise Exception(f"Image size {file_size} exceeds 5MB limit even after optimization.")
    except Exception as e:
        if os.path.exists(output_path):
            os.remove(output_path)
        raise Exception(f"Failed to save image: {str(e)}")
    
    # Return relative path from project root
    rel_path = os.path.relpath(output_path, os.path.join(os.path.dirname(__file__), ".."))
    return rel_path.replace("\\", "/")

if __name__ == "__main__":
    # Quick test if run directly
    try:
        path = generate_token_image("Antigravity AI", "ANTI", "bullish")
        print(f"Success: {path}")
    except Exception as e:
        print(f"Error: {e}")
