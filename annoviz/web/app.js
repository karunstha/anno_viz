const state = {
  imageCount: 0,
  currentName: "",
  timelineEntries: [],
  classes: [],
  idx: 0,
  image: new Image(),
  imageLoaded: false,
  boxes: [],
  selectedIdx: null,
  selectedClass: 0,
  addMode: false,
  dirty: false,
  zoom: 1,
  panX: 0,
  panY: 0,
  dragging: false,
  dragAction: null,
  dragHandle: null,
  dragStart: null,
  dragOriginalBox: null,
  panning: false,
  panStart: null,
  pendingDeletes: new Set(),
  timelineStart: 0,
  display: { x: 0, y: 0, w: 0, h: 0, fitScale: 1 },
  timelineRegions: [],
  thumbCache: new Map(),
};

const imageCanvas = document.getElementById("imageCanvas");
const imageCtx = imageCanvas.getContext("2d");
const timelineCanvas = document.getElementById("timelineCanvas");
const timelineCtx = timelineCanvas.getContext("2d");
const statusEl = document.getElementById("status");
const subjectListEl = document.getElementById("subjectList");
const rescanBtn = document.getElementById("rescanBtn");
const applyDeletesBtn = document.getElementById("applyDeletesBtn");
const closeBtn = document.getElementById("closeBtn");
const closePromptEl = document.getElementById("closePrompt");
const closePromptTextEl = document.getElementById("closePromptText");
const closeApplyBtn = document.getElementById("closeApplyBtn");
const closeDiscardBtn = document.getElementById("closeDiscardBtn");

const ANNOTATION_COLOR = "#ffff00";
const DELETE_MARK_COLOR = "#d92d20";
const DELETE_MARK_BORDER = "#ff5a52";
const TIMELINE_SLOT_W = 44;
const TIMELINE_GAP = 6;
const TIMELINE_PAD_X = 6;
const TIMELINE_PAD_Y = 8;
const TIMELINE_H = 60;
const THUMB_CACHE_LIMIT = 96;

function clamp(value, lo, hi) {
  return Math.max(lo, Math.min(value, hi));
}

function normalizeBox(box) {
  const x1 = Math.min(box.x1, box.x2);
  const y1 = Math.min(box.y1, box.y2);
  const x2 = Math.max(box.x1, box.x2);
  const y2 = Math.max(box.y1, box.y2);
  return { ...box, x1, y1, x2, y2 };
}

function classLabel(clsId) {
  if (clsId >= 0 && clsId < state.classes.length) return `${clsId}: ${state.classes[clsId]}`;
  return `class ${clsId}`;
}

function imageName() {
  return state.currentName;
}

function imageUrl(name) {
  return `/image/${encodeURIComponent(name)}`;
}

function imageUrlByIndex(idx) {
  return `/image-by-idx/${idx}`;
}

function labelUrlByIndex(idx) {
  return `/api/label?idx=${idx}`;
}

function pendingDeleteNames() {
  return [...state.pendingDeletes];
}

function syncSessionPosition() {
  return fetch("/api/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      index: state.idx,
      name: imageName(),
    }),
    keepalive: true,
  }).catch(error => {
    console.error("Could not sync session position", error);
  });
}

function syncPendingDeletes() {
  return fetch("/api/pending-deletes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ names: pendingDeleteNames() }),
    keepalive: true,
  }).catch(error => {
    console.error("Could not sync pending deletes", error);
  });
}

function markPendingDelete(name) {
  if (!name) return;
  state.pendingDeletes.add(name);
  draw();
  syncPendingDeletes();
}

function clearPendingDelete(name) {
  state.pendingDeletes.delete(name);
  draw();
  syncPendingDeletes();
}

function closePromptMessage() {
  const count = state.pendingDeletes.size;
  const noun = count === 1 ? "image" : "images";
  return `You have ${count} ${noun} marked for deletion.\n\nApply pending deletes before closing?`;
}

function showClosePrompt() {
  closePromptTextEl.textContent = closePromptMessage();
  closePromptEl.hidden = false;
  closeApplyBtn.focus();
}

function hideClosePrompt() {
  closePromptEl.hidden = true;
}

