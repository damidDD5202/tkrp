const adminPanel = document.getElementById("adminPanel");
const forbiddenHint = document.getElementById("forbiddenHint");
const summaryJson = document.getElementById("summaryJson");
const usersWrap = document.getElementById("usersWrap");
const bookingsWrap = document.getElementById("bookingsWrap");
const formNewUser = document.getElementById("formNewUser");
const newUserMsg = document.getElementById("newUserMsg");

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fmtTs(ts) {
  const n = Number(ts);
  if (!Number.isFinite(n)) return "—";
  const loc = typeof I18n !== "undefined" && I18n.lang === "en" ? "en-US" : "ru-RU";
  return new Date(n * 1000).toLocaleString(loc);
}

function t(k, v) {
  return typeof I18n !== "undefined" ? I18n.t(k, v) : k;
}

function fmtDay(ts) {
  const n = Number(ts);
  if (!Number.isFinite(n)) return "—";
  const loc = typeof I18n !== "undefined" && I18n.lang === "en" ? "en-US" : "ru-RU";
  return new Date(n * 1000).toLocaleDateString(loc, { day: "2-digit", month: "short" });
}

function fmtMoney(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return "—";
  return `${Math.round(v)} ₽`;
}

function adminStatGrid(items) {
  return `<div class="admin-stat-grid">${items
    .map(
      (it) =>
        `<div class="admin-stat-card admin-stat-card--${esc(it.tone || "default")}"><span class="admin-stat-label">${esc(it.label)}</span><span class="admin-stat-value">${esc(it.value)}</span></div>`
    )
    .join("")}</div>`;
}

function adminBarRow(label, value, max, tone) {
  const v = Number(value) || 0;
  const m = Math.max(1, Number(max) || 1);
  const pct = Math.min(100, Math.round((v / m) * 100));
  return `<div class="admin-bar-row"><span class="admin-bar-label">${esc(label)}</span><div class="admin-bar-track"><div class="admin-bar-fill admin-bar-fill--${esc(tone || "blue")}" style="width:${pct}%"></div></div><span class="admin-bar-num">${esc(String(Math.round(v)))}</span></div>`;
}

async function loadSummary() {
  if (!summaryJson) return;
  const { res, data } = await Auth.fetchJson("/api/admin/summary");
  if (!res.ok || !data?.ok) {
    summaryJson.innerHTML = `<p class="small muted">${esc(t("admin.load_fail"))} (${res.status})</p>`;
    return;
  }
  const hints = Array.isArray(data.detected_slots_hint) ? data.detected_slots_hint : [];
  let html = adminStatGrid([
    { label: t("admin.stat_users"), value: data.users_total ?? 0, tone: "blue" },
    { label: t("admin.stat_bookings"), value: data.bookings_active_now ?? 0, tone: "green" },
    { label: t("admin.stat_detected"), value: hints.length, tone: "yellow" },
  ]);

  const bySlot = Array.isArray(data.active_by_slot) ? data.active_by_slot : [];
  html += `<div class="admin-section-title">${esc(t("admin.active_by_slot"))}</div>`;
  if (bySlot.length) {
    html += `<table class="data-table"><thead><tr><th>${esc(t("admin.th_slot"))}</th><th>${esc(t("admin.th_count"))}</th></tr></thead><tbody>`;
    for (const row of bySlot) {
      html += `<tr><td>${esc(row.slot_id)}</td><td>${esc(row.n)}</td></tr>`;
    }
    html += "</tbody></table>";
  } else {
    html += `<p class="small muted">${esc(t("admin.no_active_slots"))}</p>`;
  }

  if (hints.length) {
    html += `<div class="admin-section-title">${esc(t("admin.detected_slots"))}</div><div class="admin-chips">`;
    for (const s of hints.slice(0, 24)) {
      const id = s.id ?? s.label ?? "?";
      html += `<span class="admin-chip">${esc(id)}</span>`;
    }
    html += "</div>";
  }

  summaryJson.innerHTML = html;
}

