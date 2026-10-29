# -*- coding: utf-8 -*-
"""توليد أيقونة التطبيق assets/icon.ico + icon.png — شغّله مرة واحدة عند الحاجة."""
import os
from PIL import Image, ImageDraw

SIZE = 256
BG = (31, 111, 235)      # أزرق
FG = (255, 255, 255)     # أبيض
ACCENT = (255, 193, 7)   # أصفر للموجات

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# خلفية مربعة بحواف دائرية
d.rounded_rectangle([8, 8, SIZE - 8, SIZE - 8], radius=52, fill=BG)

# جسم الميكروفون
d.rounded_rectangle([108, 38, 148, 138], radius=20, fill=FG)
# القوس حول الميكروفون
d.arc([76, 66, 180, 172], start=0, end=180, fill=FG, width=11)
d.line([76, 118, 76, 140], fill=FG, width=11)
d.line([180, 118, 180, 140], fill=FG, width=11)
# الساق والقاعدة
d.line([128, 172, 128, 202], fill=FG, width=11)
d.line([96, 204, 160, 204], fill=FG, width=11)

# موجات صوتية جانبية
d.arc([176, 52, 226, 118], start=300, end=60, fill=ACCENT, width=9)
d.arc([30, 52, 80, 118], start=120, end=240, fill=ACCENT, width=9)

out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
os.makedirs(out_dir, exist_ok=True)
img.save(os.path.join(out_dir, "icon.png"))
img.save(os.path.join(out_dir, "icon.ico"),
         sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("تم إنشاء الأيقونة في:", out_dir)