function updateStatus() {
  const selected = state.selectedIdx == null ? "none" : classLabel(state.boxes[state.selectedIdx].cls_id);
  const selectedClass = classLabel(state.selectedClass);
  const pending = state.pendingDeletes.has(imageName()) ? " | pending delete" : "";
  statusEl.textContent = `${state.idx + 1}/${state.imageCount} | ${imageName()} | boxes=${state.boxes.length} | selected=${selected} | add-class=${selectedClass}${pending}`;
  applyDeletesBtn.disabled = state.pendingDeletes.size === 0;
}

function resizeCanvases() {
  const imagePaneRect = document.getElementById("imagePane").getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  imageCanvas.width = Math.max(1, Math.floor(imagePaneRect.width * dpr));
  imageCanvas.height = Math.max(1, Math.floor(imagePaneRect.height * dpr));
  imageCanvas.style.width = `${imagePaneRect.width}px`;
  imageCanvas.style.height = `${imagePaneRect.height}px`;
  imageCtx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const timelineRect = timelineCanvas.getBoundingClientRect();
  timelineCanvas.width = Math.max(1, Math.floor(timelineRect.width * dpr));
  timelineCanvas.height = Math.max(1, Math.floor(timelineRect.height * dpr));
  timelineCtx.setTransform(dpr, 0, 0, dpr, 0, 0);

  ensureTimelineVisible();
  draw();
}

function fitImage() {
  const canvasW = imageCanvas.clientWidth;
  const canvasH = imageCanvas.clientHeight;
  const imgW = state.image.naturalWidth || 1;
  const imgH = state.image.naturalHeight || 1;
  const fitScale = Math.min(canvasW / imgW, canvasH / imgH);
  const scale = fitScale * state.zoom;
  const w = Math.max(1, Math.round(imgW * scale));
  const h = Math.max(1, Math.round(imgH * scale));
  const centeredX = Math.floor((canvasW - w) / 2);
  const centeredY = Math.floor((canvasH - h) / 2);
  const maxPanX = Math.max(0, Math.floor((w - canvasW) / 2));
  const maxPanY = Math.max(0, Math.floor((h - canvasH) / 2));
  state.panX = clamp(state.panX, -maxPanX, maxPanX);
  state.panY = clamp(state.panY, -maxPanY, maxPanY);
  state.display = {
    x: centeredX + state.panX,
    y: centeredY + state.panY,
    w,
    h,
    fitScale,
  };
}

function imageToCanvas(x, y) {
  return {
    x: state.display.x + x * state.display.w / state.image.naturalWidth,
    y: state.display.y + y * state.display.h / state.image.naturalHeight,
  };
}

function canvasToImage(x, y) {
  const d = state.display;
  if (x < d.x || y < d.y || x >= d.x + d.w || y >= d.y + d.h) return null;
  return {
    x: clamp(Math.round((x - d.x) * state.image.naturalWidth / d.w), 0, state.image.naturalWidth - 1),
    y: clamp(Math.round((y - d.y) * state.image.naturalHeight / d.h), 0, state.image.naturalHeight - 1),
  };
}

function resetZoom() {
  state.zoom = 1;
  state.panX = 0;
  state.panY = 0;
}

function zoomAt(canvasX, canvasY, delta) {
  if (!state.imageLoaded) return;
  fitImage();
  const before = canvasToImage(canvasX, canvasY) ?? {
    x: state.image.naturalWidth / 2,
    y: state.image.naturalHeight / 2,
  };
  const prevZoom = state.zoom;
  const nextZoom = clamp(Number((prevZoom * delta).toFixed(4)), 1, 12);
  if (nextZoom === prevZoom) return;
  state.zoom = nextZoom;

  const canvasW = imageCanvas.clientWidth;
  const canvasH = imageCanvas.clientHeight;
  const imgW = state.image.naturalWidth || 1;
  const imgH = state.image.naturalHeight || 1;
  const fitScale = Math.min(canvasW / imgW, canvasH / imgH);
  const scaledW = Math.max(1, Math.round(imgW * fitScale * state.zoom));
  const scaledH = Math.max(1, Math.round(imgH * fitScale * state.zoom));
  const centeredX = Math.floor((canvasW - scaledW) / 2);
  const centeredY = Math.floor((canvasH - scaledH) / 2);
  state.panX = Math.round(canvasX - centeredX - before.x * scaledW / imgW);
  state.panY = Math.round(canvasY - centeredY - before.y * scaledH / imgH);
  fitImage();
  draw();
}

