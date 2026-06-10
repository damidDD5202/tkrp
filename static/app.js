// Parking Eye demo (auto slots):
// Server returns slot_free/slot_occupied polygons, no calibration.

const video = document.getElementById("video");
const overlay = document.getElementById("overlay");
const ctx = overlay ? overlay.getContext("2d") : null;
const clientFrame = document.getElementById("clientFrame");
const modeBadge = document.getElementById("modeBadge");
const cameraHint = document.getElementById("cameraHint");
const btnStartCamera = document.getElementById("btnStartCamera");
const btnStartCameraToolbar = document.getElementById("btnStartCameraToolbar");

const freeEl = document.getElementById("free");
const totalEl = document.getElementById("total");
const occupiedEl = document.getElementById("occupied");
const statsLineEl = document.getElementById("statsLine");
const vehBox = document.getElementById("vehBox");

const btnReset = document.getElementById("btnReset");
const btnResults = document.getElementById("btnResults");
const btnCopyClientLink = document.getElementById("btnCopyClientLink");
const btnSnapshot = document.getElementById("btnSnapshot");
const btnSettings = document.getElementById("btnSettings");
const btnCapture = document.getElementById("btnCapture");
const btnUpload = document.getElementById("btnUpload");
const filePhoto = document.getElementById("filePhoto");

const results = document.getElementById("results");
const resultsBody = document.getElementById("resultsBody");

// We store last seen auto-slots in memory to support Results panel.
let lastSlots = [];
let visitId = null;

let CLIENT_POLL_MS = 1500;
let cameraReady = false;

function tMonitor(key) {
  return typeof I18n !== "undefined" ? I18n.t(key) : key;
}

function showCameraHint(visible) {
  if (cameraHint) cameraHint.classList.toggle("hidden", !visible);
}

function setCameraReady(ready) {
  cameraReady = !!ready;
  if (btnCapture) btnCapture.disabled = !cameraReady;
}

function getStoredKey(kind) {
  const k = kind === "operator" ? "pe_operator_key" : "pe_client_key";
  return String(localStorage.getItem(k) || "").trim();
}

function setStoredKey(kind, value) {
  const k = kind === "operator" ? "pe_operator_key" : "pe_client_key";
  const v = String(value || "").trim();
  if (!v) localStorage.removeItem(k);
  else localStorage.setItem(k, v);
}

async function fetchJsonWithKey(url, opts = {}, kind = null) {
  const headers = new Headers(opts.headers || {});
  if (kind) {
    const key = getStoredKey(kind);
    if (key) headers.set("x-api-key", key);
  }
  const res = await fetch(url, { ...opts, headers });
  const data = await res.json().catch(() => null);
  return { res, data };
}

async function loadConfig() {
  try {
    let { res, data } = await fetchJsonWithKey("/api/config", { cache: "no-store" }, "operator");
    if (res.status === 401) {
      const k = prompt("Введите ключ оператора (x-api-key) или оставьте пустым", getStoredKey("operator"));
      if (k === null) return;
      setStoredKey("operator", k);
      ({ res, data } = await fetchJsonWithKey("/api/config", { cache: "no-store" }, "operator"));
    }
    if (!res.ok) return;
    const cfg = data?.config || {};
    if (Number.isFinite(cfg.client_poll_ms)) CLIENT_POLL_MS = cfg.client_poll_ms;
  } catch {
    // ignore
  }
}

function getMode() {
  const url = new URL(location.href);
  const m = (url.searchParams.get("mode") || "").toLowerCase();
  if (m === "client") return "client";
  return "source";
}

const MODE = getMode();

function setBadge(text) {
  if (!modeBadge) return;
  modeBadge.textContent = text;
  modeBadge.classList.remove("hidden");
}

function resetAll() {
  lastSlots = [];
  window.__peTotal = 0;
  window.__peFree = 0;
  updateStats();
  render();
}

function updateStats() {
  const total = window.__peTotal ?? 0;
  const free = window.__peFree ?? 0;
  const occupied = Math.max(0, total - free);
  if (freeEl) freeEl.textContent = String(free);
  if (totalEl) totalEl.textContent = String(total);
  if (occupiedEl) occupiedEl.textContent = String(occupied);
  const trHost = document.getElementById("monitorTraffic");
  if (trHost && typeof ParkingFeatures !== "undefined" && total > 0) {
    const pct = free / total;
    const level = pct > 0.3 ? "green" : pct > 0.1 ? "yellow" : "red";
    ParkingFeatures.renderTraffic(trHost, { level, free, total, occupied });
  }
}

