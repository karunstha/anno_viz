from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, unquote, urlparse
import webbrowser
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


def linux_window_help():
    return (
        "Native window creation failed. On Ubuntu, pywebview typically needs GTK and WebKit.\n"
        "Install them with:\n"
        "  sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 "
        "gir1.2-webkit2-4.1\n"
        "If you are using a virtualenv, create it with --system-site-packages or "
        "install PyGObject into the virtualenv.\n"
        "You can also bypass native window creation with:\n"
        "  annoviz --browser\n"
    )


def open_in_browser(url):
    print(f"Opening Anno Viz in browser: {url}")
    if not webbrowser.open(url):
        print(f"Could not launch a browser automatically. Open this URL manually: {url}")


def browser_event_loop(url):
    open_in_browser(url)
    print("Press Ctrl+C to stop the local editor server.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nShutting down Anno Viz.")


def has_graphical_display():
    if os.name == "nt":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def is_linux():
    return sys.platform.startswith("linux")


def linux_gtk_missing_reason():
    if importlib.util.find_spec("gi") is None:
        return "PyGObject is not available in this Python environment: missing module 'gi'."

    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # noqa: F401
    except (ImportError, ValueError) as exc:
        return f"GTK is not available through PyGObject: {exc}"

    return None


class WebEditorServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address,
        handler_cls,
        images_dir,
        labels_dir,
        classes_file,
        start_index=0,
        session_config_file=None,
        session_dataset_dir=None,
        slideshow_delay_ms=50,
    ):
        super().__init__(server_address, handler_cls)
        self.images_dir = Path(images_dir)
        self.labels_dir = Path(labels_dir)
        self.classes_file = Path(classes_file) if classes_file is not None else None
        self.start_index = start_index
        self.session_config_file = Path(session_config_file) if session_config_file is not None else None
        self.session_dataset_dir = Path(session_dataset_dir) if session_dataset_dir is not None else None
        try:
            self.slideshow_delay_ms = max(1, int(slideshow_delay_ms))
        except (TypeError, ValueError):
            self.slideshow_delay_ms = 50
        self.pending_delete_names = set()
        self.pending_delete_lock = threading.Lock()
        self.current_index = max(0, int(start_index))
        self.current_image_name = None
        self._images_cache = []
        self._image_name_map = {}
        self._image_index_map = {}
        self.refresh_images_cache()
        self._sync_current_image_name()

    def images(self):
        return self._images_cache

    def image_count(self):
        return len(self._images_cache)

    def refresh_images_cache(self):
        images = collect_images(self.images_dir)
        self._images_cache = images
        self._image_name_map = {image_path.name: image_path for image_path in images}
        self._image_index_map = {image_path.name: idx for idx, image_path in enumerate(images)}
        return images

    def image_for_name(self, name):
        return self._image_name_map.get(Path(name).name)

    def image_for_index(self, index):
        if not self._images_cache:
            return None
        idx = max(0, min(int(index), len(self._images_cache) - 1))
        return self._images_cache[idx]

    def name_for_index(self, index):
        image_path = self.image_for_index(index)
        return image_path.name if image_path is not None else None

    def timeline_entries(self, start, count):
        if not self._images_cache:
            return []
        start = max(0, min(int(start), len(self._images_cache) - 1))
        count = max(0, int(count))
        end = min(len(self._images_cache), start + count)
        pending = set(self.pending_delete_names_snapshot())
        return [
            {
                "idx": idx,
                "name": image_path.name,
                "pendingDelete": image_path.name in pending,
            }
            for idx, image_path in enumerate(self._images_cache[start:end], start=start)
        ]

    def label_for_name(self, name):
        return self.labels_dir / f"{Path(name).stem}.txt"

    def valid_image_names(self):
        return set(self._image_name_map)

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

        if deleted:
            self.refresh_images_cache()
        with self.pending_delete_lock:
            self.pending_delete_names.difference_update(requested_names)
        self.persist_session_state()
        return deleted

    def apply_pending_deletes(self):
        with self.pending_delete_lock:
            names = sorted(self.pending_delete_names)
        return self.apply_delete_names(names)

    def resolved_current_index(self):
        images = self.images()
        if not images:
            return 0

        if self.current_image_name is not None:
            idx = self._image_index_map.get(self.current_image_name)
            if idx is not None:
                return idx

        return max(0, min(int(self.current_index), len(images) - 1))

    def _sync_current_image_name(self):
        images = self.images()
        if not images:
            self.current_index = 0
            self.current_image_name = None
            return

        idx = max(0, min(int(self.current_index), len(images) - 1))
        self.current_index = idx
        if self.current_image_name not in {image_path.name for image_path in images}:
            self.current_image_name = images[idx].name

    def update_session_position(self, index, name=None):
        try:
            self.current_index = max(0, int(index))
        except (TypeError, ValueError):
            pass

        clean_name = Path(name).name if name else None
        if clean_name and clean_name in self.valid_image_names():
            self.current_image_name = clean_name
        else:
            self._sync_current_image_name()

        self.persist_session_state()
        return self.resolved_current_index()

    def persist_session_state(self):
        if self.session_config_file is None or self.session_dataset_dir is None:
            return

        payload = {
            "dataset_dir": os.path.abspath(os.fspath(self.session_dataset_dir)),
            "last_index": self.resolved_current_index(),
            "slideshow_delay_ms": self.slideshow_delay_ms,
        }
        self.session_config_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


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
            self.send_text(
                "\n".join([
                    f"window.START_INDEX = {int(self.server.start_index)};",
                    f"window.SLIDESHOW_DELAY_MS = {int(self.server.slideshow_delay_ms)};",
                    "",
                ]),
                "application/javascript",
            )
            return
        if parsed.path == "/app.js":
            self.send_file(ASSET_DIR / "app.js")
            return
        if parsed.path == "/api/state":
            query = parse_qs(parsed.query)
            if query.get("refresh", ["0"])[0] == "1":
                self.server.refresh_images_cache()
            idx = int(query.get("idx", [self.server.resolved_current_index()])[0])
            current_image = self.server.image_for_index(idx)
            pending_deletes = self.server.pending_delete_names_snapshot()
            self.send_json({
                "totalImages": self.server.image_count(),
                "currentIndex": self.server.resolved_current_index() if current_image is None else self.server._image_index_map[current_image.name],
                "currentName": None if current_image is None else current_image.name,
                "classes": load_classes(self.server.classes_file),
                "pendingDeletes": pending_deletes,
            })
            return
        if parsed.path == "/api/timeline":
            query = parse_qs(parsed.query)
            start = int(query.get("start", [0])[0])
            count = int(query.get("count", [0])[0])
            self.send_json({
                "entries": self.server.timeline_entries(start, count),
                "totalImages": self.server.image_count(),
            })
            return
        if parsed.path == "/api/label":
            query = parse_qs(parsed.query)
            if "idx" in query:
                name = self.server.name_for_index(int(query.get("idx", ["0"])[0])) or ""
            else:
                name = query.get("name", [""])[0]
            label_path = self.server.label_for_name(name)
            self.send_text(label_path.read_text() if label_path.exists() else "", "text/plain")
            return
        if parsed.path.startswith("/image-by-idx/"):
            try:
                idx = int(parsed.path[len("/image-by-idx/"):])
            except ValueError:
                self.send_error(404)
                return
            image_path = self.server.image_for_index(idx)
            if image_path is None:
                self.send_error(404)
                return
            self.send_file(image_path)
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
        if parsed.path == "/api/session":
            index = self.server.update_session_position(body.get("index", 0), body.get("name"))
            self.send_json({"ok": True, "index": index})
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


