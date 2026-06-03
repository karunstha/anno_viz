from pathlib import Path
import argparse
import json


CONFIG_FILE = "anno_viz_config"
LEGACY_DATASET_PATH_FILE = "anno_viz_datasetpath.txt"

DATASET_DIR_INSTRUCTIONS = """Dataset directory is not set.

Set a default dataset directory for this workspace:
    python app.py --set-dataset-dir /path/to/dataset

Or temporarily visualize a different dataset for one run:
    python app.py --dataset-dir /path/to/dataset
    python app.py -dataset_dir /path/to/dataset

The dataset directory should contain:
    images/
    labels/
    classes.txt
"""


def workspace_config_file():
    return Path.cwd() / CONFIG_FILE


def workspace_legacy_config_file():
    return Path.cwd() / LEGACY_DATASET_PATH_FILE


def is_git_workspace(workspace_dir):
    return (workspace_dir / ".git").exists()


def ensure_config_gitignored(workspace_dir):
    if not is_git_workspace(workspace_dir):
        return False

    gitignore_path = workspace_dir / ".gitignore"
    entry = CONFIG_FILE

    if not gitignore_path.exists():
        gitignore_path.write_text(f"{entry}\n", encoding="utf-8")
        return True

    content = gitignore_path.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines()]
    if entry in lines:
        return False

    separator = "" if content.endswith("\n") or not content else "\n"
    with gitignore_path.open("a", encoding="utf-8") as gitignore:
        gitignore.write(f"{separator}{entry}\n")
    return True


def normalize_dataset_dir(path):
    path = Path(path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def write_workspace_config(config_file, dataset_dir):
    config = {
        "dataset_dir": str(dataset_dir),
    }
    config_file.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def read_dataset_path_text(path_file):
    raw_path = path_file.read_text(encoding="utf-8").strip()
    if not raw_path:
        return None

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = path_file.parent / path
    return path.resolve()


def read_workspace_dataset_dir(config_file):
    if config_file.exists():
        raw_config = config_file.read_text(encoding="utf-8").strip()
        if not raw_config:
            return None

        try:
            config = json.loads(raw_config)
        except json.JSONDecodeError:
            return read_dataset_path_text(config_file)

        dataset_dir = config.get("dataset_dir")
        if not dataset_dir:
            return None

        path = Path(dataset_dir).expanduser()
        if not path.is_absolute():
            path = config_file.parent / path
        return path.resolve()

    legacy_path_file = workspace_legacy_config_file()
    if legacy_path_file.exists():
        return read_dataset_path_text(legacy_path_file)

    return None


def main():
    parser = argparse.ArgumentParser(description="View/edit YOLO annotations on generated images")
    parser.add_argument(
        "--set-dataset-dir",
        "--set_dataset_dir",
        dest="set_dataset_dir",
        default=None,
        type=Path,
        help=f"Save the default dataset root to {CONFIG_FILE} in the current workspace.",
    )
    parser.add_argument(
        "--dataset-dir",
        "--dataset_dir",
        "-dataset_dir",
        dest="dataset_dir",
        default=None,
        type=Path,
        help="Dataset root for this run.",
    )
    parser.add_argument("--images-dir", default=None, type=Path)
    parser.add_argument("--labels-dir", default=None, type=Path)
    parser.add_argument("--classes-file", default=None, type=Path)
    parser.add_argument("--save-dir", default=None, type=Path)
    parser.add_argument("--start-index", default=0, type=int)
    parser.add_argument("--port", default=0, type=int, help="Local web UI port. Defaults to a free port.")

    args = parser.parse_args()
    config_file = workspace_config_file()
    if args.set_dataset_dir is not None:
        dataset_dir = normalize_dataset_dir(args.set_dataset_dir)
        write_workspace_config(config_file, dataset_dir)
        print(f"saved dataset directory to {config_file}: {dataset_dir}")
        legacy_path_file = workspace_legacy_config_file()
        if legacy_path_file.exists():
            legacy_path_file.unlink()
        ensure_config_gitignored(config_file.parent)
        return

    dataset_dir = args.dataset_dir.expanduser() if args.dataset_dir is not None else read_workspace_dataset_dir(config_file)
    if dataset_dir is None:
        parser.exit(2, f"error: {DATASET_DIR_INSTRUCTIONS}\n")

    dataset_dir = normalize_dataset_dir(dataset_dir)
    from web_editor import visualize

    visualize(
        images_dir=args.images_dir or dataset_dir / "images",
        labels_dir=args.labels_dir or dataset_dir / "labels",
        classes_file=args.classes_file or dataset_dir / "classes.txt",
        save_dir=args.save_dir,
        start_index=args.start_index,
        port=args.port,
    )


if __name__ == "__main__":
    main()