function overlaySize() {
  if (!overlay || !ctx) return;
  const rect = overlay.getBoundingClientRect();
  overlay.width = Math.floor(rect.width * devicePixelRatio);
  overlay.height = Math.floor(rect.height * devicePixelRatio);
  ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
}

function fromNorm(ptN) {
  const rect = overlay.getBoundingClientRect();
  return { x: ptN.x * rect.width, y: ptN.y * rect.height };
}

function render() {
  if (!ctx || !overlay) return;
  ctx.clearRect(0, 0, overlay.width, overlay.height);
}

function drawSpotPolygon(pointsNorm, fill, stroke) {
  if (!ctx) return;
  const pts = pointsNorm.map(fromNorm);
  if (pts.length < 3) return;
  ctx.lineWidth = 2;
  ctx.fillStyle = fill;
  ctx.strokeStyle = stroke;
  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  for (const p of pts.slice(1)) ctx.lineTo(p.x, p.y);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
}

function drawAutoSlots(slots) {
  if (!ctx || !overlay) return;
  ctx.clearRect(0, 0, overlay.width, overlay.height);
  let total = 0;
  let occ = 0;

  for (const s of slots) {
    if (!s || !Array.isArray(s.points) || s.points.length < 3) continue;
    const label = String(s.label || "").toLowerCase();
    const isOcc = label === "slot_occupied";
    total++;
    if (isOcc) occ++;
    const fill = isOcc ? "rgba(255,77,77,0.25)" : "rgba(32,213,107,0.25)";
    const stroke = isOcc ? "rgba(255,77,77,0.95)" : "rgba(32,213,107,0.95)";
    drawSpotPolygon(s.points.map(([x, y]) => ({ x, y })), fill, stroke);
  }

  window.__peTotal = total;
  window.__peFree = Math.max(0, total - occ);
  updateStats();
}

function updateStatsLine(text) {
  if (!statsLineEl) return;
  statsLineEl.textContent = text || "";
}

function getVehicleParams() {
  try {
    const raw = localStorage.getItem("pe_vehicle");
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function setVehicleParams(v) {
  localStorage.setItem("pe_vehicle", JSON.stringify(v || {}));
}

async function ensureCheckin() {
  const v = getVehicleParams();
  if (!v) return null;
  if (visitId) return visitId;
  let { res, data } = await fetchJsonWithKey("/api/vehicle/checkin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(v),
  }, "client");
  if (res.status === 401) {
    const k = prompt("Введите ключ клиента (x-api-key) или оставьте пустым", getStoredKey("client"));
    if (k === null) return null;
    setStoredKey("client", k);
    ({ res, data } = await fetchJsonWithKey("/api/vehicle/checkin", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(v),
    }, "client"));
  }
  if (res.ok && data?.ok) {
    visitId = data.visit_id;
    return visitId;
  }
  return null;
}

function renderVehicleBox() {
  if (!vehBox) return;
  const v = getVehicleParams() || { kind: "car", size: "normal", is_ev: false, is_disabled: false, plate: "" };
  vehBox.innerHTML = "";
  const title = document.createElement("div");
  title.className = "nav-title";
  title.textContent = "Автомобиль";

  const line = document.createElement("div");
  line.className = "small";
  line.style.marginTop = "6px";
  line.textContent = `${v.kind || "car"} • ${v.size || "normal"}${v.is_ev ? " • EV" : ""}${v.is_disabled ? " • ♿" : ""}${v.plate ? " • " + v.plate : ""}`;

  const btn = document.createElement("button");
  btn.className = "btn ghost";
  btn.style.marginTop = "8px";
  btn.textContent = "Изменить параметры";
  btn.addEventListener("click", async () => {
    const plate = prompt("Номер (можно пусто)", String(v.plate || ""));
    if (plate === null) return;
    const kind = prompt('Тип: "car"|"suv"|"truck"', String(v.kind || "car"));
    if (kind === null) return;
    const size = prompt('Размер: "compact"|"normal"|"large"', String(v.size || "normal"));
    if (size === null) return;
    const ev = confirm("Электромобиль? OK=да, Отмена=нет");
    const dis = confirm("Льготное/инвалидное? OK=да, Отмена=нет");
    const next = {
      plate: String(plate).trim(),
      kind: String(kind).toLowerCase(),
      size: String(size).toLowerCase(),
      is_ev: !!ev,
      is_disabled: !!dis,
    };
    setVehicleParams(next);
    visitId = null;
    renderVehicleBox();
    await ensureCheckin().catch(() => {});
  });

  vehBox.appendChild(title);
  vehBox.appendChild(line);
  vehBox.appendChild(btn);
}

