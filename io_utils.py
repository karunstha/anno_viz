from pathlib import Path

from geometry import clamp, normalize_xyxy, xyxy_to_yolo, yolo_to_xyxy


def load_classes(classes_file):
    if classes_file is None or not classes_file.exists():
        return []

    names = []
    for raw in classes_file.read_text().splitlines():
        name = raw.strip()
        if name:
            names.append(name)
    return names


def class_label(cls_id, class_names):
    if 0 <= cls_id < len(class_names):
        return f"{cls_id}: {class_names[cls_id]}"
    return f"class {cls_id}"


def parse_yolo_label(label_path, img_w, img_h):
    boxes = []
    if not label_path.exists():
        return boxes

    for line_no, raw in enumerate(label_path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue

        parts = line.split()
        if len(parts) != 5:
            print(f"[warn] Skipping invalid label line {label_path}:{line_no}: {line}")
            continue

        try:
            cls_id = int(float(parts[0]))
            xc = float(parts[1])
            yc = float(parts[2])
            bw = float(parts[3])
            bh = float(parts[4])
        except ValueError:
            print(f"[warn] Skipping invalid label line {label_path}:{line_no}: {line}")
            continue

        x1, y1, x2, y2 = yolo_to_xyxy(xc, yc, bw, bh, img_w, img_h)
        if x2 - x1 >= 2 and y2 - y1 >= 2:
            boxes.append({"cls_id": cls_id, "x1": x1, "y1": y1, "x2": x2, "y2": y2})

    return boxes


def save_yolo_label(label_path, boxes, img_w, img_h):
    label_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    for box in boxes:
        x1, y1, x2, y2 = normalize_xyxy(box["x1"], box["y1"], box["x2"], box["y2"])
        if x2 - x1 < 2 or y2 - y1 < 2:
            continue

        xc, yc, bw, bh = xyxy_to_yolo(x1, y1, x2, y2, img_w, img_h)
        lines.append(f'{box["cls_id"]} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}')

    label_path.write_text("\n".join(lines) + ("\n" if lines else ""))
    print(f"saved label: {label_path} ({len(lines)} boxes)")


def collect_images(images_dir):
    if not images_dir.exists():
        raise RuntimeError(f"Images dir not found: {images_dir}")
    exts = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
    return sorted(p for p in images_dir.iterdir() if p.suffix.lower() in exts)


def refresh_images(images_dir, current_path, fallback_idx=0):
    images = collect_images(images_dir)
    if not images:
        return images, 0

    if current_path is not None:
        try:
            idx = images.index(current_path)
        except ValueError:
            idx = min(fallback_idx, len(images) - 1)
    else:
        idx = min(fallback_idx, len(images) - 1)

    return images, idx