function colorFor(clsId) {
  return ANNOTATION_COLOR;
}

function selectedBox() {
  return state.selectedIdx == null ? null : state.boxes[state.selectedIdx] ?? null;
}

function boxMetrics(box) {
  const b = normalizeBox(box);
  return {
    width: b.x2 - b.x1,
    height: b.y2 - b.y1,
    area: (b.x2 - b.x1) * (b.y2 - b.y1),
  };
}

function drawTextWithBg(ctx, text, x, y, color) {
  ctx.font = "13px system-ui";
  const metrics = ctx.measureText(text);
  const h = 18;
  ctx.fillStyle = "rgba(0,0,0,0.8)";
  ctx.fillRect(x, y - h, metrics.width + 8, h + 4);
  ctx.fillStyle = color;
  ctx.fillText(text, x + 4, y - 4);
}

function handlePoints(box) {
  const b = normalizeBox(box);
  const mx = (b.x1 + b.x2) / 2;
  const my = (b.y1 + b.y2) / 2;
  return {
    tl: [b.x1, b.y1], t: [mx, b.y1], tr: [b.x2, b.y1],
    r: [b.x2, my], br: [b.x2, b.y2], b: [mx, b.y2],
    bl: [b.x1, b.y2], l: [b.x1, my],
  };
}

function nearestHandle(box, x, y) {
  const radius = 10 * state.image.naturalWidth / Math.max(1, state.display.w);
  let best = null;
  let bestDist = radius + 1;
  for (const [name, [px, py]] of Object.entries(handlePoints(box))) {
    const dist = Math.hypot(px - x, py - y);
    if (dist < bestDist) {
      best = name;
      bestDist = dist;
    }
  }
  return best;
}

function hitTest(x, y) {
  for (let i = state.boxes.length - 1; i >= 0; i--) {
    const b = normalizeBox(state.boxes[i]);
    if (x >= b.x1 && x <= b.x2 && y >= b.y1 && y <= b.y2) return i;
  }
  return null;
}

function drawImageCanvas() {
  const w = imageCanvas.clientWidth;
  const h = imageCanvas.clientHeight;
  imageCtx.clearRect(0, 0, w, h);
  imageCtx.fillStyle = "#181818";
  imageCtx.fillRect(0, 0, w, h);
  if (!state.imageLoaded) return;

  fitImage();
  const d = state.display;
  imageCtx.drawImage(state.image, d.x, d.y, d.w, d.h);

  for (let i = 0; i < state.boxes.length; i++) {
    const b = normalizeBox(state.boxes[i]);
    const p1 = imageToCanvas(b.x1, b.y1);
    const p2 = imageToCanvas(b.x2, b.y2);
    const color = colorFor(b.cls_id);
    imageCtx.strokeStyle = color;
    imageCtx.lineWidth = i === state.selectedIdx ? 3 : 2;
    imageCtx.strokeRect(p1.x, p1.y, p2.x - p1.x, p2.y - p1.y);
    drawTextWithBg(imageCtx, classLabel(b.cls_id), p1.x, Math.max(20, p1.y - 6), color);

    if (i === state.selectedIdx) {
      imageCtx.fillStyle = "#fff";
      imageCtx.strokeStyle = "#000";
      for (const [px, py] of Object.values(handlePoints(b))) {
        const hp = imageToCanvas(px, py);
        imageCtx.fillRect(hp.x - 4, hp.y - 4, 8, 8);
        imageCtx.strokeRect(hp.x - 4, hp.y - 4, 8, 8);
      }
    }
  }

  drawTextWithBg(
    imageCtx,
    `Mode: ${state.addMode ? "ADD" : "EDIT"}${state.dirty ? " *unsaved" : ""} | Zoom: ${state.zoom.toFixed(1)}x`,
    12,
    h - 14,
    "#fff",
  );
}