function renderResults() {
  resultsBody.innerHTML = "";
  const total = window.__peTotal ?? 0;
  const free = window.__peFree ?? 0;
  const occ = Math.max(0, total - free);

  const row = document.createElement("div");
  row.className = "row";
  const left = document.createElement("div");
  left.className = "left";
  const dot = document.createElement("div");
  dot.className = "dot";
  dot.style.background = "var(--green)";
  const label = document.createElement("div");
  label.textContent = `Свободно: ${free} / ${total}`;
  left.appendChild(dot);
  left.appendChild(label);
  const right = document.createElement("div");
  right.style.color = "var(--muted)";
  right.textContent = `Занято: ${occ}`;
  row.appendChild(left);
  row.appendChild(right);
  resultsBody.appendChild(row);
}

function bindToolbar() {
  btnReset?.addEventListener("click", () => {
    resetAll();
  });

  btnResults?.addEventListener("click", () => {
    if (!results) return;
    const visible = !results.classList.contains("hidden");
    if (visible) {
      results.classList.add("hidden");
    } else {
      renderResults();
      results.classList.remove("hidden");
    }
  });

  btnCopyClientLink?.addEventListener("click", async () => {
  const u = new URL(location.href);
  u.searchParams.set("mode", "client");
  const ck = getStoredKey("client");
  if (ck) u.searchParams.set("key", ck);
  const link = u.toString();
  try {
    await navigator.clipboard.writeText(link);
    updateStatsLine("Ссылка скопирована. Отправь её пользователю.");
    if (typeof UI !== "undefined" && typeof I18n !== "undefined") UI.toast(I18n.t("toast.link_copied"), "success");
  } catch {
    updateStatsLine(link);
  }
});

btnSnapshot?.addEventListener("click", async () => {
  try {
    const { res, data } = await fetchJsonWithKey("/api/snapshot", { method: "POST" }, "operator");
    if (!res.ok || !data?.ok) {
      updateStatsLine("Нет данных для снимка (сначала запусти источник).");
      return;
    }
    const s = data.snapshot;
    updateStatsLine(`Снимок сохранён: ${s.name}`);
  } catch {
    updateStatsLine("Не удалось сделать снимок.");
  }
});

btnSettings?.addEventListener("click", async () => {
  // Minimal settings UI via prompts (fast demo).
  // Editable: conf, auto_crop, client_poll_ms
  let cfg = null;
  try {
    let { res: r, data } = await fetchJsonWithKey("/api/config", { cache: "no-store" }, "operator");
    if (r.status === 401) {
      const k = prompt("Введите ключ оператора (x-api-key) или оставьте пустым", getStoredKey("operator"));
      if (k === null) return;
      setStoredKey("operator", k);
      ({ res: r, data } = await fetchJsonWithKey("/api/config", { cache: "no-store" }, "operator"));
    }
    cfg = data?.config;
  } catch {}
  const conf0 = cfg?.conf ?? 0.25;
  const poll0 = cfg?.client_poll_ms ?? CLIENT_POLL_MS;
  const crop0 = cfg?.auto_crop ?? "auto";

  const conf = prompt("CONF (0.01..0.99)", String(conf0));
  if (conf === null) return;
  const poll = prompt("Client poll ms (250..10000) (fallback, если SSE упал)", String(poll0));
  if (poll === null) return;
  const crop = prompt('Auto-crop: "auto" или "off"', String(crop0));
  if (crop === null) return;

  try {
    const { res, data } = await fetchJsonWithKey(
      "/api/config",
      {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conf: Number(conf),
        client_poll_ms: Number(poll),
        auto_crop: String(crop).toLowerCase(),
      }),
      },
      "operator"
    );
    if (!res.ok || !data?.ok) {
      updateStatsLine("Не удалось сохранить настройки.");
      return;
    }
    await loadConfig();
    updateStatsLine(`Настройки сохранены: conf=${data.config.conf}, crop=${data.config.auto_crop}`);
  } catch {
    updateStatsLine("Не удалось сохранить настройки.");
  }
  });
}

