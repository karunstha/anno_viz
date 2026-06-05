import os
from pathlib import Path
import tempfile
import unittest

from annoviz.io_utils import collect_images


class CollectImagesTests(unittest.TestCase):
    def test_collects_supported_image_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            images_dir = Path(tmp) / "images"
            images_dir.mkdir()
            (images_dir / "b.txt").write_text("", encoding="utf-8")
            (images_dir / "a.JPG").write_text("", encoding="utf-8")
            (images_dir / "c.webp").write_text("", encoding="utf-8")

            images = collect_images(images_dir)

        self.assertEqual(["a.JPG", "c.webp"], [path.name for path in images])

    def test_missing_directory_reports_similar_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Images").mkdir()
            if (root / "images").exists():
                self.skipTest("filesystem is case-insensitive")

            with self.assertRaisesRegex(RuntimeError, "different case"):
                collect_images(root / "images")

    def test_file_path_reports_not_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            images_path = Path(tmp) / "images"
            images_path.write_text("", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "not a directory"):
                collect_images(images_path)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink is not available")
    def test_broken_symlink_reports_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            images_link = Path(tmp) / "images"
            target = Path(tmp) / "missing"
            images_link.symlink_to(target, target_is_directory=True)

            with self.assertRaisesRegex(RuntimeError, "broken symlink"):
                collect_images(images_link)


if __name__ == "__main__":
    unittest.main()