function drawSubjectCrop(ctx, box, canvasW, canvasH, selected) {
  const b = normalizeBox(box);
  const metrics = boxMetrics(b);
  const pad = Math.max(16, Math.round(Math.max(metrics.width, metrics.height) * 0.2));
  const sx = clamp(b.x1 - pad, 0, state.image.naturalWidth - 1);
  const sy = clamp(b.y1 - pad, 0, state.image.naturalHeight - 1);
  const sw = Math.max(1, Math.min(state.image.naturalWidth - sx, metrics.width + pad * 2));
  const sh = Math.max(1, Math.min(state.image.naturalHeight - sy, metrics.height + pad * 2));
  const scale = Math.min(canvasW / sw, canvasH / sh);
  const dw = Math.max(1, Math.round(sw * scale));
  const dh = Math.max(1, Math.round(sh * scale));
  const dx = Math.floor((canvasW - dw) / 2);
  const dy = Math.floor((canvasH - dh) / 2);
  ctx.clearRect(0, 0, canvasW, canvasH);
  ctx.fillStyle = "#161616";
  ctx.fillRect(0, 0, canvasW, canvasH);
  ctx.drawImage(state.image, sx, sy, sw, sh, dx, dy, dw, dh);

  const rx = dx + (b.x1 - sx) * scale;
  const ry = dy + (b.y1 - sy) * scale;
  const rw = metrics.width * scale;
  const rh = metrics.height * scale;
  ctx.strokeStyle = ANNOTATION_COLOR;
  ctx.lineWidth = selected ? 3 : 2;
  ctx.strokeRect(rx, ry, rw, rh);
}

function renderSubjectList() {
  subjectListEl.textContent = "";
  if (!state.boxes.length) {
    const empty = document.createElement("div");
    empty.className = "subjectEmpty";
    empty.textContent = "No annotations yet.";
    subjectListEl.appendChild(empty);
    return;
  }

  state.boxes.forEach((box, idx) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "subjectItem";
    if (idx === state.selectedIdx) button.classList.add("is-selected");
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", idx === state.selectedIdx ? "true" : "false");

    const thumb = document.createElement("canvas");
    thumb.className = "subjectThumb";
    thumb.width = 88;
    thumb.height = 88;

    const body = document.createElement("div");
    body.className = "subjectItemBody";

    const title = document.createElement("span");
    title.className = "subjectItemTitle";
    title.textContent = `${idx + 1}. ${classLabel(box.cls_id)}`;

    const metrics = boxMetrics(box);
    const meta = document.createElement("span");
    meta.className = "subjectItemMeta";
    meta.textContent = `${Math.round(metrics.width)} x ${Math.round(metrics.height)} px | area ${Math.round(metrics.area)} px`;

    body.append(title, meta);
    button.append(thumb, body);
    button.addEventListener("click", () => {
      state.selectedIdx = idx;
      state.selectedClass = state.boxes[idx].cls_id;
      draw();
    });
    subjectListEl.appendChild(button);

    if (state.imageLoaded) {
      const ctx = thumb.getContext("2d");
      drawSubjectCrop(ctx, box, thumb.width, thumb.height, idx === state.selectedIdx);
    }
  });
}

function timelineCapacity() {
  const timelineW = Math.max(1, timelineCanvas.clientWidth - 24);
  const usable = Math.max(1, timelineW - 2 * TIMELINE_PAD_X);
  return Math.max(1, Math.floor((usable + TIMELINE_GAP) / (TIMELINE_SLOT_W + TIMELINE_GAP)));
}

function ensureTimelineVisible() {
  if (!state.imageCount) {
    state.timelineStart = 0;
    return;
  }
  const capacity = timelineCapacity();
  const maxStart = Math.max(0, state.imageCount - capacity);
  if (state.idx < state.timelineStart) state.timelineStart = state.idx;
  else if (state.idx >= state.timelineStart + capacity) state.timelineStart = state.idx - capacity + 1;
  state.timelineStart = clamp(state.timelineStart, 0, maxStart);
}

async function loadTimeline() {
  ensureTimelineVisible();
  const resp = await fetch(`/api/timeline?start=${state.timelineStart}&count=${timelineCapacity()}`);
  const data = await resp.json();
  state.timelineEntries = data.entries ?? [];
  state.imageCount = data.totalImages ?? state.imageCount;
}

