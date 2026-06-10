/* Jewelry & Clothing Virtual Try-On — minimal frontend logic (no frameworks). */

const state = {
  mode: "jewelry", // "jewelry" | "clothing"
  catalogs: {}, // mode -> items
  selectedItem: null,
  faceFile: null,
  handFile: null,
  bodyFile: null,
  busy: false,
};

const $ = (id) => document.getElementById(id);

const MODE_CONFIG = {
  jewelry: {
    endpoint: "/api/catalog",
    hint: "Necklaces & earrings are placed on your <strong>face photo</strong>; rings & bracelets on your <strong>hand photo</strong>. Upload whichever the item you pick needs.",
    boxes: ["face", "hand"],
  },
  clothing: {
    endpoint: "/api/catalog/clothing",
    hint: "Clothing is tried on against a <strong>full-body photo</strong> — standing, head to feet, facing the camera.",
    boxes: ["body"],
  },
};

const PHOTO_NOUN = { face: "face", hand: "hand", body: "full-body" };

const LOADING_MESSAGES = {
  image: "Generating your try-on image with Nano Banana… (~15–60 s)",
  video: "Generating the try-on image, then a 6-second LTX video — the video step can take a few minutes…",
};

/* ── Uploads ── */

function wireUpload(kind) {
  const input = $(`${kind}-input`);
  const box = $(`${kind}-box`);
  const preview = $(`${kind}-preview`);
  const placeholder = $(`${kind}-placeholder`);

  input.addEventListener("change", () => {
    const file = input.files[0];
    if (!file) return;
    if (file.size > 8 * 1024 * 1024) {
      showError("That photo is over 8 MB — please choose a smaller one.");
      input.value = "";
      return;
    }
    state[`${kind}File`] = file;
    preview.src = URL.createObjectURL(file);
    preview.hidden = false;
    placeholder.hidden = true;
    box.classList.add("filled");
    hideError();
    updateReadiness();
  });
}

/* ── Mode switch ── */

function setMode(mode) {
  if (state.mode === mode || state.busy) return;
  state.mode = mode;
  state.selectedItem = null;

  for (const m of ["jewelry", "clothing"]) {
    const btn = $(`mode-${m}`);
    btn.classList.toggle("active", m === mode);
    btn.setAttribute("aria-selected", String(m === mode));
  }
  $("upload-hint").innerHTML = MODE_CONFIG[mode].hint;
  for (const kind of ["face", "hand", "body"]) {
    $(`${kind}-box`).hidden = !MODE_CONFIG[mode].boxes.includes(kind);
  }
  hideError();
  loadCatalog();
  updateReadiness();
}

/* ── Catalog ── */

async function loadCatalog() {
  const mode = state.mode;
  const grid = $("catalog-grid");

  if (!state.catalogs[mode]) {
    grid.innerHTML = '<p class="muted">Loading catalog…</p>';
    try {
      const resp = await fetch(MODE_CONFIG[mode].endpoint);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      state.catalogs[mode] = await resp.json();
    } catch (err) {
      grid.innerHTML = `<p class="error">Could not load the catalog (${err.message}). Is the backend running?</p>`;
      return;
    }
  }
  if (state.mode !== mode) return; // user switched again while fetching

  grid.innerHTML = "";
  for (const item of state.catalogs[mode]) {
    const card = document.createElement("div");
    card.className = "catalog-item";
    card.dataset.id = item.id;
    card.setAttribute("role", "option");
    card.setAttribute("tabindex", "0");
    card.setAttribute("aria-selected", "false");
    card.innerHTML = `
      <img src="${item.image_url}" alt="${item.name}" loading="lazy" />
      <div class="name">${item.name}</div>
      <span class="badge">${item.type} · needs ${PHOTO_NOUN[item.photo_kind]} photo</span>
    `;
    const select = () => selectItem(item, card);
    card.addEventListener("click", select);
    card.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        select();
      }
    });
    grid.appendChild(card);
  }
}

function selectItem(item, card) {
  document.querySelectorAll(".catalog-item.selected").forEach((el) => {
    el.classList.remove("selected");
    el.setAttribute("aria-selected", "false");
  });
  card.classList.add("selected");
  card.setAttribute("aria-selected", "true");
  state.selectedItem = item;
  hideError();
  updateReadiness();
}

/* ── Readiness / requirement note ── */

function updateReadiness() {
  const note = $("requirement-note");
  const btn = $("tryon-btn");
  const item = state.selectedItem;

  if (!item) {
    note.textContent = "Pick an item above to get started.";
    btn.disabled = true;
    return;
  }
  const needed = item.photo_kind; // "face" | "hand" | "body"
  const file = state[`${needed}File`];
  const noun = PHOTO_NOUN[needed];
  if (!file) {
    note.textContent = `“${item.name}” is a ${item.type} — it needs your ${noun} photo. Upload it in step 1.`;
    btn.disabled = true;
  } else {
    note.textContent = `Ready: “${item.name}” will be placed on your ${noun} photo.`;
    btn.disabled = state.busy;
  }
}

/* ── Try-on flow ── */

async function tryOn() {
  const item = state.selectedItem;
  if (!item || state.busy) return;

  const wantVideo = $("video-toggle").checked;
  const form = new FormData();
  form.append("item_id", item.id);
  form.append("generate_video", wantVideo ? "true" : "false");
  if (state.faceFile) form.append("face_photo", state.faceFile);
  if (state.handFile) form.append("hand_photo", state.handFile);
  if (state.bodyFile) form.append("body_photo", state.bodyFile);

  setBusy(true, wantVideo ? LOADING_MESSAGES.video : LOADING_MESSAGES.image);

  try {
    const resp = await fetch("/api/tryon", { method: "POST", body: form });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(data.detail || `Request failed (HTTP ${resp.status})`);
    }
    showResults(data);
  } catch (err) {
    showError(err.message || "Something went wrong. Please try again.");
  } finally {
    setBusy(false);
  }
}

/* ── UI helpers ── */

function setBusy(busy, message) {
  state.busy = busy;
  $("tryon-btn").disabled = busy || !state.selectedItem;
  $("result-card").hidden = false;
  $("loading").hidden = !busy;
  if (busy) {
    $("loading-text").textContent = message;
    $("results").hidden = true;
    hideError();
  }
  updateReadiness();
}

function showResults(data) {
  $("results").hidden = false;
  $("result-image").src = data.image_url + `?t=${Date.now()}`;

  const videoFig = $("video-figure");
  const videoErr = $("video-error");
  if (data.video_url) {
    $("result-video").src = data.video_url + `?t=${Date.now()}`;
    videoFig.hidden = false;
    videoErr.hidden = true;
  } else {
    videoFig.hidden = true;
    if (data.video_error) {
      videoErr.textContent = `The try-on image was generated, but the video step failed: ${data.video_error}`;
      videoErr.hidden = false;
    } else {
      videoErr.hidden = true;
    }
  }

  $("prompt-text").textContent = data.prompt || "";
  $("result-card").scrollIntoView({ behavior: "smooth" });
}

function showError(message) {
  const box = $("error-box");
  box.textContent = message;
  box.hidden = false;
  $("result-card").hidden = false;
}

function hideError() {
  $("error-box").hidden = true;
}

/* ── Init ── */

wireUpload("face");
wireUpload("hand");
wireUpload("body");
loadCatalog();
updateReadiness();
$("tryon-btn").addEventListener("click", tryOn);
$("mode-jewelry").addEventListener("click", () => setMode("jewelry"));
$("mode-clothing").addEventListener("click", () => setMode("clothing"));