async function loadUsers() {
  const { res, data } = await Auth.fetchJson("/api/admin/users");
  if (!res.ok || !data?.ok) {
    usersWrap.innerHTML = `<div class="small muted">${res.status}</div>`;
    return;
  }
  const rows = data.users || [];
  let html =
    `<table class="data-table"><thead><tr><th>ID</th><th>${esc(t("admin.th_login"))}</th><th>${esc(t("admin.th_name"))}</th><th>${esc(t("admin.th_role"))}</th><th>${esc(t("admin.th_active"))}</th><th></th></tr></thead><tbody>`;
  for (const u of rows) {
    const active = !!Number(u.active);
    html += `<tr><td>${esc(u.id)}</td><td>${esc(u.username)}</td><td>${esc(u.display_name)}</td><td>${esc(u.role)}</td><td>${
      active ? esc(t("common.yes")) : esc(t("common.no"))
    }</td><td>`;
    html += `<button type="button" class="btn ghost btn-sm js-toggle" data-id="${esc(u.id)}" data-active="${active ? "0" : "1"}">${active ? esc(t("admin.disable")) : esc(t("admin.enable"))}</button>`;
    if (u.block_reason) html += `<br><span class="small muted">${esc(u.block_reason)}</span>`;
    html += "</td></tr>";
  }
  html += "</tbody></table>";
  usersWrap.innerHTML = html;
  usersWrap.querySelectorAll(".js-toggle").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-id");
      const activeNext = btn.getAttribute("data-active") === "1";
      const body = { active: activeNext };
      if (!activeNext) {
        const reason = window.prompt(t("admin.block_reason"), "") || "";
        body.block_reason = reason.slice(0, 300);
      } else {
        body.block_reason = null;
      }
      const { res } = await Auth.fetchJson(`/api/admin/users/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) UI?.toast(t("toast.user_update_fail"), "error");
      else UI?.toast(t("toast.user_updated"), "success");
      await loadUsers();
      await loadSummary();
    });
  });
}

async function loadBookings() {
  const { res, data } = await Auth.fetchJson("/api/admin/bookings");
  if (!res.ok || !data?.ok) {
    bookingsWrap.innerHTML = `<div class="small muted">${res.status}</div>`;
    return;
  }
  const rows = data.bookings || [];
  if (!rows.length) {
    bookingsWrap.innerHTML = `<div class="small muted">${esc(t("common.empty"))}</div>`;
    return;
  }
  let html =
    `<table class="data-table"><thead><tr><th>${esc(t("admin.th_slot"))}</th><th>${esc(t("admin.th_user"))}</th><th>${esc(t("admin.th_from"))}</th><th>${esc(t("admin.th_to"))}</th><th>${esc(t("admin.th_status"))}</th><th></th></tr></thead><tbody>`;
  for (const b of rows) {
    html += `<tr><td>${esc(b.slot_id)}</td><td>${esc(b.display_name)} (${esc(b.username)})</td><td class="muted">${esc(
      fmtTs(b.start_ts)
    )}</td><td class="muted">${esc(fmtTs(b.end_ts))}</td><td>${esc(b.status)}</td><td><button type="button" class="btn ghost btn-sm js-move" data-id="${esc(String(b.id))}">${esc(t("admin.transfer_slot"))}</button></td></tr>`;
  }
  html += "</tbody></table>";
  bookingsWrap.innerHTML = html;
  bookingsWrap.querySelectorAll(".js-move").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-id");
      const slot_id = window.prompt("slot_id", "slot_1");
      if (!slot_id) return;
      const { res } = await Auth.fetchJson(`/api/admin/bookings/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slot_id: slot_id.trim() }),
      });
      if (!res.ok) UI?.toast(t("msg.booking_fail"), "error");
      else {
        UI?.toast(t("toast.user_updated"), "success");
        await loadBookings();
      }
    });
  });
}