async function startCamera() {
  if (!video) throw new Error("no video element");
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("getUserMedia unavailable");
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: { ideal: "environment" } },
    audio: false,
  });
  video.srcObject = stream;
  await video.play();
}

async function requestCamera() {
  if (!navigator.mediaDevices?.getUserMedia) {
    showCameraHint(true);
    updateStatsLine(tMonitor("monitor.no_media_devices"));
    if (typeof UI !== "undefined") UI.toast(tMonitor("monitor.no_media_devices"), "error");
    return false;
  }
  try {
    await startCamera();
    showCameraHint(false);
    setCameraReady(true);
    ensureOverlayMatchesVideo();
    updateStatsLine(tMonitor("monitor.camera_ok"));
    if (typeof UI !== "undefined") UI.toast(tMonitor("monitor.camera_ok"), "success");
    return true;
  } catch (e) {
    console.error("camera", e);
    showCameraHint(true);
    setCameraReady(false);
    updateStatsLine(tMonitor("monitor.camera_fail"));
    if (typeof UI !== "undefined") UI.toast(tMonitor("monitor.camera_fail"), "error");
    return false;
  }
}

function bindSourceModeActions() {
  const onCameraClick = () => {
    requestCamera().catch(() => {});
  };
  btnStartCamera?.addEventListener("click", onCameraClick);
  btnStartCameraToolbar?.addEventListener("click", onCameraClick);

  btnCapture?.addEventListener("click", async () => {
    if (!cameraReady) {
      const ok = await requestCamera();
      if (!ok) return;
    }
    const blob = await captureFrameBlob();
    await runDetectFromBlob(blob);
  });

  btnUpload?.addEventListener("click", () => {
    filePhoto?.click();
  });

  filePhoto?.addEventListener("change", async () => {
    const f = filePhoto.files && filePhoto.files[0];
    filePhoto.value = "";
    if (!f) return;
    await runDetectFromBlob(f);
  });
}

function ensureOverlayMatchesVideo() {
  // Keep overlay aligned with rendered video box.
  overlaySize();
  // Keep last known overlays on resize.
  if (Array.isArray(lastSlots) && lastSlots.length) {
    drawAutoSlots(lastSlots);
  } else {
    render();
  }
}

async function captureFrameBlob() {
  // Capture the current displayed video frame into a JPEG Blob.
  if (video.videoWidth === 0 || video.videoHeight === 0) return null;

  const tmp = document.createElement("canvas");
  tmp.width = video.videoWidth;
  tmp.height = video.videoHeight;
  const tctx = tmp.getContext("2d");
  tctx.drawImage(video, 0, 0, tmp.width, tmp.height);

  return await new Promise((resolve) => tmp.toBlob(resolve, "image/jpeg", 0.8));
}

async function runDetectFromBlob(blob) {
  if (!blob) {
    updateStatsLine("Нет кадра для отправки (камера ещё не готова — подожди секунду или загрузи фото).");
    return false;
  }

  const fd = new FormData();
  fd.append("file", blob, "frame.jpg");

  let { res, data } = await fetchJsonWithKey("/api/detect", { method: "POST", body: fd }, "operator");
  if (res.status === 401) {
    const k = prompt("Введите ключ оператора (x-api-key) или оставьте пустым", getStoredKey("operator"));
    if (k === null) return false;
    setStoredKey("operator", k);
    ({ res, data } = await fetchJsonWithKey("/api/detect", { method: "POST", body: fd }, "operator"));
  }

  if (!res.ok || !data) {
    updateStatsLine(`Детект не удался: HTTP ${res.status}`);
    return false;
  }

  const slots = Array.isArray(data.slots) ? data.slots : [];
  lastSlots = slots;
  drawAutoSlots(slots);
  updateStatsLine(`Фото отправлено: ${new Date((data.ts || Date.now()) * 1000).toLocaleTimeString()} • dt=${data.dt_ms ?? "?"}ms`);
  return true;
}