function drawTimeline() {
  const w = timelineCanvas.clientWidth;
  const h = timelineCanvas.clientHeight;
  timelineCtx.clearRect(0, 0, w, h);
  timelineCtx.fillStyle = "#1c1c1c";
  timelineCtx.fillRect(0, 0, w, h);

  const x1 = 12, y1 = 8, x2 = w - 12, y2 = y1 + TIMELINE_H;
  timelineCtx.fillStyle = "#141414";
  timelineCtx.fillRect(x1, y1, x2 - x1, y2 - y1);
  timelineCtx.strokeStyle = "#3c3c3c";
  timelineCtx.strokeRect(x1, y1, x2 - x1, y2 - y1);

  state.timelineRegions = [];
  let drawX = x1 + TIMELINE_PAD_X;
  const drawY1 = y1 + TIMELINE_PAD_Y;
  const drawY2 = y2 - TIMELINE_PAD_Y;

  for (const entry of state.timelineEntries) {
    const name = entry.name;
    const slot = { x: drawX, y: drawY1, w: TIMELINE_SLOT_W, h: drawY2 - drawY1, idx: entry.idx };
    const isPendingDelete = entry.pendingDelete || state.pendingDeletes.has(name);
    timelineCtx.fillStyle = isPendingDelete ? DELETE_MARK_COLOR : "#505050";
    timelineCtx.fillRect(slot.x, slot.y, slot.w, slot.h);

    let img = state.thumbCache.get(name);
    if (!img) {
      img = new Image();
      img.onload = () => drawTimeline();
      img.src = imageUrl(name);
      state.thumbCache.set(name, img);
    } else {
      state.thumbCache.delete(name);
      state.thumbCache.set(name, img);
    }

    if (img.complete && img.naturalWidth) {
      const pad = 2;
      timelineCtx.drawImage(img, slot.x + pad, slot.y + pad, slot.w - pad * 2, slot.h - pad * 2);
    }

    if (isPendingDelete) {
      timelineCtx.strokeStyle = DELETE_MARK_BORDER;
      timelineCtx.lineWidth = 3;
      timelineCtx.strokeRect(slot.x + 1, slot.y + 1, slot.w - 2, slot.h - 2);
      timelineCtx.lineWidth = 1;
    }

    if (entry.idx === state.idx) {
      timelineCtx.strokeStyle = "#00c8ff";
      timelineCtx.lineWidth = 2;
      timelineCtx.strokeRect(slot.x - 1, slot.y - 1, slot.w + 2, slot.h + 2);
      timelineCtx.lineWidth = 1;
    }

    state.timelineRegions.push(slot);
    drawX += TIMELINE_SLOT_W + TIMELINE_GAP;
  }

  while (state.thumbCache.size > THUMB_CACHE_LIMIT) {
    const oldestKey = state.thumbCache.keys().next().value;
    if (oldestKey == null) break;
    state.thumbCache.delete(oldestKey);
  }
}

function draw() {
  updateStatus();
  drawImageCanvas();
  renderSubjectList();
  drawTimeline();
}

function parseYolo(raw) {
  const imgW = state.image.naturalWidth;
  const imgH = state.image.naturalHeight;
  const boxes = [];
  for (const line of raw.split(/\r?\n/)) {
    const parts = line.trim().split(/\s+/);
    if (parts.length !== 5) continue;
    const clsId = Number.parseInt(Number.parseFloat(parts[0]), 10);
    const xc = Number.parseFloat(parts[1]);
    const yc = Number.parseFloat(parts[2]);
    const bw = Number.parseFloat(parts[3]);
    const bh = Number.parseFloat(parts[4]);
    if (![clsId, xc, yc, bw, bh].every(Number.isFinite)) continue;
    const x1 = clamp(Math.round((xc - bw / 2) * imgW), 0, imgW - 1);
    const y1 = clamp(Math.round((yc - bh / 2) * imgH), 0, imgH - 1);
    const x2 = clamp(Math.round((xc + bw / 2) * imgW), 0, imgW - 1);
    const y2 = clamp(Math.round((yc + bh / 2) * imgH), 0, imgH - 1);
    if (x2 - x1 >= 2 && y2 - y1 >= 2) boxes.push(normalizeBox({ cls_id: clsId, x1, y1, x2, y2 }));
  }
  return boxes;
}

