# -*- coding: utf-8 -*-
"""
Presentation helper: draws the photo into a nicely styled canvas.
================================================================
Pure drawing code - it never touches the detection pipeline or project data.

The old GUI put the photo straight into a big flat dark QLabel, which left a
lot of ugly empty space around portrait photos. Here we instead:
  * draw a soft vertical gradient background,
  * optionally zoom into the workpiece region (auto-fit),
  * draw a subtle drop shadow + thin border around the photo itself.
"""

import cv2
import numpy as np


def _gradient_canvas(h, w, top=(252, 249, 246), bottom=(240, 245, 250)):
    """Vertical gradient background (BGR).

    [local patch] light grey-blue: #f6f9fc (top) -> #f0f5fa (bottom),
    to match the light application theme.
    NOTE: OpenCV expects BGR, so the tuples are reversed on purpose.
    """
    t = np.linspace(0.0, 1.0, max(h, 1), dtype=np.float32)[:, None]
    col = (np.array(top, np.float32)[None, :] * (1 - t) +
           np.array(bottom, np.float32)[None, :] * t)
    canvas = np.repeat(col[:, None, :], w, axis=1)
    return canvas.astype(np.uint8)


def _fit_size(src_w, src_h, max_w, max_h):
    if src_w <= 0 or src_h <= 0:
        return 1, 1
    s = min(max_w / src_w, max_h / src_h)
    return max(1, int(round(src_w * s))), max(1, int(round(src_h * s)))


def expand_rect(rect, factor, shape):
    """Expand a (x, y, w, h) rect by `factor` and clamp it to the image."""
    x, y, w, h = rect
    cx, cy = x + w / 2.0, y + h / 2.0
    w2, h2 = w * factor, h * factor
    x0 = int(max(0, cx - w2 / 2))
    y0 = int(max(0, cy - h2 / 2))
    x1 = int(min(shape[1], cx + w2 / 2))
    y1 = int(min(shape[0], cy + h2 / 2))
    if x1 - x0 < 32 or y1 - y0 < 32:
        return 0, 0, shape[1], shape[0]
    return x0, y0, x1 - x0, y1 - y0


def holes_bbox(result, shape, pad=1.45):
    """Bounding box (x, y, w, h) around all detected holes, expanded by `pad`."""
    holes = (result or {}).get("holes", [])
    if not holes:
        return None
    # OpenCV ellipse axes rotate with the angle; using the raw axes as screen
    # width/height can crop the edge of a tilted hole.
    bounds = []
    for hole in holes:
        ellipse = hole["ellipse"]
        theta = np.deg2rad(ellipse.get("angle", 0))
        a, b = ellipse["width"] / 2, ellipse["height"] / 2
        rx = np.sqrt((a * np.cos(theta)) ** 2 + (b * np.sin(theta)) ** 2)
        ry = np.sqrt((a * np.sin(theta)) ** 2 + (b * np.cos(theta)) ** 2)
        cx, cy = hole["center_px"]
        bounds.append((cx - rx, cx + rx, cy - ry, cy + ry))
    xs0, xs1, ys0, ys1 = zip(*bounds)
    rect = (min(xs0), min(ys0), max(xs1) - min(xs0), max(ys1) - min(ys0))
    return expand_rect(rect, pad, shape)


def zoom_rect(rect, factor, shape):
    """Shrink `rect` around its centre by `factor` (>1 = zoom in)."""
    if rect is None or factor <= 1.0:
        return rect
    x, y, w, h = rect
    cx, cy = x + w / 2.0, y + h / 2.0
    nw, nh = w / factor, h / factor
    x0 = int(max(0, cx - nw / 2))
    y0 = int(max(0, cy - nh / 2))
    x1 = int(min(shape[1], cx + nw / 2))
    y1 = int(min(shape[0], cy + nh / 2))
    if x1 - x0 < 32 or y1 - y0 < 32:
        return rect
    return (x0, y0, x1 - x0, y1 - y0)


