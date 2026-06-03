import math


def clamp(value, lo, hi):
    return max(lo, min(value, hi))


def normalize_xyxy(x1, y1, x2, y2):
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def yolo_to_xyxy(xc, yc, w, h, img_w, img_h):
    x1 = int(round((xc - w / 2.0) * img_w))
    y1 = int(round((yc - h / 2.0) * img_h))
    x2 = int(round((xc + w / 2.0) * img_w))
    y2 = int(round((yc + h / 2.0) * img_h))

    x1 = clamp(x1, 0, img_w - 1)
    y1 = clamp(y1, 0, img_h - 1)
    x2 = clamp(x2, 0, img_w - 1)
    y2 = clamp(y2, 0, img_h - 1)
    return normalize_xyxy(x1, y1, x2, y2)


def xyxy_to_yolo(x1, y1, x2, y2, img_w, img_h):
    x1, y1, x2, y2 = normalize_xyxy(x1, y1, x2, y2)

    bw = (x2 - x1) / img_w
    bh = (y2 - y1) / img_h
    xc = ((x1 + x2) / 2.0) / img_w
    yc = ((y1 + y2) / 2.0) / img_h

    return (
        clamp(xc, 0.0, 1.0),
        clamp(yc, 0.0, 1.0),
        clamp(bw, 0.0, 1.0),
        clamp(bh, 0.0, 1.0),
    )


def handle_points(x1, y1, x2, y2):
    mx = (x1 + x2) // 2
    my = (y1 + y2) // 2
    return {
        "tl": (x1, y1),
        "t": (mx, y1),
        "tr": (x2, y1),
        "r": (x2, my),
        "br": (x2, y2),
        "b": (mx, y2),
        "bl": (x1, y2),
        "l": (x1, my),
    }


def nearest_handle(box, x, y, radius=10):
    x1, y1, x2, y2 = normalize_xyxy(box["x1"], box["y1"], box["x2"], box["y2"])
    best_name = None
    best_dist = radius + 1

    for name, (px, py) in handle_points(x1, y1, x2, y2).items():
        dist = math.hypot(px - x, py - y)
        if dist < best_dist:
            best_name = name
            best_dist = dist

    return best_name


def point_in_box(box, x, y):
    x1, y1, x2, y2 = normalize_xyxy(box["x1"], box["y1"], box["x2"], box["y2"])
    return x1 <= x <= x2 and y1 <= y <= y2


def hit_test(boxes, x, y):
    for i in range(len(boxes) - 1, -1, -1):
        if point_in_box(boxes[i], x, y):
            return i
    return None


def apply_resize(box, handle, x, y, img_w, img_h):
    x = clamp(x, 0, img_w - 1)
    y = clamp(y, 0, img_h - 1)

    if "l" in handle:
        box["x1"] = x
    if "r" in handle:
        box["x2"] = x
    if "t" in handle:
        box["y1"] = y
    if "b" in handle:
        box["y2"] = y

    box["x1"], box["y1"], box["x2"], box["y2"] = normalize_xyxy(
        box["x1"], box["y1"], box["x2"], box["y2"]
    )


def move_box(box, dx, dy, img_w, img_h):
    x1, y1, x2, y2 = normalize_xyxy(box["x1"], box["y1"], box["x2"], box["y2"])
    bw = x2 - x1
    bh = y2 - y1

    nx1 = clamp(x1 + dx, 0, img_w - 1 - bw)
    ny1 = clamp(y1 + dy, 0, img_h - 1 - bh)

    box["x1"] = nx1
    box["y1"] = ny1
    box["x2"] = nx1 + bw
    box["y2"] = ny1 + bh