def visualize(
    images_dir,
    labels_dir,
    classes_file=None,
    save_dir=None,
    start_index=0,
    port=0,
    browser=False,
    session_config_file=None,
    session_dataset_dir=None,
    slideshow_delay_ms=50,
):
    server = WebEditorServer(
        ("127.0.0.1", port),
        WebEditorHandler,
        images_dir,
        labels_dir,
        classes_file,
        start_index,
        session_config_file=session_config_file,
        session_dataset_dir=session_dataset_dir,
        slideshow_delay_ms=slideshow_delay_ms,
    )
    host, actual_port = server.server_address
    url = f"http://{host}:{actual_port}/"
    print(f"Anno Viz window serving: {url}")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        if browser:
            browser_event_loop(url)
            return

        if not has_graphical_display():
            print("No graphical display detected. Falling back to browser mode.")
            browser_event_loop(url)
            return

        webview = import_webview()
        gui = None
        if is_linux():
            missing_reason = linux_gtk_missing_reason()
            if missing_reason is not None:
                print(missing_reason)
                print(linux_window_help())
                browser_event_loop(url)
                return
            gui = "gtk"

        api = EditorApi(server)
        window = webview.create_window("Anno Viz", url, js_api=api, width=1200, height=900)
        api.window = window
        webview.start(gui=gui)
    except Exception as exc:
        print(f"Native window launch failed: {exc}")
        if os.name == "posix":
            print(linux_window_help())
        browser_event_loop(url)
    finally:
        server.shutdown()
        server.server_close()
