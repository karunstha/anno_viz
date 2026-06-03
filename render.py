from dataclasses import dataclass

import cv2
import numpy as np

from geometry import handle_points, normalize_xyxy


ANNOTATION_COLOR = (0, 255, 255)

TOP_BAR_H = 44
BOTTOM_BAR_H = 108
TIMELINE_H = 60
TIMELINE_SLOT_W = 44
TIMELINE_GAP = 6
TIMELINE_PAD_X = 6
TIMELINE_PAD_Y = 8
TIMELINE_CANVAS_H = TIMELINE_H + 16


@dataclass
class UiRegion:
    name: str
    rect: tuple
    data: dict


@dataclass
class UiState:
    image_origin: tuple
    image_size: tuple
    source_image_size: tuple
    regions: list
    timeline_rect: tuple



def get_color(cls_id):
    return ANNOTATION_COLOR


def draw_text_with_bg(image, text, org, color, scale=0.55, thickness=1):
    font = cv2.FONT_HERSHEY_SIMPLEX
    x, y = org
    (tw, th), baseline = cv2.getTextSize(text, font, scale, thickness)
    cv2.rectangle(image, (x, y - th - baseline - 4), (x + tw + 6, y + baseline), (0, 0, 0), -1)
    cv2.putText(image, text, (x + 3, y - 3), font, scale, color, thickness, cv2.LINE_AA)


def draw_handles(image, x1, y1, x2, y2):
    points = handle_points(x1, y1, x2, y2)
    for px, py in points.values():
        cv2.rectangle(image, (px - 4, py - 4), (px + 4, py + 4), (255, 255, 255), -1)
        cv2.rectangle(image, (px - 4, py - 4), (px + 4, py + 4), (0, 0, 0), 1)


def draw_annotations(image, boxes, selected_idx, class_names, add_mode, dirty, class_label):
    for i, box in enumerate(boxes):
        cls_id = box["cls_id"]
        x1, y1, x2, y2 = normalize_xyxy(box["x1"], box["y1"], box["x2"], box["y2"])
        color = get_color(cls_id)
        thickness = 3 if i == selected_idx else 2

        cv2.rectangle(image, (x1, y1), (x2, y2), color, thickness)
        draw_text_with_bg(image, class_label(cls_id, class_names), (x1, max(20, y1 - 6)), color)

        if i == selected_idx:
            draw_handles(image, x1, y1, x2, y2)

    mode = "ADD" if add_mode else "EDIT"
    dirty_mark = " *unsaved" if dirty else ""
    draw_text_with_bg(
        image,
        f"Mode: {mode}{dirty_mark}",
        (12, image.shape[0] - 14),
        (255, 255, 255),
        scale=0.6,
        thickness=2,
    )
    return image


