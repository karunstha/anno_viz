# Anno Viz

Anno Viz is a local YOLO annotation viewer and editor for image datasets. It opens a native desktop window backed by a web UI, shows the current image with editable bounding boxes, and includes a thumbnail timeline for moving through the dataset quickly.

## Screenshot

![Anno Viz screenshot](https://raw.githubusercontent.com/karunstha/anno_viz/main/docs/screenshots/anno-viz.png)

## Dataset Layout

Anno Viz expects a dataset directory with this structure:

```text
dataset/
  images/
    image_001.jpg
    image_002.jpg
  labels/
    image_001.txt
    image_002.txt
  classes.txt
```

You can also use `data.yaml` instead of `classes.txt` for class names.

Labels use standard YOLO text format:

```text
class_id x_center y_center width height
```

The coordinate values are normalized from `0` to `1`.

## Install

Create and activate a virtual environment if you want to keep dependencies isolated:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the published package directly with:

```bash
python3 -m pip install annoviz
```

Install Anno Viz and its dependencies from the project root:

```bash
python3 -m pip install .
```

This installs the `annoviz` command. If you install outside a virtual environment and your shell cannot find `annoviz`, add your Python user scripts directory to `PATH`. On macOS with the system/Xcode Python this is often:

```bash
export PATH="$HOME/Library/Python/3.9/bin:$PATH"
```

For active development, install it in editable mode:

```bash
python3 -m pip install -e .
```

`pywebview` is required because the editor opens in a native desktop window. On macOS with Python 3.9, `requirements.txt` pins the PyObjC packages below version 12 because PyObjC 12 may try to build from source and fail on that toolchain.

On Ubuntu and other Linux desktops, `pywebview` also needs system GUI libraries:

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1
```

If you run Anno Viz from a virtualenv on Ubuntu, create the virtualenv with access to system packages so it can import `gi`:

```bash
python3 -m venv --system-site-packages .venv
```

## Configure Dataset Directory

If you run `annoviz` inside a folder that already has this layout:

```text
images/
labels/
classes.txt or data.yaml
```

Anno Viz will use the current directory as the dataset automatically. No `anno_viz_config` file is needed for that case.

Otherwise, set the default dataset directory for the current workspace:

```bash
annoviz --set-dataset-dir /path/to/dataset
```

This creates a local workspace config file named `anno_viz_config`. It is ignored by git, so each workspace can point at its own dataset.

When you use a saved workspace dataset, Anno Viz also remembers the last image index you were viewing and resumes from there on the next launch.

You can also use the underscore alias:

```bash
annoviz --set_dataset_dir /path/to/dataset
```

## Run

After setting the dataset directory, or from inside a dataset folder that matches the default layout:

```bash
annoviz
```

You can also run from source without installing through the compatibility wrappers:

```bash
python3 app.py
python3 anno_viz.py
python3 -m annoviz
```

To temporarily open a different dataset without changing the saved workspace config:

```bash
annoviz --dataset-dir /path/to/other/dataset
annoviz -dataset_dir /path/to/other/dataset
```

## Optional Paths

Use these when your dataset does not follow the default `images/`, `labels/`, `classes.txt` or `data.yaml` layout:

```bash
annoviz \
  --images-dir /path/to/images \
  --labels-dir /path/to/labels \
  --classes-file /path/to/classes.txt
```

Other useful options:

```bash
annoviz --start-index 25
annoviz --port 8765
annoviz --save-dir /path/to/rendered/previews
annoviz --browser
```

## Controls

Control

Action

`n`, Right Arrow

Next image

`b`, Left Arrow

Previous image

`c`

Move back 5 images

`v`

Move forward 2 images

`x`

Move back 10 images

`a`

Toggle add-annotation mode

Drag box

Move or resize an annotation

`Tab`

Select next box

`+`, `-`

Change selected/add class

`0` to `9`

Set selected/add class id

Delete, Backspace

Remove selected box from the label

`s`

Save label edits

`d`

Mark current image for deletion

Click a red thumbnail

Undo pending delete for that image

Apply Deletes

Delete all marked images and matching label files

`q`, Escape, Close

Close the editor

## Delete Flow

Press `d` to mark the current image for deletion. Marked thumbnails are shown in red.

Deletion is not applied immediately. You can undo a pending delete by clicking the red thumbnail. To permanently remove all marked images and their label files, click `Apply Deletes`.

When closing from `q`, Escape, or the `Close` button with pending deletes, Anno Viz asks whether to apply the pending deletes before closing.

## Config

The workspace config file is:

```text
anno_viz_config
```

It stores JSON like:

```json
{
  "dataset_dir": "/path/to/dataset",
  "last_index": 42
}
```

This file is intentionally ignored by git because it is machine/workspace-specific.

## Troubleshooting

If the editor says the dataset directory is not set, run:

```bash
annoviz --set-dataset-dir /path/to/dataset
```

If you are already inside the dataset folder, make sure it contains `images/`, `labels/`, and either `classes.txt` or `data.yaml`. In that case `annoviz` will use the current directory automatically without creating `anno_viz_config`.

If `pywebview` is missing, run:

```bash
python3 -m pip install .
```

If the native window does not open on Ubuntu and the error mentions `No module named 'gi'`, install the GTK/WebKit packages listed above and make sure your virtualenv can import `gi`. You can also run:

```bash
annoviz --browser
```

If no images appear, check that your image files are inside the configured `images/` directory. Supported extensions are handled by the local image collector in `io_utils.py`.
