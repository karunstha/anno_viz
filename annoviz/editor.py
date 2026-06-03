from collections import OrderedDict

import cv2

from .geometry import apply_resize, clamp, hit_test, move_box, nearest_handle, normalize_xyxy
from .io_utils import class_label, load_classes, parse_yolo_label, refresh_images, save_yolo_label
from .render import (
    TIMELINE_CANVAS_H,
    TOP_BAR_H,
    default_canvas_size,
    draw_annotations,
    draw_image_panel,
    draw_timeline_panel,
    draw_ui,
    hit_ui_region,
    timeline_capacity,
    timeline_slot_size,
)


WINDOW_NAME = "Annotation Editor"


class AnnotationEditor:
    def __init__(self, images_dir, labels_dir, classes_file=None, save_dir=None, start_index=0):
        self.images_dir = images_dir
        self.labels_dir = labels_dir
        self.classes_file = classes_file
        self.save_dir = save_dir
        self.start_index = start_index

        self.class_names = load_classes(classes_file)
        self.selected_class = 0
        self.add_mode = False

        self.images = []
        self.idx = 0
        self.current_path = None
        self.img_path = None
        self.label_path = None
        self.image = None
        self.boxes = []
        self.selected_idx = None
        self.dirty = False

        self.dragging = False
        self.drag_action = None
        self.drag_handle = None
        self.drag_start = None
        self.drag_original_box = None
        self.new_box_idx = None

        self.pending_deletes = set()
        self.ui_state = None
        self.timeline_ui_state = None
        self.timeline_start = 0
        self.thumb_cache = OrderedDict()
        self.canvas_size = None
        self.timeline_canvas_w = None

    def load_initial(self):
        self.images = self._collect_images()
        if not self.images:
            raise RuntimeError(f"No images found in: {self.images_dir}")

        if self.save_dir is not None:
            self.save_dir.mkdir(parents=True, exist_ok=True)

        self.idx = max(0, min(self.start_index, len(self.images) - 1))
        self.current_path = self.images[self.idx]
        self.load_current_image()

    def _collect_images(self):
        self.images, self.idx = refresh_images(self.images_dir, self.current_path, self.idx)
        return self.images

    def load_current_image(self):
        self.images, self.idx = refresh_images(self.images_dir, self.current_path, self.idx)
        if not self.images:
            raise RuntimeError(f"No images found in: {self.images_dir}")

        self.img_path = self.images[self.idx]
        self.current_path = self.img_path
        self.label_path = self.labels_dir / f"{self.img_path.stem}.txt"

        image = cv2.imread(str(self.img_path))
        if image is None:
            raise RuntimeError(f"Could not read image: {self.img_path}")

        self.image = image
        h, w = image.shape[:2]
        self.boxes = parse_yolo_label(self.label_path, w, h)
        self.selected_idx = 0 if self.boxes else None
        self.dirty = False
        self.dragging = False
        self._ensure_timeline_visible()

    def rescan_images(self):
        self.images, self.idx = refresh_images(self.images_dir, self.current_path, self.idx)
        self.pending_deletes = {p for p in self.pending_deletes if p in self.images}
        self.load_current_image()

    def save_labels(self):
        h, w = self.image.shape[:2]
        save_yolo_label(self.label_path, self.boxes, w, h)
        self.dirty = False

    def mark_current_for_deletion(self):
        if self.img_path is None:
            return
        self.pending_deletes.add(self.img_path)

    def undo_pending_delete(self, image_path):
        if image_path in self.pending_deletes:
            self.pending_deletes.remove(image_path)

    def apply_pending_deletes(self):
        if not self.pending_deletes:
            return
        for img_path in list(self.pending_deletes):
            label_path = self.labels_dir / f"{img_path.stem}.txt"
            try:
                img_path.unlink()
                print(f"deleted image: {img_path}")
            except FileNotFoundError:
                print(f"image already missing: {img_path}")

            try:
                label_path.unlink()
                print(f"deleted label: {label_path}")
            except FileNotFoundError:
                print(f"label not found: {label_path}")

        self.pending_deletes.clear()
        self.images, self.idx = refresh_images(self.images_dir, None, self.idx)
        if not self.images:
            raise RuntimeError("No images left.")

        self.idx = min(self.idx, len(self.images) - 1)
        self.current_path = self.images[self.idx]
        self.load_current_image()

    def save_visualized_image(self):
        if self.save_dir is None:
            print("save_dir not set; use --save-dir to enable saving rendered images")
            return

        out_path = self.save_dir / self.img_path.name
        vis = self._render_image()
        cv2.imwrite(str(out_path), vis)
        print(f"saved rendered image: {out_path}")

    def select_next_box(self):
        if not self.boxes:
            self.selected_idx = None
            return
        if self.selected_idx is None:
            self.selected_idx = 0
        else:
            self.selected_idx = (self.selected_idx + 1) % len(self.boxes)

    def set_selected_class(self, cls_id):
        max_class = max(len(self.class_names) - 1, cls_id, 0)
        cls_id = clamp(cls_id, 0, max_class)
        self.selected_class = cls_id

        if self.selected_idx is not None and 0 <= self.selected_idx < len(self.boxes):
            self.boxes[self.selected_idx]["cls_id"] = cls_id
            self.dirty = True

    def cycle_class(self, delta):
        class_count = len(self.class_names)
        if class_count <= 0:
            class_count = max([b["cls_id"] for b in self.boxes], default=0) + 2

        new_cls = (self.selected_class + delta) % class_count
        self.set_selected_class(new_cls)

    def remove_selected_box(self):
        if self.selected_idx is None or not (0 <= self.selected_idx < len(self.boxes)):
            return

        removed = self.boxes.pop(self.selected_idx)
        print(f"removed box: {removed}")
        if not self.boxes:
            self.selected_idx = None
        else:
            self.selected_idx = min(self.selected_idx, len(self.boxes) - 1)
        self.dirty = True

    def _map_to_image(self, x, y):
        if self.ui_state is None:
            return None
        ox, oy = self.ui_state.image_origin
        display_w, display_h = self.ui_state.image_size
        source_w, source_h = self.ui_state.source_image_size
        if ox <= x < ox + display_w and oy <= y < oy + display_h:
            ix = int((x - ox) * source_w / display_w)
            iy = int((y - oy) * source_h / display_h)
            return (
                clamp(ix, 0, source_w - 1),
                clamp(iy, 0, source_h - 1),
            )
        return None

    def _handle_ui_click(self, x, y):
        if self.ui_state is None:
            return False
        region = hit_ui_region(self.ui_state, x, y)
        if region is None:
            return False

        if region.name == "rescan":
            self.rescan_images()
            return True

        if region.name == "apply_deletes":
            if region.data.get("enabled"):
                try:
                    self.apply_pending_deletes()
                except RuntimeError as exc:
                    print(exc)
            return True

        if region.name == "timeline":
            image_path = self.images[region.data["index"]]
            if image_path in self.pending_deletes:
                self.undo_pending_delete(image_path)
                return True

            self.current_path = image_path
            self.load_current_image()
            return True

        return False

    def _timeline_canvas_w(self):
        if self.timeline_canvas_w is not None:
            return self.timeline_canvas_w
        if self.canvas_size is not None:
            return self.canvas_size[0]
        if self.image is not None:
            return self.image.shape[1]
        return 1

    def _ensure_timeline_visible(self, canvas_w=None):
        if not self.images:
            self.timeline_start = 0
            return
        capacity = timeline_capacity(canvas_w or self._timeline_canvas_w())
        max_start = max(0, len(self.images) - capacity)
        if self.idx < self.timeline_start:
            self.timeline_start = self.idx
        elif self.idx >= self.timeline_start + capacity:
            self.timeline_start = self.idx - capacity + 1
        self.timeline_start = clamp(self.timeline_start, 0, max_start)

    def _timeline_indices(self, canvas_w=None):
        if not self.images:
            return []
        capacity = timeline_capacity(canvas_w or self._timeline_canvas_w())
        max_start = max(0, len(self.images) - capacity)
        self.timeline_start = clamp(self.timeline_start, 0, max_start)
        end = min(len(self.images), self.timeline_start + capacity)
        return list(range(self.timeline_start, end))

    def _timeline_thumbs(self, indices):
        if not indices:
            return []
        slot_w, slot_h = timeline_slot_size()
        thumb_w = max(8, slot_w - 4)
        thumb_h = max(8, slot_h - 4)
        visible_set = set(indices)

        for idx in indices:
            if idx in self.thumb_cache:
                self.thumb_cache.move_to_end(idx)
                continue
            path = self.images[idx]
            thumb = None
            raw = cv2.imread(str(path))
            if raw is not None:
                thumb = cv2.resize(raw, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)
            self.thumb_cache[idx] = thumb

        for idx in list(self.thumb_cache.keys()):
            if idx not in visible_set:
                self.thumb_cache.pop(idx, None)

        return [self.thumb_cache.get(idx) for idx in indices]

    def _is_over_timeline(self, x, y):
        if self.ui_state is None:
            return False
        x1, y1, x2, y2 = self.ui_state.timeline_rect
        return x1 <= x <= x2 and y1 <= y <= y2

    def _window_canvas_size(self):
        fallback = self.canvas_size
        if fallback is None and self.image is not None:
            fallback = default_canvas_size(self.image)

        if hasattr(cv2, "getWindowImageRect"):
            try:
                _, _, window_w, window_h = cv2.getWindowImageRect(WINDOW_NAME)
                if window_w > 0 and window_h > 0:
                    return window_w, window_h
            except cv2.error:
                pass

        return fallback

    def _sync_canvas_size_from_window(self):
        window_size = self._window_canvas_size()
        if window_size is None:
            return False
        window_size = (max(1, int(window_size[0])), max(1, int(window_size[1])))
        if window_size == self.canvas_size:
            return False
        self.canvas_size = window_size
        return True

    def on_mouse(self, event, x, y, flags, param):
        img_point = self._map_to_image(x, y)

        if event == cv2.EVENT_MOUSEWHEEL:
            if self._is_over_timeline(x, y):
                delta = (flags >> 16) & 0xFFFF
                if delta > 32767:
                    delta -= 65536
                step = -1 if delta > 0 else 1
                self.timeline_start += step * 3
                self._ensure_timeline_visible()
            return

        if event == cv2.EVENT_LBUTTONDOWN:
            if self._handle_ui_click(x, y):
                return
            if img_point is None:
                return

            ix, iy = img_point
            self.dragging = True
            self.drag_start = (ix, iy)

            if self.add_mode:
                self.boxes.append({
                    "cls_id": self.selected_class,
                    "x1": ix,
                    "y1": iy,
                    "x2": ix,
                    "y2": iy,
                })
                self.selected_idx = len(self.boxes) - 1
                self.new_box_idx = self.selected_idx
                self.drag_action = "new"
                self.dirty = True
                return

            hit_idx = hit_test(self.boxes, ix, iy)
            self.selected_idx = hit_idx

            if hit_idx is None:
                self.drag_action = None
                return

            box = self.boxes[hit_idx]
            self.selected_class = box["cls_id"]
            handle = nearest_handle(box, ix, iy)

            if handle is not None:
                self.drag_action = "resize"
                self.drag_handle = handle
            else:
                self.drag_action = "move"

            self.drag_original_box = box.copy()
            return

        if event == cv2.EVENT_MOUSEMOVE and self.dragging:
            if self.selected_idx is None or not (0 <= self.selected_idx < len(self.boxes)):
                return
            if img_point is None:
                return

            ix, iy = img_point
            box = self.boxes[self.selected_idx]

            if self.drag_action == "new":
                sx, sy = self.drag_start
                box["x1"], box["y1"], box["x2"], box["y2"] = normalize_xyxy(
                    clamp(sx, 0, self.image.shape[1] - 1),
                    clamp(sy, 0, self.image.shape[0] - 1),
                    clamp(ix, 0, self.image.shape[1] - 1),
                    clamp(iy, 0, self.image.shape[0] - 1),
                )
                self.dirty = True
                return

            if self.drag_action == "resize":
                apply_resize(box, self.drag_handle, ix, iy, self.image.shape[1], self.image.shape[0])
                self.dirty = True
                return

            if self.drag_action == "move":
                sx, sy = self.drag_start
                dx = ix - sx
                dy = iy - sy
                original = self.drag_original_box.copy()
                box.update(original)
                move_box(box, dx, dy, self.image.shape[1], self.image.shape[0])
                self.dirty = True
                return

        if event == cv2.EVENT_LBUTTONUP:
            if self.drag_action == "new" and self.selected_idx is not None:
                box = self.boxes[self.selected_idx]
                x1, y1, x2, y2 = normalize_xyxy(box["x1"], box["y1"], box["x2"], box["y2"])
                if x2 - x1 < 5 or y2 - y1 < 5:
                    self.boxes.pop(self.selected_idx)
                    self.selected_idx = None if not self.boxes else len(self.boxes) - 1
                    print("ignored tiny box")
                else:
                    box["x1"], box["y1"], box["x2"], box["y2"] = x1, y1, x2, y2
                    self.dirty = True

            self.dragging = False
            self.drag_action = None
            self.drag_handle = None
            self.drag_original_box = None
            self.new_box_idx = None

    def render(self):
        canvas_size = self.canvas_size or default_canvas_size(self.image)
        self._ensure_timeline_visible(canvas_size[0])
        timeline_indices = self._timeline_indices(canvas_size[0])
        timeline_thumbs = self._timeline_thumbs(timeline_indices)

        canvas, ui_state = draw_ui(
            self.image,
            status_text=self._status_text(),
            help_text=self._help_text(),
            images=self.images,
            current_idx=self.idx,
            pending_deletes=self.pending_deletes,
            timeline_indices=timeline_indices,
            timeline_thumbs=timeline_thumbs,
            canvas_size=canvas_size,
            annotation_boxes=self.boxes,
            selected_idx=self.selected_idx,
            class_names=self.class_names,
            add_mode=self.add_mode,
            dirty=self.dirty,
            class_label_func=class_label,
        )
        self.ui_state = ui_state
        self.canvas_size = (canvas.shape[1], canvas.shape[0])
        return canvas, ui_state

    def _status_text(self):
        selected = "none"
        if self.selected_idx is not None and 0 <= self.selected_idx < len(self.boxes):
            selected = class_label(self.boxes[self.selected_idx]["cls_id"], self.class_names)

        selected_class = class_label(self.selected_class, self.class_names)
        delete_mark = " | pending delete" if self.img_path in self.pending_deletes else ""
        return (
            f"{self.idx + 1}/{len(self.images)} | {self.img_path.name} | "
            f"boxes={len(self.boxes)} | selected={selected} | add-class={selected_class}{delete_mark}"
        )

    def _help_text(self):
        return (
            "n/Right next | b/Left prev | a add mode | drag box move/resize | "
            "Tab select | +/- class | 0-9 set class | Del remove box | s save labels | p save image | d mark delete | q quit"
        )

    def _render_image(self):
        vis = self.image.copy()
        return draw_annotations(
            vis,
            self.boxes,
            self.selected_idx,
            self.class_names,
            self.add_mode,
            self.dirty,
            class_label,
        )

    def next_image(self, step=1):
        self.images, self.idx = refresh_images(self.images_dir, self.current_path, self.idx)
        if not self.images:
            return
        self.idx = (self.idx + step) % len(self.images)
        self.current_path = self.images[self.idx]
        self.load_current_image()

    def _print_controls(self):
        print(
            "Controls:\n"
            "  n / Right Arrow  : next image\n"
            "  b / Left Arrow   : previous image\n"
            "  c                : back 5 images\n"
            "  v                : forward 2 images\n"
            "  x                : back 10 images\n"
            "  a                : toggle add-annotation mode\n"
            "  mouse drag box   : move box\n"
            "  mouse drag handle: resize/reshape box\n"
            "  Tab              : select next box\n"
            "  + / -            : change selected/add class\n"
            "  0-9              : set selected/add class id\n"
            "  Delete/Backspace : remove selected box\n"
            "  s                : save YOLO label file\n"
            "  p                : save rendered preview image if --save-dir is set\n"
            "  d                : mark current image for deletion\n"
            "  q / Esc          : quit\n"
        )

    def _handle_key(self, key=None, char="", keysym=""):
        if key in (ord("q"), 27) or char == "q" or keysym == "Escape":
            return True

        if key in (ord("n"), 2555904, 83) or char == "n" or keysym == "Right":
            self.next_image(1)
            return False

        if key in (ord("b"), 2424832, 81) or char == "b" or keysym == "Left":
            self.next_image(-1)
            return False

        if key == ord("c") or char == "c":
            self.next_image(-5)
            return False

        if key == ord("v") or char == "v":
            self.next_image(2)
            return False

        if key == ord("x") or char == "x":
            self.next_image(-10)
            return False

        if key == ord("a") or char == "a":
            self.add_mode = not self.add_mode
            print(f"add mode: {self.add_mode}")
            return False

        if key == 9 or keysym == "Tab":
            self.select_next_box()
            return False

        if key in (ord("+"), ord("=")) or char in {"+", "="}:
            self.cycle_class(1)
            return False

        if key in (ord("-"), ord("_")) or char in {"-", "_"}:
            self.cycle_class(-1)
            return False

        if key is not None and ord("0") <= key <= ord("9"):
            self.set_selected_class(key - ord("0"))
            return False
        if len(char) == 1 and char.isdigit():
            self.set_selected_class(int(char))
            return False

        if key in (8, 127, 3014656) or keysym in {"BackSpace", "Delete"}:
            self.remove_selected_box()
            return False

        if key == ord("s") or char == "s":
            self.save_labels()
            return False

        if key == ord("p") or char == "p":
            self.save_visualized_image()
            return False

        if key == ord("d") or char == "d":
            self.mark_current_for_deletion()
            return False

        return False

    def _run_tk_window(self, tk):
        import base64

        root = tk.Tk()
        root.title(WINDOW_NAME)

        initial_w, initial_h = default_canvas_size(self.image)
        root.geometry(f"{initial_w}x{initial_h}")
        root.minsize(420, TOP_BAR_H + TIMELINE_CANVAS_H + 120)

        top_frame = tk.Frame(root, height=TOP_BAR_H, bg="#202020")
        top_frame.pack(side=tk.TOP, fill=tk.X)
        top_frame.pack_propagate(False)

        status_var = tk.StringVar(value=self._status_text())
        status_label = tk.Label(
            top_frame,
            textvariable=status_var,
            anchor=tk.W,
            bg="#202020",
            fg="#f0f0f0",
            padx=12,
            width=1,
        )
        status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        rescan_button = tk.Button(top_frame, text="Rescan", width=9, command=lambda: handle_rescan())
        rescan_button.pack(side=tk.LEFT, padx=(6, 4), pady=7)

        apply_button = tk.Button(top_frame, text="Apply Deletes", width=13, command=lambda: handle_apply_deletes())
        apply_button.pack(side=tk.LEFT, padx=(4, 12), pady=7)

        bottom_frame = tk.Frame(root, bg="#1c1c1c")
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X)

        help_label = tk.Label(
            bottom_frame,
            text=self._help_text(),
            anchor=tk.W,
            bg="#1c1c1c",
            fg="#c8c8c8",
            padx=12,
            pady=5,
            width=1,
        )
        help_label.pack(side=tk.TOP, fill=tk.X)

        timeline_canvas = tk.Canvas(
            bottom_frame,
            height=TIMELINE_CANVAS_H,
            bg="#1c1c1c",
            highlightthickness=0,
            bd=0,
        )
        timeline_canvas.pack(side=tk.TOP, fill=tk.X)

        image_canvas = tk.Canvas(root, bg="#181818", highlightthickness=0, bd=0)
        image_canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        image_canvas.focus_set()

        tk_state = {
            "image_id": None,
            "image_photo": None,
            "timeline_id": None,
            "timeline_photo": None,
            "rendering_image": False,
            "rendering_timeline": False,
        }

        def bgr_photo(image):
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            img_h, img_w = rgb.shape[:2]
            header = f"P6\n{img_w} {img_h}\n255\n".encode("ascii")
            data = base64.b64encode(header + rgb.tobytes()).decode("ascii")
            return tk.PhotoImage(data=data, format="PPM")

        def render_image_canvas():
            if tk_state["rendering_image"]:
                return
            tk_state["rendering_image"] = True
            try:
                width = max(1, image_canvas.winfo_width())
                height = max(1, image_canvas.winfo_height())
                self.canvas_size = (width, height)

                rendered, image_state = draw_image_panel(
                    self.image,
                    (width, height),
                    annotation_boxes=self.boxes,
                    selected_idx=self.selected_idx,
                    class_names=self.class_names,
                    add_mode=self.add_mode,
                    dirty=self.dirty,
                    class_label_func=class_label,
                )
                self.ui_state = image_state
                photo = bgr_photo(rendered)

                if tk_state["image_id"] is None:
                    tk_state["image_id"] = image_canvas.create_image(0, 0, anchor=tk.NW, image=photo)
                else:
                    image_canvas.itemconfigure(tk_state["image_id"], image=photo)

                tk_state["image_photo"] = photo
            finally:
                tk_state["rendering_image"] = False

        def render_timeline_canvas():
            if tk_state["rendering_timeline"]:
                return
            tk_state["rendering_timeline"] = True
            try:
                width = max(1, timeline_canvas.winfo_width())
                self.timeline_canvas_w = width
                self._ensure_timeline_visible(width)
                timeline_indices = self._timeline_indices(width)
                timeline_thumbs = self._timeline_thumbs(timeline_indices)
                rendered, timeline_state = draw_timeline_panel(
                    width,
                    self.images,
                    self.idx,
                    self.pending_deletes,
                    timeline_indices,
                    timeline_thumbs,
                )
                self.timeline_ui_state = timeline_state
                photo = bgr_photo(rendered)

                if tk_state["timeline_id"] is None:
                    tk_state["timeline_id"] = timeline_canvas.create_image(0, 0, anchor=tk.NW, image=photo)
                else:
                    timeline_canvas.itemconfigure(tk_state["timeline_id"], image=photo)

                tk_state["timeline_photo"] = photo
            finally:
                tk_state["rendering_timeline"] = False

        def refresh_top():
            status_var.set(self._status_text())
            apply_button.configure(state=tk.NORMAL if self.pending_deletes else tk.DISABLED)

        def refresh_all():
            refresh_top()
            render_image_canvas()
            render_timeline_canvas()
            image_canvas.focus_set()

        def handle_rescan():
            self.rescan_images()
            refresh_all()

        def handle_apply_deletes():
            if self.pending_deletes:
                try:
                    self.apply_pending_deletes()
                except RuntimeError as exc:
                    print(exc)
            refresh_all()

        def handle_image_configure(event):
            if event.width <= 1 or event.height <= 1:
                return
            self.canvas_size = (event.width, event.height)
            render_image_canvas()

        def handle_timeline_configure(event):
            if event.width <= 1:
                return
            self.timeline_canvas_w = event.width
            render_timeline_canvas()

        def handle_image_mouse(event, cv_event, flags=0):
            self.on_mouse(cv_event, event.x, event.y, flags, None)
            refresh_all()

        def handle_image_mouse_wheel(event):
            delta = getattr(event, "delta", 0)
            flags = (int(delta) & 0xFFFF) << 16
            handle_image_mouse(event, cv2.EVENT_MOUSEWHEEL, flags)

        def handle_image_mouse_wheel_button(event, delta):
            flags = (delta & 0xFFFF) << 16
            handle_image_mouse(event, cv2.EVENT_MOUSEWHEEL, flags)

        def handle_timeline_click(event):
            if self.timeline_ui_state is None:
                return
            region = hit_ui_region(self.timeline_ui_state, event.x, event.y)
            if region is None or region.name != "timeline":
                return

            image_path = self.images[region.data["index"]]
            if image_path in self.pending_deletes:
                self.undo_pending_delete(image_path)
            else:
                self.current_path = image_path
                self.load_current_image()
            refresh_all()

        def handle_timeline_wheel_delta(delta):
            step = -1 if delta > 0 else 1
            self.timeline_start += step * 3
            self._ensure_timeline_visible(self.timeline_canvas_w)
            render_timeline_canvas()

        def handle_timeline_mouse_wheel(event):
            handle_timeline_wheel_delta(getattr(event, "delta", 0))

        def handle_timeline_mouse_wheel_button(delta):
            handle_timeline_wheel_delta(delta)

        def handle_key(event):
            should_quit = self._handle_key(char=event.char, keysym=event.keysym)
            if should_quit:
                root.destroy()
                return "break"
            refresh_all()
            return "break"

        image_canvas.bind("<Configure>", handle_image_configure)
        image_canvas.bind("<ButtonPress-1>", lambda event: handle_image_mouse(event, cv2.EVENT_LBUTTONDOWN))
        image_canvas.bind("<B1-Motion>", lambda event: handle_image_mouse(event, cv2.EVENT_MOUSEMOVE))
        image_canvas.bind("<ButtonRelease-1>", lambda event: handle_image_mouse(event, cv2.EVENT_LBUTTONUP))
        image_canvas.bind("<MouseWheel>", handle_image_mouse_wheel)
        image_canvas.bind("<Button-4>", lambda event: handle_image_mouse_wheel_button(event, 120))
        image_canvas.bind("<Button-5>", lambda event: handle_image_mouse_wheel_button(event, -120))

        timeline_canvas.bind("<Configure>", handle_timeline_configure)
        timeline_canvas.bind("<ButtonPress-1>", handle_timeline_click)
        timeline_canvas.bind("<MouseWheel>", handle_timeline_mouse_wheel)
        timeline_canvas.bind("<Button-4>", lambda event: handle_timeline_mouse_wheel_button(120))
        timeline_canvas.bind("<Button-5>", lambda event: handle_timeline_mouse_wheel_button(-120))
        root.bind("<Key>", handle_key)

        root.update_idletasks()
        refresh_all()
        root.mainloop()

    def _run_cv2_window(self):
        window_flags = cv2.WINDOW_NORMAL
        if hasattr(cv2, "WINDOW_FREERATIO"):
            window_flags |= cv2.WINDOW_FREERATIO
        cv2.namedWindow(WINDOW_NAME, window_flags)
        if hasattr(cv2, "WND_PROP_ASPECT_RATIO") and hasattr(cv2, "WINDOW_FREERATIO"):
            try:
                cv2.setWindowProperty(WINDOW_NAME, cv2.WND_PROP_ASPECT_RATIO, cv2.WINDOW_FREERATIO)
            except cv2.error:
                pass
        self.canvas_size = default_canvas_size(self.image)
        cv2.resizeWindow(WINDOW_NAME, *self.canvas_size)
        cv2.setMouseCallback(WINDOW_NAME, self.on_mouse)

        while True:
            self._sync_canvas_size_from_window()
            canvas, _ = self.render()
            cv2.imshow(WINDOW_NAME, canvas)
            key = cv2.waitKeyEx(20)
            if self._sync_canvas_size_from_window():
                canvas, _ = self.render()
                cv2.imshow(WINDOW_NAME, canvas)

            if key == -1:
                continue

            if key in (ord("q"), 27):
                break

            self._handle_key(key=key)

        cv2.destroyAllWindows()

    def run(self):
        self.load_initial()
        self._print_controls()

        try:
            import tkinter as tk
        except ImportError:
            self._run_cv2_window()
            return

        try:
            self._run_tk_window(tk)
        except tk.TclError as exc:
            print(f"Tk window unavailable ({exc}); falling back to OpenCV window")
            self._run_cv2_window()


def visualize(images_dir, labels_dir, classes_file=None, save_dir=None, start_index=0):
    editor = AnnotationEditor(
        images_dir=images_dir,
        labels_dir=labels_dir,
        classes_file=classes_file,
        save_dir=save_dir,
        start_index=start_index,
    )
    editor.run()
