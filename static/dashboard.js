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
  const loc = I18n.lang === "en" ? "en-US" : "ru-RU";
  return new Date(n * 1000).toLocaleString(loc, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtParkingAge(ts) {
  if (ts == null) return "";
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - Number(ts)));
  if (sec < 60) return I18n.t("dash.just_now");
  if (sec < 3600) return I18n.t("dash.min_ago", { n: Math.floor(sec / 60) });
  return I18n.t("dash.h_ago", { n: Math.floor(sec / 3600) });
}

function renderDashboard(user, data) {
  const root = document.getElementById("dashboardRoot");
  const lead = document.getElementById("welcomeLead");
  if (!root) return;

  const name = user.display_name || user.username;
  if (lead) lead.textContent = I18n.t("dash.lead", { name });

  const p = data?.parking || {};
  const active = Number(data?.bookings_active || 0);
  const next = data?.next_booking;
  const live = !!p.live;

  let nextHtml = `<p class="dash-muted">${esc(I18n.t("dash.no_bookings"))}</p>`;
  if (next) {
    nextHtml = `<p class="dash-next-slot"><strong>${esc(next.slot_id)}</strong></p>
      <p class="dash-muted">${esc(I18n.t("dash.until"))} ${esc(fmtTs(next.end_ts))}</p>`;
  }

  const parkingHtml = live
    ? `<div class="dash-stat-row">
        <div><span class="dash-big dash-big--green">${esc(p.free)}</span><span class="dash-label">${esc(I18n.t("dash.free"))}</span></div>
        <div><span class="dash-big dash-big--red">${esc(p.occupied)}</span><span class="dash-label">${esc(I18n.t("dash.occupied"))}</span></div>
        <div><span class="dash-big">${esc(p.total)}</span><span class="dash-label">${esc(I18n.t("dash.total"))}</span></div>
      </div>
      <p class="dash-muted">${esc(I18n.t("dash.updated"))} ${esc(fmtParkingAge(p.ts))}</p>`
    : `<p class="dash-muted">${esc(I18n.t("dash.no_camera"))}</p>`;

  const adminLink =
    String(user.role).toLowerCase() === "admin"
      ? `<a class="btn ghost" href="/admin.html">${esc(I18n.t("dash.link_admin"))}</a>`
      : "";

  root.innerHTML = `
    <a href="/" class="dash-card panel card dash-card--link">
      <span class="dash-card-icon dash-card-icon--blue">${AppShell.icon("monitor")}</span>
      <h2 class="dash-card-title">${esc(I18n.t("dash.monitor"))}</h2>
      <p class="dash-card-desc">${esc(I18n.t("dash.monitor_desc"))}</p>
      ${live ? `<span class="dash-badge dash-badge--live">Live</span>` : ""}
    </a>
    <a href="/cabinet.html" class="dash-card panel card dash-card--link">
      <span class="dash-card-icon dash-card-icon--green">${AppShell.icon("cabinet")}</span>
      <h2 class="dash-card-title">${esc(I18n.t("dash.cabinet"))}</h2>
      <p class="dash-card-desc">${esc(I18n.t("dash.cabinet_desc"))}</p>
      ${active > 0 ? `<span class="dash-badge">${esc(I18n.t("dash.active_n", { n: active }))}</span>` : ""}
    </a>
    <section class="panel card dash-detail">
      <h2 class="card-title">${esc(I18n.t("dash.parking_now"))}</h2>
      <div id="dashTraffic" class="dash-traffic-wrap"></div>
      ${parkingHtml}
    </section>
    <section class="panel card dash-detail">
      <h2 class="card-title">${esc(I18n.t("dash.next_booking"))}</h2>
      ${nextHtml}
      <a href="/cabinet.html" class="btn ghost btn-sm dash-link-btn">${esc(I18n.t("dash.all_bookings"))}</a>
    </section>
    <section class="panel card dash-quick">
      <h2 class="card-title">${esc(I18n.t("dash.quick_links"))}</h2>
      <div class="quick-links">
        <a class="btn ghost" href="/?mode=source">${esc(I18n.t("dash.link_source"))}</a>
        <a class="btn ghost" href="/?mode=client">${esc(I18n.t("dash.link_client"))}</a>
        ${adminLink}
      </div>
    </section>
  `;
}

async function loadDashboard() {
  const user = window.__PE_USER__;
  if (!user) return;
  const { res, data } = await Auth.fetchJson("/api/me/overview");
  if (!res.ok || !data?.ok) {
    document.getElementById("dashboardRoot").innerHTML =
      `<div class="panel card"><p class="muted">${esc(I18n.t("dash.load_fail"))}</p></div>`;
    return;
  }
  window.__PE_DASHBOARD_DATA__ = data;
  renderDashboard(user, data);
  const trHost = document.getElementById("dashTraffic");
  if (trHost && data?.parking?.traffic) {
    if (typeof ParkingFeatures !== "undefined") ParkingFeatures.renderTraffic(trHost, data.parking.traffic);
  }
}

(async () => {
  const user = await Auth.requireAuth();
  if (!user) return;
  window.__PE_USER__ = user;
  AppShell.mount(user, "dashboard");
  if (typeof I18n !== "undefined") I18n.apply(document);
  await loadDashboard();
  window.__PE_REFRESH_PAGE__ = () => loadDashboard();
})();
