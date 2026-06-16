from pathlib import Path
import tempfile
import unittest

from annoviz.web_editor import WebEditorHandler, WebEditorServer


class WebEditorSearchTests(unittest.TestCase):
    def make_server(self, image_names):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        images_dir = root / "images"
        labels_dir = root / "labels"
        images_dir.mkdir()
        labels_dir.mkdir()
        for name in image_names:
            (images_dir / name).write_text("", encoding="utf-8")

        server = WebEditorServer(("127.0.0.1", 0), WebEditorHandler, images_dir, labels_dir, None)
        self.addCleanup(server.server_close)
        self.addCleanup(tmp.cleanup)
        return server

    def test_search_ranks_exact_stem_before_similar_names(self):
        server = self.make_server([
            "scene_001_copy.jpg",
            "scene_001.jpg",
            "scene_001_mask.png",
            "scene_002.jpg",
        ])

        matches = server.search_image_names("scene_001")

        self.assertEqual(
            ["scene_001.jpg", "scene_001_copy.jpg", "scene_001_mask.png"],
            [match["name"] for match in matches],
        )

    def test_search_is_case_insensitive_and_accepts_full_filename(self):
        server = self.make_server(["Dog.JPG", "dog_closeup.jpg", "cat.jpg"])

        matches = server.search_image_names("dog.jpg")

        self.assertEqual("Dog.JPG", matches[0]["name"])

    def test_search_uses_basename_from_path_like_query(self):
        server = self.make_server(["bird.jpg", "blue_bird.jpg", "cat.jpg"])

        matches = server.search_image_names("/tmp/data/bird")

        self.assertEqual(["bird.jpg", "blue_bird.jpg"], [match["name"] for match in matches])

        matches = server.search_image_names(r"C:\data\blue_bird.jpg")

        self.assertEqual(["blue_bird.jpg"], [match["name"] for match in matches])


if __name__ == "__main__":
    unittest.main()