def compose(photo_bgr, canvas_size, crop_rect=None, padding=18):
    """Render `photo_bgr` into a styled canvas of `canvas_size`.

    crop_rect: optional (x, y, w, h) region to zoom into (None = whole photo).
    Returns (canvas, mapping) where mapping lets callers draw annotations in
    *canvas* coordinates so the text stays crisp at any zoom level.
    """
    cw, ch = max(120, int(canvas_size[0])), max(120, int(canvas_size[1]))
    canvas = _gradient_canvas(ch, cw)
    if photo_bgr is None:
        return canvas, None

    src = photo_bgr
    crop = (0, 0, photo_bgr.shape[1], photo_bgr.shape[0])
    if crop_rect is not None:
        x, y, w, h = [int(v) for v in crop_rect]
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(src.shape[1], x + w), min(src.shape[0], y + h)
        if x1 - x0 > 32 and y1 - y0 > 32:
            src = src[y0:y1, x0:x1]
            crop = (x0, y0, x1 - x0, y1 - y0)

    avail_w, avail_h = cw - 2 * padding, ch - 2 * padding
    tw, th = _fit_size(src.shape[1], src.shape[0], avail_w, avail_h)
    thumb = cv2.resize(src, (tw, th), interpolation=cv2.INTER_AREA)

    # ---- soft drop shadow ----
    shadow = np.zeros((ch, cw), np.float32)
    ox, oy = (cw - tw) // 2, (ch - th) // 2
    cv2.rectangle(shadow, (ox - 6, oy + 8), (ox + tw + 6, oy + th + 14), 1.0, -1)
    shadow = cv2.GaussianBlur(shadow, (0, 0), 12)
    shadow = np.clip(shadow[..., None] * 110.0, 0, 255)
    canvas = np.clip(canvas.astype(np.float32) * (1 - shadow / 255.0), 0, 255).astype(np.uint8)

    # ---- photo + 1px light border ----
    canvas[oy:oy + th, ox:ox + tw] = thumb
    cv2.rectangle(canvas, (ox - 1, oy - 1), (ox + tw, oy + th), (148, 163, 184), 1)
    mapping = {"ox": ox, "oy": oy, "tw": tw, "th": th,
               "scale": tw / float(max(crop[2], 1)), "crop": crop}
    return canvas, mapping


def _map_pts(pts, mapping):
    x0, y0 = mapping["crop"][0], mapping["crop"][1]
    s = mapping["scale"]
    return (np.asarray(pts, np.float64) - [x0, y0]) * s + [mapping["ox"], mapping["oy"]]


def overlay_annotations(canvas, result, mapping, show_masks=True):
    """Draw mask / contour / ellipse / centre / H0x labels in canvas space."""
    if canvas is None or mapping is None or not result:
        return canvas
    holes = result.get("holes") or []
    if not holes:
        return canvas

    ox, oy, tw, th = mapping["ox"], mapping["oy"], mapping["tw"], mapping["th"]
    cx0, cy0, cw0, ch0 = mapping["crop"]
    s = mapping["scale"]

    # ---- translucent mask fill ----
    if show_masks:
        overlay = canvas.copy()
        for h in holes:
            m = h.get("_mask")
            if m is None:
                continue
            sub = m[cy0:cy0 + ch0, cx0:cx0 + cw0]
            if sub.size == 0:
                continue
            sub = cv2.resize(sub.astype(np.uint8), (tw, th), interpolation=cv2.INTER_NEAREST)
            region = overlay[oy:oy + th, ox:ox + tw]
            region[sub > 0] = (60, 200, 60)
        canvas = cv2.addWeighted(overlay, 0.28, canvas, 0.72, 0)

    fs = float(np.clip(min(tw, th) / 900.0, 0.7, 1.6))
    thick = max(2, int(round(fs * 2.6)))

    for h in holes:
        cnt = h.get("_contour")
        if cnt is not None:
            cv2.polylines(canvas, [np.round(_map_pts(cnt.reshape(-1, 2), mapping)).astype(np.int32)],
                          True, (255, 255, 255), 2)
        e = h["ellipse"]
        c = _map_pts([e["center"]], mapping)[0]
        cv2.ellipse(canvas, (tuple(c), (e["width"] * s, e["height"] * s), e["angle"]),
                    (0, 255, 0), thick)
        cv2.circle(canvas, tuple(np.round(c).astype(int)), int(6 * fs), (0, 0, 255), -1)
        cv2.circle(canvas, tuple(np.round(c).astype(int)), int(9 * fs), (255, 255, 255), 2)

        label = "{}   {:.2f}".format(h["id"], h["confidence"])
        (lw, lh), base = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, fs, thick)
        tx = int(np.clip(c[0] + 14, ox + 2, ox + tw - lw - 10))
        ty = int(np.clip(c[1] - 16, oy + lh + 8, oy + th - 6))
        cv2.rectangle(canvas, (tx - 8, ty - lh - 8), (tx + lw + 8, ty + base + 4),
                      (17, 24, 39), -1)
        cv2.rectangle(canvas, (tx - 8, ty - lh - 8), (tx + lw + 8, ty + base + 4),
                      (56, 189, 248), 1)
        cv2.putText(canvas, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, fs,
                    (0, 0, 0), thick + 2, cv2.LINE_AA)
        cv2.putText(canvas, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, fs,
                    (0, 255, 255), max(1, thick - 2), cv2.LINE_AA)
    return canvas


