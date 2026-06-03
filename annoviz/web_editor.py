from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
import json
import mimetypes
import threading

from .geometry import normalize_xyxy, xyxy_to_yolo
from .io_utils import collect_images, load_classes


ASSET_DIR = Path(__file__).resolve().parent / "web"


class EditorApi:
    def __init__(self, server):
        self.server = server
        self.window = None

    def close_editor(self, apply_deletes=False):
        if apply_deletes:
            self.server.apply_pending_deletes()
        else:
            self.server.set_pending_delete_names([])

        threading.Timer(0.01, self._destroy_window).start()
        return True

    def _destroy_window(self):
        if self.window is not None:
            self.window.destroy()


def import_webview():
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError(
            "Anno Viz requires pywebview for the embedded editor window.\n"
            "Install it with: python3 -m pip install ."
        ) from exc
    return webview


class WebEditorServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_cls, images_dir, labels_dir, classes_file, start_index=0):
        super().__init__(server_address, handler_cls)
        self.images_dir = Path(images_dir)
        self.labels_dir = Path(labels_dir)
        self.classes_file = Path(classes_file) if classes_file is not None else None
        self.start_index = start_index
        self.pending_delete_names = set()
        self.pending_delete_lock = threading.Lock()

    def images(self):
        return collect_images(self.images_dir)

    def image_for_name(self, name):
        requested = Path(name).name
        for image_path in self.images():
            if image_path.name == requested:
                return image_path
        return None

    def label_for_name(self, name):
        return self.labels_dir / f"{Path(name).stem}.txt"

    def valid_image_names(self):
        return {image_path.name for image_path in self.images()}

    def set_pending_delete_names(self, names):
        valid_names = self.valid_image_names()
        clean_names = {Path(name).name for name in names if Path(name).name in valid_names}
        with self.pending_delete_lock:
            self.pending_delete_names = clean_names
        return sorted(clean_names)

    def pending_delete_count(self):
        valid_names = self.valid_image_names()
        with self.pending_delete_lock:
            self.pending_delete_names = {name for name in self.pending_delete_names if name in valid_names}
            return len(self.pending_delete_names)

    def pending_delete_names_snapshot(self):
        self.pending_delete_count()
        with self.pending_delete_lock:
            return sorted(self.pending_delete_names)

    def apply_delete_names(self, names):
        requested_names = {Path(name).name for name in names}
        deleted = []
        for name in requested_names:
            image_path = self.image_for_name(name)
            if image_path is None:
                continue
            label_path = self.label_for_name(image_path.name)
            try:
                image_path.unlink()
                deleted.append(image_path.name)
            except FileNotFoundError:
                pass
            try:
                label_path.unlink()
            except FileNotFoundError:
                pass

        with self.pending_delete_lock:
            self.pending_delete_names.difference_update(requested_names)
        return deleted

    def apply_pending_deletes(self):
        with self.pending_delete_lock:
            names = sorted(self.pending_delete_names)
        return self.apply_delete_names(names)


class WebEditorHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_file(ASSET_DIR / "index.html")
            return
        if parsed.path == "/styles.css":
            self.send_file(ASSET_DIR / "styles.css")
            return
        if parsed.path == "/config.js":
            self.send_text(f"window.START_INDEX = {int(self.server.start_index)};\n", "application/javascript")
            return
        if parsed.path == "/app.js":
            self.send_file(ASSET_DIR / "app.js")
            return
        if parsed.path == "/api/state":
            pending_deletes = self.server.pending_delete_names_snapshot()
            self.send_json({
                "images": [{"name": image.name} for image in self.server.images()],
                "classes": load_classes(self.server.classes_file),
                "pendingDeletes": pending_deletes,
            })
            return
        if parsed.path == "/api/label":
            query = parse_qs(parsed.query)
            name = query.get("name", [""])[0]
            label_path = self.server.label_for_name(name)
            self.send_text(label_path.read_text() if label_path.exists() else "", "text/plain")
            return
        if parsed.path.startswith("/image/"):
            name = unquote(parsed.path[len("/image/"):])
            image_path = self.server.image_for_name(name)
            if image_path is None:
                self.send_error(404)
                return
            self.send_file(image_path)
            return
        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        body = self.read_json()
        if parsed.path == "/api/save":
            name = body.get("name", "")
            width = int(body.get("width", 0))
            height = int(body.get("height", 0))
            boxes = body.get("boxes", [])
            if width <= 0 or height <= 0:
                self.send_error(400, "invalid image dimensions")
                return
            label_path = self.server.label_for_name(name)
            save_web_label(label_path, boxes, width, height)
            self.send_json({"ok": True})
            return
        if parsed.path == "/api/delete":
            deleted = self.server.apply_delete_names(body.get("names", []))
            self.send_json({"ok": True, "deleted": deleted})
            return
        if parsed.path == "/api/pending-deletes":
            pending = self.server.set_pending_delete_names(body.get("names", []))
            self.send_json({"ok": True, "pendingDeletes": pending})
            return
        self.send_error(404)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def send_text(self, text, content_type):
        data = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, value):
        data = json.dumps(value).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, path):
        data = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def save_web_label(label_path, boxes, img_w, img_h):
    label_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for box in boxes:
        x1, y1, x2, y2 = normalize_xyxy(
            int(round(box["x1"])),
            int(round(box["y1"])),
            int(round(box["x2"])),
            int(round(box["y2"])),
        )
        if x2 - x1 < 2 or y2 - y1 < 2:
            continue
        cls_id = int(box["cls_id"])
        xc, yc, bw, bh = xyxy_to_yolo(x1, y1, x2, y2, img_w, img_h)
        lines.append(f"{cls_id} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}")
    label_path.write_text("\n".join(lines) + ("\n" if lines else ""))
    print(f"saved label: {label_path} ({len(lines)} boxes)")


def visualize(images_dir, labels_dir, classes_file=None, save_dir=None, start_index=0, port=0):
    webview = import_webview()
    server = WebEditorServer(("127.0.0.1", port), WebEditorHandler, images_dir, labels_dir, classes_file, start_index)
    host, actual_port = server.server_address
    url = f"http://{host}:{actual_port}/"
    print(f"Anno Viz window serving: {url}")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        api = EditorApi(server)
        window = webview.create_window("Anno Viz", url, js_api=api, width=1200, height=900)
        api.window = window
        webview.start()
    finally:
        server.shutdown()
        server.server_close()