def _draw_button(canvas, rect, label, enabled=True):
    x1, y1, x2, y2 = rect
    bg = (50, 50, 50) if enabled else (30, 30, 30)
    fg = (240, 240, 240) if enabled else (120, 120, 120)
    cv2.rectangle(canvas, (x1, y1), (x2, y2), bg, -1)
    cv2.rectangle(canvas, (x1, y1), (x2, y2), (90, 90, 90), 1)

    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.5
    thickness = 1
    (tw, th), _ = cv2.getTextSize(label, font, scale, thickness)
    tx = x1 + max(6, (x2 - x1 - tw) // 2)
    ty = y2 - max(6, (y2 - y1 - th) // 2)
    cv2.putText(canvas, label, (tx, ty), font, scale, fg, thickness, cv2.LINE_AA)


def _is_point_in_rect(x, y, rect):
    x1, y1, x2, y2 = rect
    return x1 <= x <= x2 and y1 <= y <= y2


def default_canvas_size(image):
    img_h, img_w = image.shape[:2]
    return img_w, TOP_BAR_H + img_h + BOTTOM_BAR_H


def _fit_size(src_w, src_h, max_w, max_h):
    scale = min(max_w / src_w, max_h / src_h)
    display_w = max(1, int(round(src_w * scale)))
    display_h = max(1, int(round(src_h * scale)))
    return display_w, display_h


def _scale_boxes(boxes, scale_x, scale_y, display_w, display_h):
    scaled_boxes = []
    max_x = display_w - 1
    max_y = display_h - 1

    for box in boxes:
        scaled_box = box.copy()
        scaled_box["x1"] = max(0, min(max_x, int(round(box["x1"] * scale_x))))
        scaled_box["y1"] = max(0, min(max_y, int(round(box["y1"] * scale_y))))
        scaled_box["x2"] = max(0, min(max_x, int(round(box["x2"] * scale_x))))
        scaled_box["y2"] = max(0, min(max_y, int(round(box["y2"] * scale_y))))
        scaled_boxes.append(scaled_box)

    return scaled_boxes


def draw_ui(
    image,
    status_text,
    help_text,
    images,
    current_idx,
    pending_deletes,
    timeline_indices,
    timeline_thumbs,
    canvas_size=None,
    annotation_boxes=None,
    selected_idx=None,
    class_names=None,
    add_mode=False,
    dirty=False,
    class_label_func=None,
):
    img_h, img_w = image.shape[:2]
    if canvas_size is None:
        canvas_w, canvas_h = default_canvas_size(image)
    else:
        canvas_w, canvas_h = canvas_size
        canvas_w = max(64, int(canvas_w))
        canvas_h = max(TOP_BAR_H + BOTTOM_BAR_H + 16, int(canvas_h))

    canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
    canvas[:] = (24, 24, 24)

    image_area_h = max(1, canvas_h - TOP_BAR_H - BOTTOM_BAR_H)
    display_w, display_h = _fit_size(img_w, img_h, canvas_w, image_area_h)
    image_x = max(0, (canvas_w - display_w) // 2)
    image_y = TOP_BAR_H + max(0, (image_area_h - display_h) // 2)
    scaled_image = cv2.resize(image, (display_w, display_h), interpolation=cv2.INTER_LINEAR)

    if annotation_boxes is not None and class_names is not None and class_label_func is not None:
        scaled_boxes = _scale_boxes(
            annotation_boxes,
            display_w / img_w,
            display_h / img_h,
            display_w,
            display_h,
        )
        scaled_image = draw_annotations(
            scaled_image,
            scaled_boxes,
            selected_idx,
            class_names,
            add_mode,
            dirty,
            class_label_func,
        )

    canvas[image_y:image_y + display_h, image_x:image_x + display_w] = scaled_image

    regions = []

    cv2.rectangle(canvas, (0, 0), (canvas_w, TOP_BAR_H), (32, 32, 32), -1)
    cv2.rectangle(canvas, (0, TOP_BAR_H + image_area_h), (canvas_w, canvas_h), (28, 28, 28), -1)

    draw_text_with_bg(canvas, status_text, (12, 30), (255, 255, 255), scale=0.6, thickness=2)

    button_y1 = 8
    button_y2 = TOP_BAR_H - 8
    button_right = max(12, canvas_w - 12)
    apply_rect = (max(0, button_right - 108), button_y1, button_right, button_y2)
    rescan_rect = (max(0, apply_rect[0] - 100), button_y1, max(0, apply_rect[0] - 10), button_y2)

    if rescan_rect[2] > rescan_rect[0]:
        _draw_button(canvas, rescan_rect, "Rescan", enabled=True)
        regions.append(UiRegion("rescan", rescan_rect, {}))

    apply_enabled = len(pending_deletes) > 0
    _draw_button(canvas, apply_rect, "Apply Deletes", enabled=apply_enabled)
    regions.append(UiRegion("apply_deletes", apply_rect, {"enabled": apply_enabled}))

    hint_y = TOP_BAR_H + image_area_h + 22
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(canvas, help_text, (12, hint_y), font, 0.45, (200, 200, 200), 1, cv2.LINE_AA)

    timeline_y1 = canvas_h - TIMELINE_H - 8
    timeline_y2 = canvas_h - 8
    timeline_x1 = 12
    timeline_x2 = canvas_w - 12

    cv2.rectangle(canvas, (timeline_x1, timeline_y1), (timeline_x2, timeline_y2), (20, 20, 20), -1)
    cv2.rectangle(canvas, (timeline_x1, timeline_y1), (timeline_x2, timeline_y2), (60, 60, 60), 1)

    if timeline_indices:
        draw_x = timeline_x1 + TIMELINE_PAD_X
        draw_y1 = timeline_y1 + TIMELINE_PAD_Y
        draw_y2 = timeline_y2 - TIMELINE_PAD_Y
        slot_h = draw_y2 - draw_y1

        for idx, thumb in zip(timeline_indices, timeline_thumbs):
            slot_rect = (draw_x, draw_y1, draw_x + TIMELINE_SLOT_W, draw_y2)
            color = (80, 80, 80)
            if images[idx] in pending_deletes:
                color = (30, 30, 220)
            cv2.rectangle(canvas, (slot_rect[0], slot_rect[1]), (slot_rect[2], slot_rect[3]), color, -1)

            if thumb is not None:
                thumb_h, thumb_w = thumb.shape[:2]
                tx = slot_rect[0] + max(0, (TIMELINE_SLOT_W - thumb_w) // 2)
                ty = slot_rect[1] + max(0, (slot_h - thumb_h) // 2)
                canvas[ty:ty + thumb_h, tx:tx + thumb_w] = thumb

            if idx == current_idx:
                cv2.rectangle(
                    canvas,
                    (slot_rect[0] - 1, slot_rect[1] - 1),
                    (slot_rect[2] + 1, slot_rect[3] + 1),
                    (0, 200, 255),
                    2,
                )

            regions.append(UiRegion("timeline", slot_rect, {"index": idx}))

            draw_x += TIMELINE_SLOT_W + TIMELINE_GAP

    timeline_rect = (timeline_x1, timeline_y1, timeline_x2, timeline_y2)
    regions.append(UiRegion("timeline_bar", timeline_rect, {}))
    return canvas, UiState(
        (image_x, image_y),
        (display_w, display_h),
        (img_w, img_h),
        regions,
        timeline_rect,
    )


def draw_image_panel(
    image,
    canvas_size,
    annotation_boxes=None,
    selected_idx=None,
    class_names=None,
    add_mode=False,
    dirty=False,
    class_label_func=None,
):
    img_h, img_w = image.shape[:2]
    canvas_w, canvas_h = canvas_size
    canvas_w = max(64, int(canvas_w))
    canvas_h = max(64, int(canvas_h))

    canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
    canvas[:] = (24, 24, 24)

    display_w, display_h = _fit_size(img_w, img_h, canvas_w, canvas_h)
    image_x = max(0, (canvas_w - display_w) // 2)
    image_y = max(0, (canvas_h - display_h) // 2)
    scaled_image = cv2.resize(image, (display_w, display_h), interpolation=cv2.INTER_LINEAR)

    if annotation_boxes is not None and class_names is not None and class_label_func is not None:
        scaled_boxes = _scale_boxes(
            annotation_boxes,
            display_w / img_w,
            display_h / img_h,
            display_w,
            display_h,
        )
        scaled_image = draw_annotations(
            scaled_image,
            scaled_boxes,
            selected_idx,
            class_names,
            add_mode,
            dirty,
            class_label_func,
        )

    canvas[image_y:image_y + display_h, image_x:image_x + display_w] = scaled_image
    return canvas, UiState(
        (image_x, image_y),
        (display_w, display_h),
        (img_w, img_h),
        [],
        (-1, -1, -1, -1),
    )


def draw_timeline_panel(
    canvas_w,
    images,
    current_idx,
    pending_deletes,
    timeline_indices,
    timeline_thumbs,
):
    canvas_w = max(64, int(canvas_w))
    canvas = np.zeros((TIMELINE_CANVAS_H, canvas_w, 3), dtype=np.uint8)
    canvas[:] = (28, 28, 28)

    regions = []
    timeline_x1 = 12
    timeline_x2 = canvas_w - 12
    timeline_y1 = 8
    timeline_y2 = timeline_y1 + TIMELINE_H

    cv2.rectangle(canvas, (timeline_x1, timeline_y1), (timeline_x2, timeline_y2), (20, 20, 20), -1)
    cv2.rectangle(canvas, (timeline_x1, timeline_y1), (timeline_x2, timeline_y2), (60, 60, 60), 1)

    if timeline_indices:
        draw_x = timeline_x1 + TIMELINE_PAD_X
        draw_y1 = timeline_y1 + TIMELINE_PAD_Y
        draw_y2 = timeline_y2 - TIMELINE_PAD_Y
        slot_h = draw_y2 - draw_y1

        for idx, thumb in zip(timeline_indices, timeline_thumbs):
            slot_rect = (draw_x, draw_y1, draw_x + TIMELINE_SLOT_W, draw_y2)
            color = (80, 80, 80)
            if images[idx] in pending_deletes:
                color = (30, 30, 220)
            cv2.rectangle(canvas, (slot_rect[0], slot_rect[1]), (slot_rect[2], slot_rect[3]), color, -1)

            if thumb is not None:
                thumb_h, thumb_w = thumb.shape[:2]
                tx = slot_rect[0] + max(0, (TIMELINE_SLOT_W - thumb_w) // 2)
                ty = slot_rect[1] + max(0, (slot_h - thumb_h) // 2)
                canvas[ty:ty + thumb_h, tx:tx + thumb_w] = thumb

            if idx == current_idx:
                cv2.rectangle(
                    canvas,
                    (slot_rect[0] - 1, slot_rect[1] - 1),
                    (slot_rect[2] + 1, slot_rect[3] + 1),
                    (0, 200, 255),
                    2,
                )

            regions.append(UiRegion("timeline", slot_rect, {"index": idx}))
            draw_x += TIMELINE_SLOT_W + TIMELINE_GAP

    timeline_rect = (timeline_x1, timeline_y1, timeline_x2, timeline_y2)
    regions.append(UiRegion("timeline_bar", timeline_rect, {}))
    return canvas, UiState((0, 0), (0, 0), (0, 0), regions, timeline_rect)


def timeline_capacity(canvas_w):
    timeline_w = max(1, canvas_w - 24)
    usable = max(1, timeline_w - 2 * TIMELINE_PAD_X)
    return max(1, (usable + TIMELINE_GAP) // (TIMELINE_SLOT_W + TIMELINE_GAP))


def timeline_slot_size():
    slot_h = TIMELINE_H - 2 * TIMELINE_PAD_Y
    return TIMELINE_SLOT_W, slot_h


def hit_ui_region(ui_state, x, y):
    for region in ui_state.regions:
        if _is_point_in_rect(x, y, region.rect):
            return region
    return None
