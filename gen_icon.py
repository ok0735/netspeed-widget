"""生成心电图风格的 ICO 图标文件 — 手动打包多尺寸 PNG 到 ICO"""
from PIL import Image, ImageDraw
import io
import os
import struct

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICO_PATH = os.path.join(SCRIPT_DIR, "netspeed.ico")

# Windows 支持的图标尺寸（现代 Windows 支持内嵌 PNG 的 ICO）
SIZES = [16, 24, 32, 48, 64, 128, 256]


def create_ecg_icon(size):
    """绘制心电图 + 上下箭头结合的图标"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    primary = (0, 255, 170)      # #00FFAA 青绿
    secondary = (0, 200, 136)    # 深一点

    cx, cy = size // 2, size // 2
    r = size // 2 - max(1, size // 20)

    if size <= 32:
        # 小尺寸：简化为上下箭头
        draw.polygon([
            (cx, cy - r + 1),
            (cx - r + 2, cy + 2),
            (cx + r - 2, cy + 2),
        ], fill=primary)
        draw.polygon([
            (cx, cy + r - 1),
            (cx - r + 2, cy - 2),
            (cx + r - 2, cy - 2),
        ], fill=secondary)
    else:
        # 大尺寸：圆底 + 心电图 + 上下箭头
        draw.ellipse([1, 1, size - 2, size - 2], outline=primary,
                     width=max(1, size // 32))
        draw.ellipse([2, 2, size - 3, size - 3],
                     fill=(0, 255, 170, 25))

        # 心电图折线
        margin = size // 6
        y_center = cy
        amplitude = size // 4
        pts = []
        steps = 24
        for i in range(steps + 1):
            x = margin + (size - 2 * margin) * i / steps
            t = i / steps
            if t < 0.18:
                y = y_center
            elif t < 0.24:
                y = y_center - amplitude * (t - 0.18) / 0.06
            elif t < 0.28:
                y = y_center - amplitude + amplitude * (t - 0.24) / 0.04
            elif t < 0.32:
                y = y_center + amplitude * 0.4
            elif t < 0.35:
                y = y_center - amplitude * 0.15
            elif t < 0.42:
                y = y_center
            elif t < 0.55:
                y = y_center
            elif t < 0.62:
                y = y_center + amplitude * 0.35
            elif t < 0.68:
                y = y_center - amplitude * 0.15
            elif t < 0.78:
                y = y_center
            else:
                y = y_center
            pts.append((x, y))

        draw.line(pts, fill=primary, width=max(2, size // 32))

        # 上下箭头
        arrow_s = size // 7
        gap = size // 16
        # 上箭头
        ax = cx - gap - arrow_s
        ay = cy + size // 8
        draw.polygon([
            (ax, ay - arrow_s),
            (ax - arrow_s // 2, ay + arrow_s // 3),
            (ax + arrow_s // 2, ay + arrow_s // 3),
        ], fill=primary)
        # 下箭头
        dx = cx + gap + arrow_s
        dy = cy + size // 8
        draw.polygon([
            (dx, dy + arrow_s),
            (dx - arrow_s // 2, dy - arrow_s // 3),
            (dx + arrow_s // 2, dy - arrow_s // 3),
        ], fill=secondary)

    return img


# ─── 生成所有尺寸的 PNG 数据 ───
png_data_list = []
for s in SIZES:
    img = create_ecg_icon(s)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_data_list.append(buf.getvalue())

# ─── 手动打包 ICO ───
# ICO 文件格式：
#   HEADER: reserved(2) + type(2) + count(2)
#   DIR[]:  w(1) + h(1) + colors(1) + reserved(1) + planes(2) + bpp(2) + size(4) + offset(4)
#   DATA[]: PNG 数据

header = struct.pack('<HHH', 0, 1, len(SIZES))  # reserved=0, type=1(ico), count

offset = 6 + 16 * len(SIZES)  # header + directory entries
dir_entries = b""
for i, s in enumerate(SIZES):
    png_data = png_data_list[i]
    # 目录项：w, h (255=256), colors, reserved, planes, bpp, size, offset
    w = 0 if s == 256 else s
    h = 0 if s == 256 else s
    dir_entries += struct.pack('<BBBBHHII',
                               w, h, 0, 0,  # width, height, colors, reserved
                               1, 32,        # planes, bpp
                               len(png_data), offset)
    offset += len(png_data)

# 写入文件
with open(ICO_PATH, 'wb') as f:
    f.write(header)
    f.write(dir_entries)
    for data in png_data_list:
        f.write(data)

file_size = os.path.getsize(ICO_PATH)
print(f"ICO 已生成: {ICO_PATH} ({file_size:,} bytes)")
print(f"包含尺寸: {SIZES}")

# 验证
verify = Image.open(ICO_PATH)
n = 0
while True:
    try:
        verify.seek(n)
        print(f"  帧 {n}: {verify.size}")
        n += 1
    except EOFError:
        break
    except Exception:
        break
print(f"共 {n} 个尺寸 ✓")