def overlay_execution(canvas, result, mapping, state):
    """Draw the simulated robot run: planned path, finished holes, and the probe.

    state = {"active": True, "order": ["H01", ...], "done": ["H01"],
             "current": "H02", "probe": (x, y) or None}

    Text on the image stays ASCII because cv2.putText cannot render Chinese;
    all Chinese wording lives in the GUI panels / log instead.
    """
    if canvas is None or mapping is None or not result or not state or not state.get("active"):
        return canvas
    holes = {h["id"]: h for h in (result.get("holes") or [])}
    order = [t for t in state.get("order", []) if t in holes]
    if not order:
        return canvas

    fs = float(np.clip(min(mapping["tw"], mapping["th"]) / 900.0, 0.7, 1.6))

    # ---- planned path (cyan poly-line through the hole centres) ----
    pts = [_map_pts([holes[t]["ellipse"]["center"]], mapping)[0] for t in order]
    if len(pts) >= 2:
        cv2.polylines(canvas, [np.round(np.array(pts)).astype(np.int32)],
                      False, (255, 191, 0), max(2, int(fs * 3)))

    # ---- finished holes (ring only; the "H0x" labels are drawn later, on top) ----
    for hid in state.get("done", []):
        if hid not in holes:
            continue
        c = _map_pts([holes[hid]["ellipse"]["center"]], mapping)[0]
        r = int(max(holes[hid]["ellipse"]["major"], 40) * mapping["scale"] * 0.62)
        cv2.circle(canvas, tuple(np.round(c).astype(int)), r, (0, 200, 0), 4)
        cv2.drawMarker(canvas, tuple(np.round(c).astype(int)), (0, 200, 0),
                       cv2.MARKER_TILTED_CROSS, int(22 * fs) + 10, max(2, int(fs * 3)))

    # ---- current target ----
    cur = state.get("current")
    if cur in holes:
        c = _map_pts([holes[cur]["ellipse"]["center"]], mapping)[0]
        r = int(max(holes[cur]["ellipse"]["major"], 40) * mapping["scale"] * 0.70)
        cv2.circle(canvas, tuple(np.round(c).astype(int)), r, (0, 165, 255), 5)

    # ---- probe (simulated tool tip) ----
    probe = state.get("probe")
    if probe is not None:
        p = _map_pts([probe], mapping)[0]
        px, py = int(round(p[0])), int(round(p[1]))
        cv2.drawMarker(canvas, (px, py), (0, 140, 255), cv2.MARKER_CROSS,
                       int(46 * fs) + 20, max(2, int(fs * 3)))
        cv2.circle(canvas, (px, py), int(13 * fs) + 6, (0, 140, 255), -1)
        cv2.circle(canvas, (px, py), int(13 * fs) + 6, (255, 255, 255), 2)
        tx, ty = px + int(18 * fs), py + int(34 * fs)
        cv2.putText(canvas, "PROBE", (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, fs,
                    (0, 0, 0), int(fs * 5) + 2, cv2.LINE_AA)
        cv2.putText(canvas, "PROBE", (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, fs,
                    (0, 165, 255), max(1, int(fs * 2)), cv2.LINE_AA)

    # ---- HUD ----
    total = len(order)
    done = len(state.get("done", []))
    hud = "SIMULATED RUN  {}/{}   (no real robot connected)".format(done, total)
    cv2.putText(canvas, hud, (16, int(mapping["oy"] + mapping["th"] - 14)),
                cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 0, 0), int(fs * 5) + 2, cv2.LINE_AA)
    cv2.putText(canvas, hud, (16, int(mapping["oy"] + mapping["th"] - 14)),
                cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 165, 255), max(1, int(fs * 2)), cv2.LINE_AA)
    return canvas
