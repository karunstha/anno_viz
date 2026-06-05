import os
import stat
from pathlib import Path
import ast

from .geometry import clamp, normalize_xyxy, xyxy_to_yolo, yolo_to_xyxy


def _load_classes_from_data_yaml(classes_file):
    names = []
    raw_lines = classes_file.read_text().splitlines()

    for idx, raw in enumerate(raw_lines):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        if not line.startswith("names:"):
            continue

        remainder = line.split(":", 1)[1].strip()
        if remainder:
            try:
                parsed = ast.literal_eval(remainder)
            except (SyntaxError, ValueError):
                return []
            if isinstance(parsed, dict):
                return [str(name).strip() for _, name in sorted(parsed.items()) if str(name).strip()]
            if isinstance(parsed, (list, tuple)):
                return [str(name).strip() for name in parsed if str(name).strip()]
            return []

        block_names = []
        for nested_raw in raw_lines[idx + 1:]:
            if not nested_raw.strip():
                continue
            if not nested_raw.startswith((" ", "\t")):
                break
            nested = nested_raw.strip()
            if nested.startswith("- "):
                name = nested[2:].strip().strip("'\"")
                if name:
                    block_names.append(name)
                continue

            if ":" in nested:
                _, value = nested.split(":", 1)
                name = value.strip().strip("'\"")
                if name:
                    block_names.append(name)

        return block_names

    return names


def load_classes(classes_file):
    if classes_file is None or not classes_file.exists():
        return []

    if classes_file.suffix.lower() in {".yaml", ".yml"}:
        return _load_classes_from_data_yaml(classes_file)

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


def _case_mismatch_hint(path):
    try:
        siblings = path.parent.iterdir()
    except OSError:
        return ""

    wanted = path.name.lower()
    for sibling in siblings:
        if sibling.name.lower() == wanted and sibling.name != path.name:
            return f"Found similar path with different case: {sibling}"
    return ""


def _ensure_images_dir(images_dir):
    images_dir = Path(images_dir).expanduser()

    try:
        stat_result = images_dir.stat()
    except FileNotFoundError as exc:
        if images_dir.is_symlink():
            try:
                target = os.readlink(images_dir)
            except OSError:
                target = "<unreadable target>"
            raise RuntimeError(f"Images dir is a broken symlink: {images_dir} -> {target}") from exc

        message = f"Images dir not found: {images_dir}"
        hint = _case_mismatch_hint(images_dir)
        if hint:
            message = f"{message}. {hint}"
        raise RuntimeError(message) from exc
    except NotADirectoryError as exc:
        raise RuntimeError(f"Images dir path contains a non-directory component: {images_dir}") from exc
    except PermissionError as exc:
        raise RuntimeError(f"Cannot access images dir: {images_dir} ({exc.strerror})") from exc
    except OSError as exc:
        raise RuntimeError(f"Cannot access images dir: {images_dir} ({exc.strerror or exc})") from exc

    if not stat.S_ISDIR(stat_result.st_mode):
        mode = oct(stat_result.st_mode & 0o777)
        raise RuntimeError(f"Images path is not a directory: {images_dir} (mode {mode})")

    return images_dir


def collect_images(images_dir):
    images_dir = _ensure_images_dir(images_dir)
    exts = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
    try:
        return sorted(p for p in images_dir.iterdir() if p.suffix.lower() in exts)
    except PermissionError as exc:
        raise RuntimeError(f"Cannot read images dir: {images_dir} ({exc.strerror})") from exc
    except OSError as exc:
        raise RuntimeError(f"Cannot read images dir: {images_dir} ({exc.strerror or exc})") from exc


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
