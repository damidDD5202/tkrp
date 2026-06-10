/**
 * Traffic light, slot map, expiry alerts.
 */
const ParkingFeatures = {
  trafficLabels() {
    const t = (k) => (typeof I18n !== "undefined" ? I18n.t(k) : k);
    return {
      green: t("traffic.green"),
      yellow: t("traffic.yellow"),
      red: t("traffic.red"),
      unknown: t("traffic.unknown"),
    };
  },

  renderTraffic(host, data) {
    if (!host) return;
    const level = String(data?.level || "unknown");
    const labels = this.trafficLabels();
    const free = data?.free ?? "—";
    const total = data?.total ?? "—";
    const parts = [
      '<div class="traffic-light" role="status" aria-live="polite">',
      '<div class="traffic-light__bulbs">',
      `<span class="traffic-light__bulb traffic-light__bulb--red${level === "red" ? " is-on" : ""}" title="${labels.red}"></span>`,
      `<span class="traffic-light__bulb traffic-light__bulb--yellow${level === "yellow" ? " is-on" : ""}" title="${labels.yellow}"></span>`,
      `<span class="traffic-light__bulb traffic-light__bulb--green${level === "green" ? " is-on" : ""}" title="${labels.green}"></span>`,
      "</div>",
      '<div class="traffic-light__meta">',
      `<span class="traffic-light__label">${labels[level] || labels.unknown}</span>`,
      `<span class="traffic-light__counts">${free} / ${total}</span>`,
      "</div>",
      "</div>",
    ];
    host.innerHTML = parts.join("");
  },

  _stateClass(state) {
    const s = String(state || "").toLowerCase();
    if (s === "free") return "slot-map__cell--free";
    if (s === "occupied") return "slot-map__cell--busy";
    if (s === "booked") return "slot-map__cell--booked";
    if (s === "repair" || s === "closed") return "slot-map__cell--closed";
    if (s === "reserved") return "slot-map__cell--reserved";
    return "slot-map__cell--unknown";
  },

  renderSlotMap(host, payload, { onSelect } = {}) {
    if (!host) return;
    const slots = Array.isArray(payload?.slots) ? payload.slots : [];
    if (!slots.length) {
      host.innerHTML = `<p class="small muted">${typeof I18n !== "undefined" ? I18n.t("slotmap.empty") : "Нет данных с камеры"}</p>`;
      return;
    }
    const parts = ['<div class="slot-map" role="list">'];
    for (const s of slots) {
      const id = String(s.id || "");
      const cls = this._stateClass(s.state);
      const title = [id, s.state, s.override_note].filter(Boolean).join(" · ");
      const dis = s.bookable ? "" : " disabled";
      parts.push(
        `<button type="button" class="slot-map__cell ${cls}" data-slot="${encodeURIComponent(id)}" title="${title.replace(/"/g, "&quot;")}"${dis}>${id.replace(/^slot_/, "")}</button>`
      );
    }
    parts.push("</div>");
    host.innerHTML = parts.join("");
    host.querySelectorAll(".slot-map__cell:not([disabled])").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = decodeURIComponent(btn.getAttribute("data-slot") || "");
        if (id && typeof onSelect === "function") onSelect(id, btn);
      });
    });
  },

  /** Admin: click any cell to toggle closed ↔ available. */
  renderAdminSlotMap(host, payload, { onToggle } = {}) {
    if (!host) return;
    const t = (k) => (typeof I18n !== "undefined" ? I18n.t(k) : k);
    const slots = Array.isArray(payload?.slots) ? payload.slots : [];
    if (!slots.length) {
      host.innerHTML = `<p class="small muted">${t("slotmap.empty")}</p>`;
      return;
    }
    const offStatuses = new Set(["repair", "reserved", "closed"]);
    const parts = ['<div class="slot-map slot-map--admin" role="list">'];
    for (const s of slots) {
      const id = String(s.id || "");
      const ov = String(s.override || s.state || "").toLowerCase();
      const adminOff = offStatuses.has(ov);
      const cls = adminOff ? "slot-map__cell--closed slot-map__cell--admin-off" : this._stateClass(s.state);
      const title = [id, s.state, s.override_note].filter(Boolean).join(" · ");
      parts.push(
        `<button type="button" class="slot-map__cell ${cls}" data-slot="${encodeURIComponent(id)}" data-off="${adminOff ? "1" : "0"}" title="${title.replace(/"/g, "&quot;")}">${id.replace(/^slot_/, "")}</button>`
      );
    }
    parts.push("</div>");
    host.innerHTML = parts.join("");
    host.querySelectorAll(".slot-map__cell").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = decodeURIComponent(btn.getAttribute("data-slot") || "");
        if (!id || typeof onToggle !== "function") return;
        const off = btn.getAttribute("data-off") === "1";
        await onToggle(id, off, btn);
      });
    });
  },

  checkExpiryAlerts(bookings, container) {
    if (!container) return;
    const t = (k, v) => (typeof I18n !== "undefined" ? I18n.t(k, v) : k);
    const soon = (bookings || []).filter((b) => {
      if (String(b.status) !== "active") return false;
      const rem = Number(b.remaining_s);
      return Number.isFinite(rem) && rem > 0 && rem <= 900;
    });
    if (!soon.length) {
      container.classList.add("hidden");
      container.innerHTML = "";
      return;
    }
    container.classList.remove("hidden");
    container.innerHTML = soon
      .map((b) => {
        const min = Math.max(1, Math.ceil(Number(b.remaining_s) / 60));
        return `<div class="alert-banner alert-banner--warn">${t("alert.expires_soon", { slot: b.slot_id, min })}</div>`;
      })
      .join("");
  },
};
