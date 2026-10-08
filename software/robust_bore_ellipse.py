import cv2
import numpy as np

def sample_boundary(points, count=240):
    p = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    p = p[np.r_[True, np.linalg.norm(np.diff(p, axis=0), axis=1) > 1e-5]]
    if len(p) < 5:
        raise ValueError('有效轮廓点不足五个')
    closed = np.vstack([p, p[0]])
    lengths = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    cumulative = np.r_[0, np.cumsum(lengths)]
    if cumulative[-1] <= 0:
        raise ValueError('轮廓退化')
    targets = np.linspace(0, cumulative[-1], count, endpoint=False)
    return np.column_stack([np.interp(targets, cumulative, closed[:, k]) for k in (0, 1)]).astype(np.float32)

def ellipse_residual(points, ellipse):
    (cx, cy), (width, height), angle = ellipse
    rx, ry = width / 2, height / 2
    radians = np.deg2rad(angle)
    cosine, sine = np.cos(radians), np.sin(radians)
    delta = points - [cx, cy]
    u = cosine * delta[:, 0] + sine * delta[:, 1]
    v = -sine * delta[:, 0] + cosine * delta[:, 1]
    q = np.sqrt((u / rx) ** 2 + (v / ry) ** 2)
    gradient = np.sqrt((u / rx**2) ** 2 + (v / ry**2) ** 2) / np.maximum(q, 1e-6)
    distance = np.abs(q - 1) / np.maximum(gradient, 1e-6)
    theta = np.arctan2(v / ry, u / rx)
    return distance, theta

def robust_bore_ellipse(points, min_support=0.70, min_coverage=0.70):
    samples = sample_boundary(points)
    low, high = samples.min(axis=0), samples.max(axis=0)
    extent = high - low
    contour_area = abs(cv2.contourArea(np.asarray(points, dtype=np.float32)))
    tolerance = max(2.0, 0.02 * float(min(extent)))
    rng = np.random.default_rng(42)

    def valid(ellipse):
        (cx, cy), (width, height), angle = ellipse
        if not np.isfinite([cx, cy, width, height, angle]).all() or min(width, height) <= 0:
            return False
        if max(width, height) / min(width, height) > 12:
            return False
        if not np.all(np.array([cx, cy]) >= low - 0.1 * extent) or not np.all(np.array([cx, cy]) <= high + 0.1 * extent):
            return False
        ratio = np.pi * width * height / 4 / max(contour_area, 1)
        return 0.55 <= ratio <= 1.8

    best = None
    best_score = (-1, -np.inf)
    for iteration in range(401):
        selected = samples if iteration == 0 else samples[rng.choice(len(samples), 8, replace=False)]
        try:
            candidate = cv2.fitEllipseDirect(selected.reshape(-1, 1, 2))
        except cv2.error:
            continue
        if not valid(candidate):
            continue
        residual, _ = ellipse_residual(samples, candidate)
        score = (int(np.sum(residual <= tolerance)), -float(np.median(residual)))
        if score > best_score:
            best, best_score = candidate, score
    if best is None:
        raise ValueError('未找到合理的椭圆')
    for _ in range(3):
        residual, _ = ellipse_residual(samples, best)
        inliers = residual <= tolerance
        if np.sum(inliers) < 5:
            break
        candidate = cv2.fitEllipseDirect(samples[inliers].reshape(-1, 1, 2))
        if not valid(candidate):
            break
        best = candidate
    residual, angles = ellipse_residual(samples, best)
    inliers = residual <= tolerance
    support = float(np.mean(inliers))
    bins = np.floor((angles[inliers] + np.pi) / (2 * np.pi) * 24).astype(int) % 24
    coverage = len(np.unique(bins)) / 24
    if support < min_support or coverage < min_coverage:
        raise ValueError(f'轮廓不够支持椭圆：支持比例 {support:.0%}，角度覆盖 {coverage:.0%}')
    return best, samples, inliers, float(np.median(residual[inliers])), support