async function loadIndex(idx) {
  const requestedIdx = state.imageCount ? ((idx % state.imageCount) + state.imageCount) % state.imageCount : Math.max(0, idx);
  state.imageLoaded = false;
  state.selectedIdx = null;
  state.dirty = false;
  resetZoom();
  const stateResp = await fetch(`/api/state?idx=${requestedIdx}`);
  const stateData = await stateResp.json();
  state.imageCount = stateData.totalImages ?? 0;
  state.classes = stateData.classes ?? state.classes;
  state.pendingDeletes = new Set(stateData.pendingDeletes ?? []);
  if (!state.imageCount || stateData.currentName == null) {
    state.idx = 0;
    state.currentName = "";
    state.boxes = [];
    state.timelineEntries = [];
    statusEl.textContent = "No images found.";
    draw();
    return;
  }
  state.idx = stateData.currentIndex ?? requestedIdx;
  state.currentName = stateData.currentName;
  const labelPromise = fetch(labelUrlByIndex(state.idx)).then(r => r.text());
  state.image = new Image();
  await new Promise((resolve, reject) => {
    state.image.onload = resolve;
    state.image.onerror = reject;
    state.image.src = `${imageUrlByIndex(state.idx)}?t=${Date.now()}`;
  });
  state.imageLoaded = true;
  const raw = await labelPromise;
  state.boxes = parseYolo(raw);
  state.selectedIdx = state.boxes.length ? 0 : null;
  syncSessionPosition();
  ensureTimelineVisible();
  await loadTimeline();
  draw();
}

async function loadState(startIndex = 0, refresh = false) {
  state.thumbCache.clear();
  state.selectedClass = 0;
  state.timelineEntries = [];
  if (refresh) {
    const resp = await fetch(`/api/state?idx=${Math.max(0, startIndex)}&refresh=1`);
    const data = await resp.json();
    state.imageCount = data.totalImages ?? 0;
    state.classes = data.classes ?? state.classes;
    state.pendingDeletes = new Set(data.pendingDeletes ?? []);
  } else {
    state.imageCount = 0;
  }
  await loadIndex(startIndex);
}

async function saveLabels() {
  if (!state.imageLoaded) return;
  await fetch("/api/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: imageName(),
      width: state.image.naturalWidth,
      height: state.image.naturalHeight,
      boxes: state.boxes.map(normalizeBox),
    }),
  });
  state.dirty = false;
  draw();
}

async function applyDeletes() {
  if (!state.pendingDeletes.size) return;
  await fetch("/api/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ names: pendingDeleteNames() }),
  });
  state.pendingDeletes.clear();
  await loadState(Math.max(0, state.idx), true);
}

async function requestClose() {
  await syncPendingDeletes();
  if (state.pendingDeletes.size) {
    showClosePrompt();
    return;
  }
  await closeEditor(false);
}

async function closeEditor(applyDeletes) {
  hideClosePrompt();
  await syncPendingDeletes();
  if (window.pywebview?.api?.close_editor) {
    await window.pywebview.api.close_editor(Boolean(applyDeletes));
  } else {
    window.close();
  }
}

function setSelectedClass(clsId) {
  const maxClass = Math.max(state.classes.length - 1, clsId, 0);
  state.selectedClass = clamp(clsId, 0, maxClass);
  if (state.selectedIdx != null && state.boxes[state.selectedIdx]) {
    state.boxes[state.selectedIdx].cls_id = state.selectedClass;
    state.dirty = true;
  }
  draw();
}

function cycleClass(delta) {
  const count = Math.max(1, state.classes.length || Math.max(0, ...state.boxes.map(b => b.cls_id)) + 2);
  setSelectedClass((state.selectedClass + delta + count) % count);
}

function removeSelectedBox() {
  if (state.selectedIdx == null) return;
  state.boxes.splice(state.selectedIdx, 1);
  state.selectedIdx = state.boxes.length ? Math.min(state.selectedIdx, state.boxes.length - 1) : null;
  state.dirty = true;
  draw();
}

function clearAllBoxes() {
  if (!state.boxes.length) return;
  state.boxes = [];
  state.selectedIdx = null;
  state.dirty = true;
  draw();
}

function cycleSelection(delta) {
  if (!state.boxes.length) {
    state.selectedIdx = null;
    draw();
    return;
  }

  if (state.selectedIdx == null) {
    state.selectedIdx = delta >= 0 ? 0 : state.boxes.length - 1;
  } else {
    state.selectedIdx = (state.selectedIdx + delta + state.boxes.length) % state.boxes.length;
  }
  state.selectedClass = state.boxes[state.selectedIdx].cls_id;
  draw();
}