async function clientFetchLatest() {
  // Use image endpoint for display and JSON endpoint for slots/counts.
  const ck = getStoredKey("client");
  const keyParam = ck ? `&key=${encodeURIComponent(ck)}` : "";
  clientFrame.src = `/api/latest.jpg?ts=${Date.now()}${keyParam}`;
  let { res, data } = await fetchJsonWithKey("/api/latest", { cache: "no-store" }, "client");
  if (res.status === 401) {
    const k = prompt("Введите ключ клиента (x-api-key) или оставьте пустым", getStoredKey("client"));
    if (k === null) return;
    setStoredKey("client", k);
    ({ res, data } = await fetchJsonWithKey("/api/latest", { cache: "no-store" }, "client"));
  }
  if (!res.ok) return;
  const slots = Array.isArray(data.slots) ? data.slots : [];
  lastSlots = slots;
  drawAutoSlots(slots);
  if (data.counts) {
    updateStatsLine(`Обновлено: ${new Date((data.ts || Date.now()) * 1000).toLocaleTimeString()} • dt=${data.dt_ms ?? "?"}ms`);
  }
}

function startClientStream() {
  // Prefer SSE push; fallback to polling.
  const ck = getStoredKey("client");
  const keyParam = ck ? `?key=${encodeURIComponent(ck)}` : "";
  try {
    const es = new EventSource(`/api/stream${keyParam}`);
    es.addEventListener("update", () => {
      clientFetchLatest().catch(() => {});
    });
    es.onerror = () => {
      es.close();
      // fallback polling
      setInterval(() => clientFetchLatest().catch(() => {}), CLIENT_POLL_MS);
    };
  } catch {
    setInterval(() => clientFetchLatest().catch(() => {}), CLIENT_POLL_MS);
  }
}

async function boot() {
  try {
    bindToolbar();
  } catch (e) {
    console.error("bindToolbar", e);
    updateStatsLine("Ошибка кнопок: " + (e?.message || e));
  }

  updateStats();
  if (typeof AppShell !== "undefined") AppShell.syncModeTabs(MODE);
  if (typeof I18n !== "undefined") {
    I18n.apply(document);
    window.__PE_REFRESH_PAGE__ = () => {
      AppShell.syncModeTabs(MODE);
      if (MODE === "client") setBadge(I18n.t("monitor.badge_client"));
      else setBadge(I18n.t("monitor.badge_source"));
    };
  }
  await loadConfig();
  renderVehicleBox();

  window.addEventListener("resize", ensureOverlayMatchesVideo);

  // Register service worker for "Add to Home Screen" (PWA-like)
  if ("serviceWorker" in navigator) {
    try { await navigator.serviceWorker.register("/sw.js"); } catch { /* ignore */ }
  }

  if (MODE === "client") {
    setBadge(typeof I18n !== "undefined" ? I18n.t("monitor.badge_client") : "Client");
    video?.classList.add("hidden");
    clientFrame?.classList.remove("hidden");
    showCameraHint(false);
    btnStartCameraToolbar?.classList.add("hidden");
    btnStartCamera?.classList.add("hidden");
    ensureOverlayMatchesVideo();
    updateStatsLine(typeof I18n !== "undefined" ? I18n.t("monitor.badge_client") : "Режим клиента");
    await clientFetchLatest().catch(() => {});
    startClientStream();
    return;
  }

  setBadge(typeof I18n !== "undefined" ? I18n.t("monitor.badge_source") : "Source");
  clientFrame?.classList.add("hidden");
  video?.classList.remove("hidden");
  btnStartCameraToolbar?.classList.remove("hidden");

  bindSourceModeActions();
  ensureOverlayMatchesVideo();

  // Автозапуск камеры при открытии (как раньше); кнопка — запасной вариант
  const autoOk = await requestCamera();
  if (!autoOk) {
    showCameraHint(true);
    updateStatsLine(tMonitor("monitor.camera_hint"));
  }
}

boot().catch((e) => {
  console.error("monitor boot", e);
  updateStatsLine("Ошибка загрузки мониторинга: " + (e?.message || e));
});

