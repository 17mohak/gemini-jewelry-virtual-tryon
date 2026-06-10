/* Jewelry Virtual Try-On — minimal frontend logic (no frameworks). */

const state = {
  catalog: [],
  selectedItem: null,
  faceFile: null,
  handFile: null,
  busy: false,
};

const $ = (id) => document.getElementById(id);

const LOADING_MESSAGES = {
  image: "Generating your try-on image with Gemini… (~15–60 s)",
  video: "Image + video requested. Kling video generation can take a few minutes — hang tight…",
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

/* ── Catalog ── */

async function loadCatalog() {
  const grid = $("catalog-grid");
  try {
    const resp = await fetch("/api/catalog");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    state.catalog = await resp.json();
  } catch (err) {
    grid.innerHTML = `<p class="error">Could not load the catalog (${err.message}). Is the backend running?</p>`;
    return;
  }

  grid.innerHTML = "";
  for (const item of state.catalog) {
    const card = document.createElement("div");
    card.className = "catalog-item";
    card.dataset.id = item.id;
    card.innerHTML = `
      <img src="${item.image_url}" alt="${item.name}" loading="lazy" />
      <div class="name">${item.name}</div>
      <span class="badge">${item.type} · needs ${item.photo_kind} photo</span>
    `;
    card.addEventListener("click", () => selectItem(item, card));
    grid.appendChild(card);
  }
}

function selectItem(item, card) {
  document.querySelectorAll(".catalog-item.selected").forEach((el) => el.classList.remove("selected"));
  card.classList.add("selected");
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
    note.textContent = "Pick a jewelry item above to get started.";
    btn.disabled = true;
    return;
  }
  const needed = item.photo_kind; // "face" | "hand"
  const file = needed === "face" ? state.faceFile : state.handFile;
  if (!file) {
    note.textContent = `“${item.name}” is a ${item.type} — it needs your ${needed} photo. Upload it in step 1.`;
    btn.disabled = true;
  } else {
    note.textContent = `Ready: “${item.name}” will be placed on your ${needed} photo.`;
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
loadCatalog();
updateReadiness();
$("tryon-btn").addEventListener("click", tryOn);
