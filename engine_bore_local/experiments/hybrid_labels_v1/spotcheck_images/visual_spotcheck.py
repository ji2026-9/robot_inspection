from pathlib import Path
import json
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(r'C:\Users\86189\Documents\Codex\engine_bore_local')
OUT = ROOT / 'experiments' / 'hybrid_labels_v1' / 'spotcheck_images'
OUT.mkdir(parents=True, exist_ok=True)
LOCAL = ROOT / 'data' / 'database_seed'
FRIEND = ROOT / 'friend_package' / 'package_v1' / 'dataset' / 'box_yolo'
FONT = ImageFont.truetype(r'C:\Windows\Fonts\arial.ttf', 22)
FRIEND_COLOR = (255, 140, 20)
BORE_COLOR = (0, 210, 255)
PART_COLOR = (30, 255, 90)

def files_for(stem):
    label = next((FRIEND / 'labels').rglob(stem + '.txt'))
    photo = next((FRIEND / 'images').rglob(stem + '.jpg'))
    return label, photo

def polygons_for(stem):
    im = Image.open(LOCAL / (stem + '.jpg')).convert('RGB')
    w, h = im.size
    data = json.loads((LOCAL / (stem + '.json')).read_text(encoding='utf-8-sig'))
    local = [(s['label'], np.asarray(s['points'], np.float32)) for s in data['shapes']]
    label, photo = files_for(stem)
    friend = []
    for line in label.read_text().splitlines():
        v = [float(x) for x in line.split()]
        if v and int(v[0]) == 0:
            friend.append(np.asarray(v[1:], np.float32).reshape(-1, 2) * [w, h])
    return im, local, friend, photo

def overlay(stem, mode='both', width=1400):
    im, local, friend, photo = polygons_for(stem)
    ratio = width / im.width
    im = im.resize((width, round(im.height * ratio)), Image.Resampling.LANCZOS)
    canvas = ImageDraw.Draw(im)
    if mode in ('both', 'friend'):
        for pts in friend:
            p = [(float(x * ratio), float(y * ratio)) for x, y in pts]
            canvas.line(p + [p[0]], fill=FRIEND_COLOR, width=4)
    if mode in ('both', 'local'):
        for label, pts in local:
            p = [(float(x * ratio), float(y * ratio)) for x, y in pts]
            color = BORE_COLOR if label == 'bore' else PART_COLOR
            canvas.line(p + [p[0]], fill=color, width=4)
    return im

def panel(im, title):
    result = Image.new('RGB', (im.width, im.height + 45), (24, 24, 24))
    result.paste(im, (0, 45))
    ImageDraw.Draw(result).text((10, 10), title, fill='white', font=FONT)
    return result

def selected(stem):
    both = panel(overlay(stem), f'{stem}: orange=friend bore; cyan=local bore; green=local part')
    both.save(OUT / f'{stem}_overlay.png')
    raw, local, friend, photo = polygons_for(stem)
    raw.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
    a = panel(raw, f'{stem}: original')
    b = panel(overlay(stem, 'friend', raw.width), 'Friend bore (orange)')
    c = panel(overlay(stem, 'local', raw.width), 'Local bore (cyan), part (green)')
    total = Image.new('RGB', (a.width * 3, max(a.height, b.height, c.height)), (24, 24, 24))
    for i, p in enumerate([a, b, c]):
        total.paste(p, (i * a.width, 0))
    total.save(OUT / f'{stem}_three_views.png')
    im, local, friend, photo = polygons_for(stem)
    summary = {'id':stem, 'local_dimensions':im.size, 'friend_dimensions':Image.open(photo).size,
               'local_shapes':[(lab, len(p), np.min(p, axis=0).tolist(), np.max(p, axis=0).tolist()) for lab,p in local],
               'friend_bores':[(len(p), np.min(p, axis=0).tolist(), np.max(p, axis=0).tolist()) for p in friend]}
    print(json.dumps(summary))

def crop_compare(stem, box, suffix):
    raw, local, friend, photo = polygons_for(stem)
    images = []
    for mode, title in [('raw', 'Original'), ('friend', 'Friend bore (orange)'), ('local', 'Local bore (cyan)'), ('both', 'Both contours')]:
        im = raw.copy()
        canvas = ImageDraw.Draw(im)
        if mode in ('friend', 'both'):
            for pts in friend:
                p = [tuple(map(float, v)) for v in pts]
                canvas.line(p + [p[0]], fill=FRIEND_COLOR, width=5)
        if mode in ('local', 'both'):
            for label, pts in local:
                if label == 'bore':
                    p = [tuple(map(float, v)) for v in pts]
                    canvas.line(p + [p[0]], fill=BORE_COLOR, width=5)
        im = im.crop(box)
        im = im.resize((1000, round(im.height * 1000/im.width)), Image.Resampling.LANCZOS)
        images.append(panel(im, f'{stem}: {title}'))
    result = Image.new('RGB', (2000, images[0].height * 2), (24,24,24))
    for i, im in enumerate(images):
        result.paste(im, ((i % 2)*1000, (i//2)*im.height))
    result.save(OUT/f'{stem}_{suffix}.png')

cells = []
for i in range(1,26):
    stem = f'{i:03d}'
    im = overlay(stem, width=450)
    cell = Image.new('RGB', (500, 430), (24,24,24))
    im.thumbnail((500,385), Image.Resampling.LANCZOS)
    cell.paste(im, ((500-im.width)//2, 40+(385-im.height)//2))
    ImageDraw.Draw(cell).text((10,8), stem, fill='white', font=FONT)
    cells.append(cell)
sheet = Image.new('RGB',(2500,2150),(24,24,24))
for i, cell in enumerate(cells):
    sheet.paste(cell, ((i%5)*500,(i//5)*430))
sheet.save(OUT/'contact_sheet_25.png')
for stem in ['023','025','018','021']:
    selected(stem)
crop_compare('023', (950, 730, 1690, 1040), 'far_bore_zoom')
crop_compare('025', (140, 460, 1020, 1110), 'left_bore_zoom')
