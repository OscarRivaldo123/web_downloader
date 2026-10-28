"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const els = {
  url: $("#url"),
  analyze: $("#analyzeBtn"),
  paste: $("#pasteBtn"),
  error: $("#errorBox"),
  result: $("#result"),
  rows: $("#rows"),
  thumb: $("#thumb"),
  thumbWrap: $("#thumbWrap"),
  duration: $("#duration"),
  title: $("#title"),
  uploader: $("#uploader"),
  platform: $("#platform"),
  history: $("#history"),
  historyList: $("#historyList"),
};

let info = null;
let mode = "video";

const PLATFORM_LABEL = { youtube: "YouTube", instagram: "Instagram", tiktok: "TikTok" };

function showError(message) {
  els.error.textContent = message;
  els.error.hidden = false;
}

function clearError() {
  els.error.hidden = true;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function analyze() {
  const url = els.url.value.trim();
  if (!url) {
    showError("Tempel tautan video terlebih dahulu.");
    els.url.focus();
    return;
  }
  clearError();
  els.analyze.disabled = true;
  els.analyze.textContent = "Memproses…";
  try {
    const res = await fetch("/api/info", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal menganalisis tautan.");
    render(data);
  } catch (err) {
    showError(err.message || "Tidak dapat menghubungi server.");
  } finally {
    els.analyze.disabled = false;
    els.analyze.textContent = "Analisis";
  }
}

function render(data) {
  info = data;
  els.result.hidden = false;
  els.title.textContent = data.title;
  els.uploader.textContent = data.uploader || "Sumber tidak diketahui";
  els.platform.textContent =
    (PLATFORM_LABEL[data.platform] || data.platform) +
    (data.platform === "tiktok" ? " · tanpa watermark" : "");
  els.duration.textContent = data.duration || "";
  els.duration.hidden = !data.duration;
  if (data.thumbnail) {
    els.thumb.src = `/api/thumbnail?url=${encodeURIComponent(data.thumbnail)}`;
    els.thumb.hidden = false;
  } else {
    els.thumb.removeAttribute("src");
    els.thumb.hidden = true;
  }
  els.thumbWrap.classList.toggle("noimg", !data.thumbnail);
  renderRows();
  els.result.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderRows() {
  const list = mode === "video" ? info.videos : info.audios;
  els.rows.innerHTML = "";
  if (!list.length) {
    els.rows.innerHTML =
      `<div class="empty">Tidak ada varian ${mode === "video" ? "video" : "audio"} yang bisa diunduh dari tautan ini.</div>`;
    return;
  }
  list.forEach((opt) => {
    const row = document.createElement("div");
    row.className = "row";

    const head = document.createElement("div");
    head.className = "row-main";

    const q = document.createElement("span");
    q.className = "q";
    q.textContent = opt.label;
    head.appendChild(q);

    if (opt.badge) {
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = opt.badge;
      head.appendChild(badge);
    }
    if (opt.fps && opt.fps > 30) {
      const fps = document.createElement("span");
      fps.className = "badge soft";
      fps.textContent = `${opt.fps} fps`;
      head.appendChild(fps);
    }
    if (mode === "video") {
      const sub = document.createElement("span");
      sub.className = "qsub";
      sub.textContent = opt.progressive ? "MP4" : "MP4 · audio digabung";
      head.appendChild(sub);
    }

    const size = document.createElement("span");
    size.className = "size";
    size.textContent = opt.size;

    const btn = document.createElement("button");
    btn.className = "dl";
    btn.type = "button";
    btn.textContent = "Unduh";
    btn.addEventListener("click", () => startDownload(opt, row));

    row.append(head, size, btn);
    els.rows.appendChild(row);
  });
}

function buildProgress() {
  const bar = document.createElement("div");
  bar.className = "bar";
  bar.innerHTML = `<div class="track"><div class="fill"></div></div><span class="pct">0%</span>`;
  return bar;
}

function setProgress(bar, pct, text) {
  bar.querySelector(".fill").style.width = `${pct}%`;
  bar.querySelector(".pct").textContent = text || `${pct}%`;
}

function saveFile(taskId) {
  const f = document.createElement("iframe");
  f.src = `/api/file/${taskId}`;
  f.style.display = "none";
  document.body.appendChild(f);
  setTimeout(() => f.remove(), 5 * 60 * 1000);
}

async function startDownload(opt, row) {
  const btn = row.querySelector(".dl");
  btn.disabled = true;
  btn.textContent = "Menyiapkan…";

  const body = { url: info.url, mode };
  if (mode === "video") body.quality = opt.height;
  else body.bitrate = opt.bitrate;

  let taskId;
  try {
    const res = await fetch("/api/prepare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal memulai unduhan.");
    taskId = data.task_id;
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Unduh";
    showError(err.message);
    return;
  }

  const bar = buildProgress();
  btn.replaceWith(bar);
  setProgress(bar, 0, "Menunggu…");

  const timer = setInterval(async () => {
    let st;
    try {
      const res = await fetch(`/api/task/${taskId}`);
      st = await res.json();
      if (!res.ok) throw new Error(st.detail || "Tugas hilang dari server.");
    } catch (err) {
      clearInterval(timer);
      failRow(bar, err.message);
      return;
    }

    if (st.status === "downloading" || st.status === "starting") {
      setProgress(bar, st.progress);
    } else if (st.status === "processing") {
      setProgress(bar, 96, "Memproses…");
    } else if (st.status === "ready") {
      clearInterval(timer);
      finishRow(row, bar, taskId, st);
    } else if (st.status === "error") {
      clearInterval(timer);
      failRow(bar, st.error || "Unduhan gagal.");
    }
  }, 900);
}

function finishRow(row, bar, taskId, st) {
  bar.remove();
  const done = document.createElement("button");
  done.className = "dl saved";
  done.type = "button";
  done.textContent = "Simpan File";
  done.title = st.filename ? `${st.filename} · ${st.size}` : "";
  done.addEventListener("click", () => saveFile(taskId));

  const sizeEl = row.querySelector(".size");
  if (sizeEl && st.size && st.size !== "?") sizeEl.textContent = st.size;

  row.appendChild(done);
  saveFile(taskId);
  addHistory(taskId, st);
}

function failRow(bar, message) {
  const note = document.createElement("span");
  note.className = "fail";
  note.textContent = message;
  bar.replaceWith(note);
}

function addHistory(taskId, st) {
  els.history.hidden = false;
  const kind = st.mode === "audio"
    ? `MP3 · ${st.bitrate} kbps · ${st.size}`
    : `MP4 · ${st.quality}p · ${st.size}`;

  const item = document.createElement("div");
  item.className = "history-item";

  const label = document.createElement("div");
  label.className = "h-label";
  label.innerHTML =
    `<strong>${escapeHtml(st.title || "Media")}</strong><small>${escapeHtml(kind)}</small>`;

  const btn = document.createElement("button");
  btn.className = "dl saved";
  btn.type = "button";
  btn.textContent = "Simpan";
  btn.addEventListener("click", () => saveFile(taskId));

  item.append(label, btn);
  els.historyList.prepend(item);
  while (els.historyList.children.length > 8) els.historyList.lastChild.remove();
}

els.analyze.addEventListener("click", analyze);
els.url.addEventListener("keydown", (e) => {
  if (e.key === "Enter") analyze();
});
els.paste.addEventListener("click", async () => {
  try {
    const text = await navigator.clipboard.readText();
    if (text) {
      els.url.value = text.trim();
      analyze();
    }
  } catch {
    els.url.focus();
  }
});

$$(".tab").forEach((tab) => tab.addEventListener("click", () => {
  if (!info) return;
  $$(".tab").forEach((t) => t.classList.toggle("active", t === tab));
  mode = tab.dataset.mode;
  renderRows();
}));