imageCanvas.addEventListener("mousedown", event => {
  if (event.button === 1 || event.button === 2) {
    event.preventDefault();
    state.panning = true;
    state.panStart = {
      x: event.clientX,
      y: event.clientY,
      panX: state.panX,
      panY: state.panY,
    };
    return;
  }

  if (event.button !== 0) return;
  const point = canvasToImage(event.offsetX, event.offsetY);
  if (!point) return;

  state.dragging = true;
  state.dragStart = point;

  if (state.addMode) {
    state.boxes.push({ cls_id: state.selectedClass, x1: point.x, y1: point.y, x2: point.x, y2: point.y });
    state.selectedIdx = state.boxes.length - 1;
    state.dragAction = "new";
    state.dirty = true;
    draw();
    return;
  }

  const hit = hitTest(point.x, point.y);
  state.selectedIdx = hit;
  if (hit == null) {
    state.dragAction = null;
    draw();
    return;
  }

  state.selectedClass = state.boxes[hit].cls_id;
  const handle = nearestHandle(state.boxes[hit], point.x, point.y);
  state.dragAction = handle ? "resize" : "move";
  state.dragHandle = handle;
  state.dragOriginalBox = { ...state.boxes[hit] };
  draw();
});

imageCanvas.addEventListener("mousemove", event => {
  if (state.panning && state.panStart) {
    state.panX = state.panStart.panX + (event.clientX - state.panStart.x);
    state.panY = state.panStart.panY + (event.clientY - state.panStart.y);
    draw();
    return;
  }

  if (!state.dragging || state.selectedIdx == null) return;
  const point = canvasToImage(event.offsetX, event.offsetY);
  if (!point) return;
  const box = state.boxes[state.selectedIdx];

  if (state.dragAction === "new") {
    box.x1 = state.dragStart.x;
    box.y1 = state.dragStart.y;
    box.x2 = point.x;
    box.y2 = point.y;
  } else if (state.dragAction === "resize") {
    if (state.dragHandle.includes("l")) box.x1 = point.x;
    if (state.dragHandle.includes("r")) box.x2 = point.x;
    if (state.dragHandle.includes("t")) box.y1 = point.y;
    if (state.dragHandle.includes("b")) box.y2 = point.y;
    Object.assign(box, normalizeBox(box));
  } else if (state.dragAction === "move") {
    const dx = point.x - state.dragStart.x;
    const dy = point.y - state.dragStart.y;
    const original = state.dragOriginalBox;
    const b = normalizeBox(original);
    const bw = b.x2 - b.x1;
    const bh = b.y2 - b.y1;
    const nx1 = clamp(b.x1 + dx, 0, state.image.naturalWidth - 1 - bw);
    const ny1 = clamp(b.y1 + dy, 0, state.image.naturalHeight - 1 - bh);
    box.x1 = nx1;
    box.y1 = ny1;
    box.x2 = nx1 + bw;
    box.y2 = ny1 + bh;
  }

  state.dirty = true;
  draw();
});

function endImageInteraction() {
  state.panning = false;
  state.panStart = null;
  if (state.dragAction === "new" && state.selectedIdx != null) {
    const box = normalizeBox(state.boxes[state.selectedIdx]);
    if (box.x2 - box.x1 < 5 || box.y2 - box.y1 < 5) {
      state.boxes.splice(state.selectedIdx, 1);
      state.selectedIdx = state.boxes.length ? state.boxes.length - 1 : null;
    } else {
      state.boxes[state.selectedIdx] = box;
    }
  }
  state.dragging = false;
  state.dragAction = null;
  state.dragHandle = null;
  state.dragOriginalBox = null;
  draw();
}

imageCanvas.addEventListener("mouseup", endImageInteraction);
imageCanvas.addEventListener("contextmenu", event => event.preventDefault());
imageCanvas.addEventListener("wheel", event => {
  event.preventDefault();
  zoomAt(event.offsetX, event.offsetY, event.deltaY < 0 ? 1.12 : 1 / 1.12);
}, { passive: false });
imageCanvas.addEventListener("dblclick", () => {
  resetZoom();
  draw();
});
window.addEventListener("mouseup", () => {
  if (state.panning || state.dragging) endImageInteraction();
});

