import json
from pathlib import Path
import tempfile
import unittest

from annoviz.app import (
    DEFAULT_SLIDESHOW_DELAY_MS,
    normalize_cli_args,
    normalize_slideshow_delay_ms,
    read_workspace_state,
    write_workspace_config,
)


class AppConfigTests(unittest.TestCase):
    def test_write_and_read_slideshow_delay(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "anno_viz_config"
            dataset_dir = Path(tmp) / "dataset"

            write_workspace_config(config_file, dataset_dir, last_index=12, slideshow_delay_ms=75)
            state = read_workspace_state(config_file)

        self.assertEqual(dataset_dir, state["dataset_dir"])
        self.assertEqual(12, state["last_index"])
        self.assertEqual(75, state["slideshow_delay_ms"])

    def test_invalid_slideshow_delay_in_config_uses_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "anno_viz_config"
            config_file.write_text(json.dumps({"slideshow_delay_ms": 0}), encoding="utf-8")

            state = read_workspace_state(config_file)

        self.assertEqual(DEFAULT_SLIDESHOW_DELAY_MS, state["slideshow_delay_ms"])

    def test_normalize_cli_args_accepts_command_shape(self):
        self.assertEqual(
            ["--set-slideshow-delay", "80"],
            normalize_cli_args(["set", "slideshow", "delay", "80"]),
        )
        self.assertEqual(
            ["--set-slideshow-delay", "80"],
            normalize_cli_args(["set", "slideshow-delay", "80"]),
        )

    def test_normalize_slideshow_delay_rejects_zero(self):
        with self.assertRaises(ValueError):
            normalize_slideshow_delay_ms(0)


if __name__ == "__main__":
    unittest.main()
