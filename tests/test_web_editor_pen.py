from pathlib import Path
import tempfile
import unittest

from annoviz.web_editor import apply_image_strokes, save_uploaded_image

try:
    from PIL import Image
except ImportError:  # pragma: no cover - dependency is declared for installed runs
    Image = None


class WebEditorImageUploadTests(unittest.TestCase):
    def test_save_uploaded_image_writes_matching_image_type(self):
        data = b"\x89PNG\r\n\x1a\n" + b"edited-image"
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "sample.png"
            image_path.write_bytes(b"old")

            result = save_uploaded_image(image_path, data, "image/png")

            self.assertEqual(data, image_path.read_bytes())
        self.assertEqual({"bytes": len(data)}, result)

    def test_save_uploaded_image_rejects_mismatched_image_type(self):
        data = b"\x89PNG\r\n\x1a\n" + b"edited-image"
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "sample.jpg"
            image_path.write_bytes(b"old")

            with self.assertRaises(ValueError):
                save_uploaded_image(image_path, data, "image/png")

            self.assertEqual(b"old", image_path.read_bytes())


@unittest.skipIf(Image is None, "Pillow is not installed")
class WebEditorPenTests(unittest.TestCase):
    def test_apply_image_strokes_draws_into_image_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "sample.png"
            Image.new("RGB", (24, 24), "white").save(image_path)

            result = apply_image_strokes(image_path, [
                {
                    "color": "#ff0000",
                    "size": 5,
                    "points": [{"x": 4, "y": 12}, {"x": 20, "y": 12}],
                }
            ])

            with Image.open(image_path) as image:
                pixel = image.convert("RGB").getpixel((12, 12))

        self.assertEqual({"strokes": 1}, result)
        self.assertEqual((255, 0, 0), pixel)

    def test_apply_image_strokes_clamps_points_to_image_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "sample.png"
            Image.new("RGB", (8, 8), "white").save(image_path)

            result = apply_image_strokes(image_path, [
                {
                    "color": "#0000ff",
                    "size": 3,
                    "points": [{"x": -20, "y": -20}, {"x": 50, "y": 50}],
                }
            ])

            with Image.open(image_path) as image:
                top_left = image.convert("RGB").getpixel((0, 0))
                bottom_right = image.convert("RGB").getpixel((7, 7))

        self.assertEqual({"strokes": 1}, result)
        self.assertEqual((0, 0, 255), top_left)
        self.assertEqual((0, 0, 255), bottom_right)


if __name__ == "__main__":
    unittest.main()