timelineCanvas.addEventListener("mousedown", event => {
  const region = state.timelineRegions.find(r => event.offsetX >= r.x && event.offsetX <= r.x + r.w && event.offsetY >= r.y && event.offsetY <= r.y + r.h);
  if (!region) return;
  const name = state.timelineEntries.find(entry => entry.idx === region.idx)?.name ?? "";
  if (state.pendingDeletes.has(name)) {
    clearPendingDelete(name);
  } else {
    loadIndex(region.idx);
  }
});

timelineCanvas.addEventListener("wheel", event => {
  event.preventDefault();
  const step = event.deltaY > 0 ? 1 : -1;
  state.timelineStart += step * 3;
  const maxStart = Math.max(0, state.imageCount - timelineCapacity());
  state.timelineStart = clamp(state.timelineStart, 0, maxStart);
  loadTimeline().then(drawTimeline);
}, { passive: false });

window.addEventListener("resize", resizeCanvases);

function consumeKey(event) {
  event.preventDefault();
  event.stopPropagation();
}

function isEditableTarget(target) {
  return target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement ||
    target?.isContentEditable;
}

function isButtonActivation(event) {
  return event.target instanceof HTMLButtonElement && (event.key === "Enter" || event.key === " ");
}

document.addEventListener("keydown", event => {
  if (event.defaultPrevented) return;
  if (isEditableTarget(event.target) || event.metaKey || event.ctrlKey || event.altKey) return;
  const key = event.key;
  const promptOpen = !closePromptEl.hidden;

  if (promptOpen) {
    if (key === "Escape" || key === "q") {
      consumeKey(event);
      hideClosePrompt();
    } else if (!isButtonActivation(event)) {
      consumeKey(event);
    }
    return;
  }

  if (key === "q" || key === "Escape") { consumeKey(event); requestClose(); }
  else if (key === "n" || key === "ArrowRight") { consumeKey(event); loadIndex(state.idx + 1); }
  else if (key === "b" || key === "ArrowLeft") { consumeKey(event); loadIndex(state.idx - 1); }
  else if (key === "c") { consumeKey(event); loadIndex(state.idx - 5); }
  else if (key === "v") { consumeKey(event); loadIndex(state.idx + 2); }
  else if (key === "x") { consumeKey(event); loadIndex(state.idx - 10); }
  else if (key === "z") { consumeKey(event); zoomAt(imageCanvas.clientWidth / 2, imageCanvas.clientHeight / 2, 1.12); }
  else if (key === "Z") { consumeKey(event); zoomAt(imageCanvas.clientWidth / 2, imageCanvas.clientHeight / 2, 1 / 1.12); }
  else if (key === "r") { consumeKey(event); resetZoom(); draw(); }
  else if (key === "a") { consumeKey(event); state.addMode = !state.addMode; draw(); }
  else if (key === "Tab" || key === "]") { consumeKey(event); cycleSelection(1); }
  else if (key === "[") { consumeKey(event); cycleSelection(-1); }
  else if (key === "+" || key === "=") { consumeKey(event); cycleClass(1); }
  else if (key === "-" || key === "_") { consumeKey(event); cycleClass(-1); }
  else if (/^[0-9]$/.test(key)) { consumeKey(event); setSelectedClass(Number(key)); }
  else if ((key === "Backspace" || key === "Delete") && event.shiftKey) { consumeKey(event); clearAllBoxes(); }
  else if (key === "Backspace" || key === "Delete") { consumeKey(event); removeSelectedBox(); }
  else if (key === "s") { consumeKey(event); saveLabels(); }
  else if (key === "d") { consumeKey(event); markPendingDelete(imageName()); }
  else if (!isButtonActivation(event)) consumeKey(event);
}, true);

rescanBtn.addEventListener("click", () => loadState(state.idx, true));
applyDeletesBtn.addEventListener("click", applyDeletes);
closeBtn.addEventListener("click", requestClose);
closeApplyBtn.addEventListener("click", () => closeEditor(true));
closeDiscardBtn.addEventListener("click", () => closeEditor(false));

resizeCanvases();
loadState(window.START_INDEX || 0);
