from pathlib import Path
import argparse
import json
import os


CONFIG_FILE = "anno_viz_config"
LEGACY_DATASET_PATH_FILE = "anno_viz_datasetpath.txt"

DATASET_DIR_INSTRUCTIONS = """Dataset directory is not set.

Set a default dataset directory for this workspace:
    annoviz --set-dataset-dir /path/to/dataset

Or temporarily visualize a different dataset for one run:
    annoviz --dataset-dir /path/to/dataset
    annoviz -dataset_dir /path/to/dataset

The dataset directory should contain:
    images/
    labels/
    classes.txt or data.yaml

If the current working directory already contains that layout, annoviz will use it automatically.
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
    return Path(os.path.abspath(os.fspath(path)))


def default_classes_file(dataset_dir):
    dataset_dir = normalize_dataset_dir(dataset_dir)
    classes_txt = dataset_dir / "classes.txt"
    if classes_txt.is_file():
        return classes_txt

    data_yaml = dataset_dir / "data.yaml"
    if data_yaml.is_file():
        return data_yaml

    return classes_txt


def looks_like_dataset_dir(path):
    dataset_dir = normalize_dataset_dir(path)
    return (
        (dataset_dir / "images").is_dir()
        and (dataset_dir / "labels").is_dir()
        and default_classes_file(dataset_dir).is_file()
    )


def write_workspace_config(config_file, dataset_dir, last_index=None):
    config = {
        "dataset_dir": str(dataset_dir),
    }
    if last_index is not None:
        config["last_index"] = max(0, int(last_index))
    config_file.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def read_dataset_path_text(path_file):
    raw_path = path_file.read_text(encoding="utf-8").strip()
    if not raw_path:
        return None

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = path_file.parent / path
    return normalize_dataset_dir(path)


def read_workspace_state(config_file):
    state = {
        "dataset_dir": None,
        "last_index": None,
    }

    if config_file.exists():
        raw_config = config_file.read_text(encoding="utf-8").strip()
        if not raw_config:
            return state

        try:
            config = json.loads(raw_config)
        except json.JSONDecodeError:
            state["dataset_dir"] = read_dataset_path_text(config_file)
            return state

        dataset_dir = config.get("dataset_dir")
        if dataset_dir:
            path = Path(dataset_dir).expanduser()
            if not path.is_absolute():
                path = config_file.parent / path
            state["dataset_dir"] = normalize_dataset_dir(path)

        last_index = config.get("last_index")
        try:
            if last_index is not None:
                state["last_index"] = max(0, int(last_index))
        except (TypeError, ValueError):
            state["last_index"] = None
        return state

    legacy_path_file = workspace_legacy_config_file()
    if legacy_path_file.exists():
        state["dataset_dir"] = read_dataset_path_text(legacy_path_file)
        return state

    return state


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
    parser.add_argument("--start-index", default=None, type=int)
    parser.add_argument("--port", default=0, type=int, help="Local web UI port. Defaults to a free port.")
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Open the editor in the default browser instead of creating a native desktop window.",
    )

    args = parser.parse_args()
    config_file = workspace_config_file()
    workspace_state = read_workspace_state(config_file)
    if args.set_dataset_dir is not None:
        dataset_dir = normalize_dataset_dir(args.set_dataset_dir)
        write_workspace_config(config_file, dataset_dir, last_index=0)
        print(f"saved dataset directory to {config_file}: {dataset_dir}")
        legacy_path_file = workspace_legacy_config_file()
        if legacy_path_file.exists():
            legacy_path_file.unlink()
        ensure_config_gitignored(config_file.parent)
        return

    using_saved_workspace_dataset = args.dataset_dir is None and workspace_state["dataset_dir"] is not None
    dataset_dir = args.dataset_dir.expanduser() if args.dataset_dir is not None else workspace_state["dataset_dir"]
    if dataset_dir is None and looks_like_dataset_dir(Path.cwd()):
        dataset_dir = Path.cwd()
    if dataset_dir is None:
        parser.exit(2, f"error: {DATASET_DIR_INSTRUCTIONS}\n")

    dataset_dir = normalize_dataset_dir(dataset_dir)
    start_index = (
        args.start_index
        if args.start_index is not None
        else ((workspace_state["last_index"] or 0) if using_saved_workspace_dataset else 0)
    )
    session_config_file = config_file if using_saved_workspace_dataset else None
    from .web_editor import visualize

    visualize(
        images_dir=args.images_dir or dataset_dir / "images",
        labels_dir=args.labels_dir or dataset_dir / "labels",
        classes_file=args.classes_file or default_classes_file(dataset_dir),
        save_dir=args.save_dir,
        start_index=start_index,
        port=args.port,
        browser=args.browser,
        session_config_file=session_config_file,
        session_dataset_dir=dataset_dir if session_config_file is not None else None,
    )


if __name__ == "__main__":
    main()