function highlightAdminSlot(slot_id) {
  if (!slot_id) return;
  const mapHost = document.getElementById("adminSlotMap");
  if (!mapHost) return;
  mapHost.querySelectorAll(".slot-map__cell--highlight").forEach((el) => el.classList.remove("slot-map__cell--highlight"));
  const enc = encodeURIComponent(slot_id);
  const btn = mapHost.querySelector(`.slot-map__cell[data-slot="${enc}"]`);
  if (btn) {
    btn.classList.add("slot-map__cell--highlight");
    btn.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

function renderFindPlateResults(matches) {
  const el = document.getElementById("findPlateResult");
  if (!el) return;
  if (!matches.length) {
    el.innerHTML = `<p class="small muted">${esc(t("admin.find_plate_empty"))}</p>`;
    return;
  }
  let html = `<p class="small muted">${esc(t("admin.find_plate_hint"))}</p>`;
  for (const m of matches) {
    const live = m.live_state ? `${t("admin.find_plate_live")}: ${m.live_state}` : "";
    html += `<div class="admin-find-hit">
      <span class="admin-find-hit__slot">${esc(t("admin.find_plate_slot"))} ${esc(m.slot_id)}</span>
      <span>${esc(m.plate)}</span>
      <span class="muted">${esc(m.display_name)} (${esc(m.username)})</span>
      <span class="muted">${esc(t("admin.find_plate_until"))}: ${esc(fmtTs(m.end_ts))}</span>
      ${live ? `<span class="muted">${esc(live)}</span>` : ""}
    </div>`;
  }
  el.innerHTML = html;
  highlightAdminSlot(matches[0].slot_id);
}

async function findByPlate(plate) {
  const el = document.getElementById("findPlateResult");
  const q = String(plate || "").trim();
  if (q.length < 2) {
    if (el) el.innerHTML = `<p class="small muted">${esc(t("admin.find_plate_short"))}</p>`;
    return;
  }
  if (el) el.innerHTML = `<p class="small muted">${esc(t("cabinet.loading"))}</p>`;
  const { res, data } = await Auth.fetchJson(`/api/admin/find-by-plate?plate=${encodeURIComponent(q)}`);
  if (!res.ok || !data?.ok) {
    const reason = data?.reason === "plate_too_short" ? t("admin.find_plate_short") : t("admin.load_fail");
    if (el) el.innerHTML = `<p class="small muted">${esc(reason)}</p>`;
    return;
  }
  renderFindPlateResults(Array.isArray(data.matches) ? data.matches : []);
}

async function setSlotOverride(slot_id, status) {
  const { res } = await Auth.fetchJson(`/api/admin/slot-overrides/${encodeURIComponent(slot_id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  return res.ok;
}

async function loadAdminSlotMap() {
  const mapHost = document.getElementById("adminSlotMap");
  const listEl = document.getElementById("slotOverridesList");
  if (!mapHost) return;
  const { res, data } = await Auth.fetchJson("/api/parking/slots-map");
  if (!res.ok || !data?.ok) {
    mapHost.innerHTML = `<p class="small muted">${esc(t("admin.load_fail"))} (${res.status})</p>`;
    return;
  }
  ParkingFeatures.renderAdminSlotMap(mapHost, data, {
    async onToggle(slot_id, isOff) {
      const next = isOff ? "available" : "closed";
      const ok = await setSlotOverride(slot_id, next);
      if (!ok) {
        UI?.toast(t("msg.booking_fail"), "error");
        return;
      }
      UI?.toast(isOff ? t("admin.slot_enabled", { slot: slot_id }) : t("admin.slot_disabled", { slot: slot_id }), "success");
      await loadAdminSlotMap();
    },
  });
  if (!listEl) return;
  const { res: oRes, data: oData } = await Auth.fetchJson("/api/admin/slot-overrides");
  const rows = oRes.ok && oData?.ok && Array.isArray(oData.overrides) ? oData.overrides : [];
  const off = rows.filter((r) => {
    const st = String(r.status || "").toLowerCase();
    return st && st !== "available" && st !== "free";
  });
  if (!off.length) {
    listEl.innerHTML = `<p class="small muted">${esc(t("admin.slots_all_on"))}</p>`;
    return;
  }
  listEl.innerHTML = `<p class="small">${esc(t("admin.slots_off_list"))}: ${off.map((r) => esc(r.slot_id)).join(", ")}</p>`;
}

async function loadAnalytics() {
  const el = document.getElementById("analyticsJson");
  if (!el) return;
  const { res, data } = await Auth.fetchJson("/api/admin/analytics/occupancy?days=7");
  if (!res.ok || !data?.ok) {
    el.innerHTML = `<p class="small muted">${esc(t("admin.load_fail"))} (${res.status})</p>`;
    return;
  }
  const daily = Array.isArray(data.daily) ? data.daily : [];
  if (!daily.length) {
    el.innerHTML = `<p class="small muted">${esc(t("admin.no_analytics"))}</p>`;
    return;
  }
  const peakMax = Math.max(1, ...daily.map((d) => Number(d.peak_occupied) || 0));
  let html = adminStatGrid([
    { label: t("admin.analytics_days"), value: data.days ?? 7, tone: "blue" },
    {
      label: t("admin.analytics_peak"),
      value: peakMax,
      tone: "red",
    },
  ]);
  html += `<div class="admin-section-title">${esc(t("admin.analytics_daily"))}</div>`;
  html += `<table class="data-table"><thead><tr><th>${esc(t("admin.th_day"))}</th><th>${esc(t("admin.avg_free"))}</th><th>${esc(t("admin.avg_occupied"))}</th><th>${esc(t("admin.peak_occupied"))}</th></tr></thead><tbody>`;
  for (const d of daily.slice(-7)) {
    html += `<tr><td>${esc(fmtDay(d.day))}</td><td>${esc(Math.round(Number(d.avg_free) || 0))}</td><td>${esc(Math.round(Number(d.avg_occupied) || 0))}</td><td>${esc(Math.round(Number(d.peak_occupied) || 0))}</td></tr>`;
  }
  html += "</tbody></table>";
  html += `<div class="admin-section-title">${esc(t("admin.peak_chart"))}</div>`;
  for (const d of daily.slice(-7)) {
    html += adminBarRow(fmtDay(d.day), d.peak_occupied, peakMax, "red");
  }
  el.innerHTML = html;
}

async function loadFinance() {
  const el = document.getElementById("financeJson");
  if (!el) return;
  const { res, data } = await Auth.fetchJson("/api/admin/finance/summary?days=30");
  if (!res.ok || !data?.ok) {
    el.innerHTML = `<p class="small muted">${esc(t("admin.load_fail"))} (${res.status})</p>`;
    return;
  }
  const byDay = Array.isArray(data.by_day) ? data.by_day : [];
  let html = adminStatGrid([
    { label: t("admin.revenue_total"), value: fmtMoney(data.revenue_rub), tone: "green" },
    { label: t("admin.payments_count"), value: data.payments_count ?? 0, tone: "blue" },
    { label: t("admin.tariff_hour"), value: fmtMoney(data.tariff_hour_rub), tone: "yellow" },
  ]);
  html += `<div class="admin-section-title">${esc(t("admin.revenue_by_day"))} (${esc(data.days ?? 30)} ${esc(t("admin.days_short"))})</div>`;
  if (!byDay.length) {
    html += `<p class="small muted">${esc(t("admin.no_payments"))}</p>`;
  } else {
    const maxRev = Math.max(1, ...byDay.map((d) => Number(d.revenue) || 0));
    html += `<table class="data-table"><thead><tr><th>${esc(t("admin.th_day"))}</th><th>${esc(t("admin.revenue"))}</th><th>${esc(t("admin.payments_count"))}</th></tr></thead><tbody>`;
    for (const d of byDay.slice(-14)) {
      html += `<tr><td>${esc(fmtDay(d.day))}</td><td>${esc(fmtMoney(d.revenue))}</td><td>${esc(d.payments)}</td></tr>`;
    }
    html += "</tbody></table>";
    html += `<div class="admin-section-title">${esc(t("admin.revenue_chart"))}</div>`;
    for (const d of byDay.slice(-7)) {
      html += adminBarRow(fmtDay(d.day), d.revenue, maxRev, "green");
    }
  }
  el.innerHTML = html;
}

async function refreshAllAdmin() {
  await Promise.all([loadSummary(), loadUsers(), loadBookings(), loadAdminSlotMap(), loadAnalytics(), loadFinance()]);
}

document.getElementById("formFindPlate")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const plate = document.getElementById("findPlateIn")?.value.trim();
  await findByPlate(plate);
});

formNewUser?.addEventListener("submit", async (e) => {
  e.preventDefault();
  newUserMsg.textContent = "";
  const username = document.getElementById("nuUser").value.trim().toLowerCase();
  const password = document.getElementById("nuPass").value;
  const display_name = document.getElementById("nuName").value.trim();
  const role = document.getElementById("nuRole").value;
  const { res, data } = await Auth.fetchJson("/api/admin/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, display_name, role }),
  });
  if (!res.ok) {
    newUserMsg.textContent = data?.reason === "username_taken" ? t("err.username_taken") : t("msg.user_create_fail");
    return;
  }
  newUserMsg.textContent = t("msg.user_created_id", { id: data.user_id });
  UI?.toast(t("toast.user_created"), "success");
  formNewUser.reset();
  await loadUsers();
  await loadSummary();
});

(async () => {
  const user = await Auth.requireAuth();
  if (!user) return;
  window.__PE_USER__ = user;
  AppShell.mount(user, "admin");
  if (typeof I18n !== "undefined") I18n.apply(document);
  forbiddenHint.classList.add("hidden");
  if (String(user.role).toLowerCase() !== "admin") {
    adminPanel.classList.add("hidden");
    forbiddenHint.classList.remove("hidden");
    return;
  }
  adminPanel.classList.remove("hidden");
  await refreshAllAdmin();
  if (typeof SupportChat !== "undefined") {
    window.__PE_SUPPORT_ADMIN__ = SupportChat.mountAdmin({
      threadsEl: document.getElementById("supportThreads"),
      logEl: document.getElementById("supportAdminLog"),
      formEl: document.getElementById("formSupportAdmin"),
      inputEl: document.getElementById("supportAdminInput"),
      titleEl: document.getElementById("supportThreadTitle"),
    });
  }
  window.__PE_REFRESH_PAGE__ = () => {
    refreshAllAdmin();
    window.__PE_SUPPORT_ADMIN__?.loadThreads?.();
  };
})();
