const formBook = document.getElementById("formBook");
const bookingsWrap = document.getElementById("bookingsWrap");
const sessionsWrap = document.getElementById("sessionsWrap");
const displayNameEl = document.getElementById("displayName");
const bookMsg = document.getElementById("bookMsg");
const tariffLine = document.getElementById("tariffLine");
const slotMapHost = document.getElementById("slotMapHost");
const expiryAlerts = document.getElementById("expiryAlerts");

let tariffHour = 120;
let lastBookings = [];
let showBookedByCol = false;
let familyInviteCode = "";
let loyaltyState = null;

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

function formatPlate(plate) {
  const p = String(plate || "").trim();
  return p ? esc(p) : `<span class="muted">${esc(t("cabinet.no_plate"))}</span>`;
}

function formatMoneyRub(sum) {
  const n = Number(sum);
  if (!Number.isFinite(n) || n <= 0) {
    return `<span class="pay-unpaid">${esc(t("cabinet.unpaid"))}</span>`;
  }
  return `${esc(n)} ₽`;
}

function bookingHours(b) {
  return Math.max(0.25, (Number(b.end_ts) - Number(b.start_ts)) / 3600);
}

function redeemCostForHours(hours) {
  const rate = Number(loyaltyState?.points_per_free_hour || 500);
  return Math.ceil(Math.max(0.25, hours) * rate);
}

function formatPayCell(b) {
  const paidN = Number(b.paid_n || 0);
  if (paidN > 0) {
    let html = `<span class="pay-badge">${esc(t("cabinet.paid"))}</span>`;
    if (Number(b.paid_with_points)) {
      html += ` <span class="muted">(${esc(t("cabinet.paid_points"))})</span>`;
    }
    if (b.last_receipt_id) {
      html += ` <button type="button" class="btn ghost btn-sm js-receipt" data-receipt="${esc(String(b.last_receipt_id))}">${esc(t("cabinet.receipt"))}</button>`;
    }
    if (Number(b.paid_sum) > 0) {
      html += ` <span class="pay-estimate">${esc(b.paid_sum)} ₽</span>`;
    }
    return html;
  }
  if (String(b.status) !== "active") {
    return `<span class="muted">—</span>`;
  }
  const est = Number(b.price_estimate_rub);
  const hrs = bookingHours(b);
  const ptsCost = redeemCostForHours(hrs);
  const canPts = loyaltyState && Number(loyaltyState.balance) >= ptsCost;
  let html = `<span class="pay-unpaid">${esc(t("cabinet.unpaid"))}</span>`;
  if (Number.isFinite(est) && est > 0) {
    html += ` <span class="pay-estimate">~${esc(est)} ₽</span>`;
  }
  return { html, canPts, ptsCost, hrs };
}

function formatPayCellHtml(b) {
  const r = formatPayCell(b);
  return typeof r === "string" ? r : r.html;
}

function notify(msg, type = "info") {
  if (typeof UI !== "undefined" && UI.toast) UI.toast(msg, type);
  else window.alert(msg);
}

function bookingErrorMessage(data, status) {
  const reason = data?.reason || data?.detail;
  if (status === 401 || reason === "login_required") return t("msg.session_expired");
  if (status === 404 && reason !== "not_found") return t("msg.payment_api_missing");
  if (reason === "not_active") return t("msg.booking_not_active");
  if (reason === "slot_busy") return t("msg.booking_busy");
  if (reason === "not_found") return t("msg.booking_action_fail") + " (бронь не найдена)";
  if (reason === "already_paid") return t("msg.already_paid", { amount: data?.amount_rub ?? "—" });
  if (reason === "payment_db_error") return t("msg.payment_db_error");
  if (reason) return t("msg.booking_action_fail") + ` (${reason})`;
  return t("msg.booking_action_fail") + (status ? ` (HTTP ${status})` : "");
}

async function fetchJsonTimeout(url, opts = {}, ms = 45000) {
  return Auth.fetchJson(url, opts, ms);
}

function networkErrorMessage(err) {
  if (err?.name === "AbortError") return t("msg.server_busy");
  return t("msg.network_error");
}

let _reloadTablesGen = 0;
let _payBusy = false;

function setWrapLoading(wrap, on) {
  if (!wrap) return;
  if (on) {
    wrap.dataset.loading = "1";
    wrap.innerHTML = `<div class="small muted">${esc(t("cabinet.loading"))}</div>`;
  } else if (wrap.dataset.loading === "1") {
    delete wrap.dataset.loading;
  }
}

function reloadCabinetTables() {
  const gen = ++_reloadTablesGen;
  void Promise.allSettled([loadBookings(), loadSessions()]).then((results) => {
    if (gen !== _reloadTablesGen) return;
    for (const r of results) {
      if (r.status === "rejected") console.error("cabinet reload", r.reason);
    }
  });
}

function confirmPayDialog(amount, slot) {
  const dlg = document.getElementById("payDialog");
  const textEl = document.getElementById("payDialogText");
  const okBtn = document.getElementById("payDialogOk");
  const cancelBtn = document.getElementById("payDialogCancel");
  if (!dlg || !textEl || !okBtn || !cancelBtn || typeof dlg.showModal !== "function") {
    return Promise.resolve(window.confirm(t("pay.confirm", { amount, slot })));
  }
  if (dlg.parentElement !== document.body) {
    document.body.appendChild(dlg);
  }
  textEl.textContent = t("pay.dialog_body", { amount, slot });
  if (typeof I18n !== "undefined") I18n.apply(dlg);
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      okBtn.removeEventListener("click", onOk);
      cancelBtn.removeEventListener("click", onCancel);
      dlg.removeEventListener("close", onNativeClose);
      dlg.removeEventListener("cancel", onNativeCancel);
      resolve(value);
    };
    const onOk = (e) => {
      e.preventDefault();
      e.stopPropagation();
      dlg.returnValue = "ok";
      if (dlg.open) dlg.close();
      else finish(true);
    };
    const onCancel = (e) => {
      e.preventDefault();
      e.stopPropagation();
      dlg.returnValue = "cancel";
      if (dlg.open) dlg.close();
      else finish(false);
    };
    const onNativeClose = () => finish(dlg.returnValue === "ok");
    const onNativeCancel = (e) => {
      e.preventDefault();
      dlg.returnValue = "cancel";
      finish(false);
    };
    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    dlg.addEventListener("close", onNativeClose);
    dlg.addEventListener("cancel", onNativeCancel);
    dlg.returnValue = "cancel";
    dlg.showModal();
    okBtn.focus();
  });
}

function downloadReceipt(receiptId) {
  if (!receiptId) return;
  const v = window.__PE_ASSET_V || "1";
  const a = document.createElement("a");
  a.href = `/api/me/receipt/${encodeURIComponent(receiptId)}.pdf?pev=${encodeURIComponent(v)}`;
  a.download = `${receiptId}.pdf`;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function loadLoyalty() {
  const { res, data } = await Auth.fetchJson("/api/me/loyalty", {}, 15000);
  if (!res.ok || !data?.ok) return;
  loyaltyState = data.loyalty;
  const balEl = document.getElementById("loyaltyBalance");
  const ratesEl = document.getElementById("loyaltyRates");
  const freeEl = document.getElementById("loyaltyFreeHours");
  if (balEl) balEl.textContent = String(loyaltyState.balance ?? 0);
  if (ratesEl) {
    ratesEl.textContent = `${t("loyalty.rate_earn")}: +${loyaltyState.points_per_paid_hour} / ч · ${t("loyalty.rate_redeem")}: ${loyaltyState.points_per_free_hour} / ч`;
  }
  if (freeEl) {
    freeEl.textContent = t("loyalty.free_hours", { n: loyaltyState.can_redeem_hours ?? 0 });
  }
  refreshLoyaltyBookHint();
}

function refreshLoyaltyBookHint() {
  const hint = document.getElementById("loyaltyBookHint");
  const chk = document.getElementById("inRedeemPoints");
  if (!hint || !loyaltyState) return;
  const hours = Number(document.getElementById("inHours")?.value || 3);
  const cost = redeemCostForHours(hours);
  const ok = Number(loyaltyState.balance) >= cost;
  hint.textContent = ok
    ? `${t("loyalty.rate_redeem")}: ${cost} баллов за ${hours} ч`
    : t("msg.insufficient_points");
  hint.classList.toggle("hidden", false);
  if (chk) chk.disabled = !ok;
}

async function runPointsPayment(bookingId, slotLabel, ptsCost) {
  if (_payBusy) return;
  _payBusy = true;
  try {
    const after = Math.max(0, Number(loyaltyState?.balance || 0) - ptsCost);
    const slot = slotLabel || bookingId;
    const ok = window.confirm(t("pay.points_confirm", { cost: ptsCost, slot, after }));
    if (!ok) return;
    notify(t("pay.sending"), "info");
    const payRes = await fetchJsonTimeout(`/api/me/bookings/${encodeURIComponent(bookingId)}/pay`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ redeem_points: true }),
    });
    const { res, data } = payRes;
    if (!res.ok || !data?.ok) {
      notify(
        data?.reason === "insufficient_points" ? t("msg.insufficient_points") : bookingErrorMessage(data, res.status),
        "error"
      );
      return;
    }
    if (data.loyalty) loyaltyState = data.loyalty;
    const msg = t("pay.points_done", { cost: data.points_spent || ptsCost, balance: data.loyalty?.balance ?? "—" });
    notify(msg, "success");
    await loadLoyalty();
    reloadCabinetTables();
  } finally {
    _payBusy = false;
  }
}

async function runMockPayment(bookingId, slotLabel) {
  if (_payBusy) return;
  if (!bookingId) {
    notify(t("msg.booking_action_fail"), "error");
    return;
  }
  _payBusy = true;
  try {
  notify(t("pay.sending"), "info");
  console.info("[PE] payment-quote", bookingId);
  let quoteRes;
  try {
    quoteRes = await fetchJsonTimeout(`/api/me/bookings/${encodeURIComponent(bookingId)}/payment-quote`);
  } catch (e) {
    console.error("payment-quote", e);
    notify(networkErrorMessage(e), "error");
    return;
  }
  const { res: qRes, data: q } = quoteRes;
  if (!qRes.ok || !q?.ok) {
    notify(bookingErrorMessage(q, qRes.status), "error");
    return;
  }
  if (q.already_paid) {
    notify(t("msg.already_paid", { amount: q.amount_rub }), "info");
    if (q.last_receipt_id) downloadReceipt(q.last_receipt_id);
    reloadCabinetTables();
    return;
  }
  const amount = q.amount_rub;
  const slot = slotLabel || q.slot_id || bookingId;
  const ok = await confirmPayDialog(amount, slot);
  if (!ok) return;
  notify(t("pay.sending"), "info");
  let payRes;
  try {
    payRes = await fetchJsonTimeout(`/api/me/bookings/${encodeURIComponent(bookingId)}/pay`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
  } catch (e) {
    console.error("payment-pay", e);
    notify(networkErrorMessage(e), "error");
    return;
  }
  const { res, data } = payRes;
  if (res.status === 409 && data?.reason === "already_paid") {
    notify(t("msg.already_paid", { amount: data.amount_rub }), "info");
    if (data.receipt_id) downloadReceipt(data.receipt_id);
    reloadCabinetTables();
    return;
  }
  if (!res.ok || !data?.ok) {
    notify(bookingErrorMessage(data, res.status), "error");
    return;
  }
  if (data.points_earned) {
    notify(t("pay.done", { amount: data.amount_rub, receipt: data.receipt_id }) + ` (+${data.points_earned} б.)`, "success");
    if (data.loyalty) loyaltyState = data.loyalty;
    await loadLoyalty();
  }
  const msg = t("pay.done", { amount: data.amount_rub, receipt: data.receipt_id });
  if (bookMsg) {
    bookMsg.textContent = msg;
    bookMsg.classList.remove("muted");
  }
  notify(msg, "success");
  downloadReceipt(data.receipt_id);
  reloadCabinetTables();
  } finally {
    _payBusy = false;
  }
}

function bindBookingsActions() {
  if (!bookingsWrap || bookingsWrap.dataset.actionsBound === "1") return;
  bookingsWrap.dataset.actionsBound = "1";
  bookingsWrap.addEventListener("click", async (e) => {
    const btn = e.target.closest(".js-cancel, .js-extend, .js-pay, .js-pay-points");
    if (!btn || btn.disabled) return;
    e.preventDefault();
    e.stopPropagation();
    const id = btn.getAttribute("data-id");
    if (!id) return;

    btn.disabled = true;

    try {
      if (btn.classList.contains("js-cancel")) {
        const { res, data } = await Auth.fetchJson(`/api/me/bookings/${encodeURIComponent(id)}`, {
          method: "DELETE",
        });
        if (!res.ok || !data?.ok) {
          notify(bookingErrorMessage(data, res.status), "error");
          return;
        }
        notify(t("toast.booking_cancelled"), "success");
        await loadBookings();
        await loadSlotMap();
        return;
      }

      if (btn.classList.contains("js-extend")) {
        const { res, data } = await Auth.fetchJson(`/api/me/bookings/${encodeURIComponent(id)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ extend_hours: 1 }),
        });
        if (!res.ok || !data?.ok) {
          notify(bookingErrorMessage(data, res.status), "error");
          return;
        }
        notify(
          data.end_ts
            ? t("msg.booking_extended_ok", { until: fmtTs(data.end_ts) })
            : t("toast.extended"),
          "success"
        );
        await loadBookings();
        return;
      }

      if (btn.classList.contains("js-pay-points")) {
        const slotLabel = btn.getAttribute("data-slot") || "";
        const cost = Number(btn.getAttribute("data-cost") || 0);
        await runPointsPayment(id, slotLabel, cost);
        return;
      }

      if (btn.classList.contains("js-pay")) {
        btn.disabled = false;
        const slotLabel = btn.getAttribute("data-slot") || "";
        await runMockPayment(id, slotLabel);
        return;
      }
    } catch (err) {
      console.error(err);
      notify(t("msg.booking_action_fail"), "error");
    } finally {
      btn.disabled = false;
    }
  });
}

async function refreshTariffLine() {
  const hours = Number(document.getElementById("inHours")?.value || 3);
  if (!tariffLine) return;
  const { res, data } = await Auth.fetchJson("/api/tariff/calc", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ hours }),
  });
  if (!res.ok || !data?.ok) {
    tariffLine.textContent = "";
    return;
  }
  tariffHour = Number(data.hour_rub) || tariffHour;
  tariffLine.textContent = t("cabinet.tariff_calc", {
    price: data.price_rub,
    rate: data.hour_rub,
  });
  tariffLine.classList.remove("muted");
}

async function loadSlotMap() {
  if (!slotMapHost) return;
  const { res, data } = await Auth.fetchJson("/api/parking/slots-map");
  if (!res.ok || !data?.ok) {
    slotMapHost.innerHTML = `<p class="small muted">${esc(t("slotmap.empty"))}</p>`;
    return;
  }
  ParkingFeatures.renderSlotMap(slotMapHost, data, {
    onSelect(id) {
      const inp = document.getElementById("inSlotId");
      if (inp) inp.value = id;
      inp?.focus();
    },
  });
}

async function loadFamily(user) {
  const membersEl = document.getElementById("familyMembers");
  const inviteBlock = document.getElementById("familyInviteBlock");
  const codeEl = document.getElementById("familyInviteCode");
  if (!membersEl) return;
  let fam = user?.family;
  if (!fam) {
    const { res, data } = await Auth.fetchJson("/api/me/family", {}, 15000);
    if (res.ok && data?.family) fam = data.family;
  }
  if (!fam) {
    membersEl.innerHTML = "";
    if (inviteBlock) inviteBlock.classList.add("hidden");
    return;
  }
  showBookedByCol = Array.isArray(fam.members) && fam.members.length > 1;
  const rows = (fam.members || [])
    .map((m) => {
      const role =
        m.family_role === "owner" ? "owner" : "member";
      const tag = role === "owner" ? " ★" : "";
      return `<li>${esc(m.display_name || m.username)} <span class="muted">(${esc(m.username)})${tag}</span></li>`;
    })
    .join("");
  membersEl.innerHTML = `<p class="small"><strong>${esc(t("cabinet.family_members"))}</strong></p><ul class="family-members-list">${rows}</ul>`;
  if (fam.is_owner && fam.invite_code) {
    familyInviteCode = String(fam.invite_code);
    if (inviteBlock) inviteBlock.classList.remove("hidden");
    if (codeEl) codeEl.textContent = familyInviteCode;
  } else if (inviteBlock) {
    inviteBlock.classList.add("hidden");
  }
}

function bindFamilyActions() {
  document.getElementById("btnFamilyCopy")?.addEventListener("click", async () => {
    if (!familyInviteCode) return;
    try {
      await navigator.clipboard.writeText(familyInviteCode);
      notify(t("toast.family_code_copied"), "success");
    } catch {
      notify(familyInviteCode, "info");
    }
  });
  document.getElementById("btnFamilyRefresh")?.addEventListener("click", async () => {
    const { res, data } = await Auth.fetchJson("/api/me/family/invite", { method: "POST" });
    if (!res.ok || !data?.ok) {
      notify(Auth.reasonMessage(data?.reason, t("err.generic")), "error");
      return;
    }
    familyInviteCode = String(data.invite_code || "");
    const codeEl = document.getElementById("familyInviteCode");
    if (codeEl) codeEl.textContent = familyInviteCode;
    notify(t("toast.family_code_refreshed"), "success");
  });
}

async function loadBookings() {
  if (!bookingsWrap) return;
  const { res, data } = await Auth.fetchJson("/api/me/bookings", {}, 15000);
  if (!res.ok || !data?.ok) {
    bookingsWrap.innerHTML = `<div class="small muted">${esc(t("msg.bookings_load_fail"))} (${res.status})</div>`;
    delete bookingsWrap.dataset.loading;
    return;
  }
  lastBookings = Array.isArray(data.bookings) ? data.bookings : [];
  ParkingFeatures.checkExpiryAlerts(lastBookings, expiryAlerts);
  if (!lastBookings.length) {
    bookingsWrap.innerHTML = `<div class="small muted">${esc(t("msg.bookings_empty"))}</div>`;
    delete bookingsWrap.dataset.loading;
    return;
  }
  const byTh = showBookedByCol ? `<th>${esc(t("cabinet.col_booked_by"))}</th>` : "";
  let html =
    `<table class="data-table"><thead><tr><th>${esc(t("admin.th_slot"))}</th>${byTh}<th>${esc(t("cabinet.plate"))}</th><th>${esc(t("admin.th_from"))}</th><th>${esc(t("admin.th_to"))}</th><th>${esc(t("admin.th_status"))}</th><th>${esc(t("cabinet.col_payment"))}</th><th>${esc(t("cabinet.col_actions"))}</th></tr></thead><tbody>`;
  for (const b of lastBookings) {
    const canAct = String(b.status) === "active";
    const paidN = Number(b.paid_n || 0);
    const isPaid = paidN > 0;
    const payInfo = formatPayCell(b);
    const payCell = formatPayCellHtml(b);
    const byTd = showBookedByCol
      ? `<td class="muted">${esc(b.booked_by_name || b.booked_by_username || "—")}</td>`
      : "";
    html += `<tr><td>${esc(b.slot_id)}</td>${byTd}<td>${formatPlate(b.plate)}</td><td class="muted">${esc(fmtTs(b.start_ts))}</td><td class="muted">${esc(
      fmtTs(b.end_ts)
    )}</td><td>${esc(b.status)}</td><td>${payCell}</td><td class="table-actions">`;
    if (canAct) {
      html += `<button type="button" class="btn ghost btn-sm js-extend" data-id="${esc(String(b.id))}">${esc(t("cabinet.extend"))}</button> `;
      if (!isPaid) {
        if (payInfo.canPts) {
          html += `<button type="button" class="btn ghost btn-sm js-pay-points" data-id="${esc(String(b.id))}" data-slot="${esc(String(b.slot_id))}" data-cost="${esc(String(payInfo.ptsCost))}">${esc(t("cabinet.pay_points"))}</button> `;
        }
        html += `<button type="button" class="btn ghost btn-sm js-pay" data-id="${esc(String(b.id))}" data-slot="${esc(String(b.slot_id))}">${esc(t("cabinet.pay"))}</button> `;
      }
      html += `<button type="button" class="btn ghost btn-sm js-cancel" data-id="${esc(String(b.id))}">${esc(t("common.cancel"))}</button>`;
    } else html += "—";
    html += "</td></tr>";
  }
  html += "</tbody></table>";
  bookingsWrap.innerHTML = html;
  delete bookingsWrap.dataset.loading;
  bookingsWrap.querySelectorAll(".js-receipt").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      downloadReceipt(btn.getAttribute("data-receipt"));
    });
  });
}

async function loadSessions() {
  if (!sessionsWrap) return;
  const { res, data } = await Auth.fetchJson("/api/me/sessions", {}, 15000);
  if (!res.ok || !data?.ok) {
    sessionsWrap.innerHTML = `<div class="small muted">${res.status}</div>`;
    delete sessionsWrap.dataset.loading;
    return;
  }
  const rows = data.sessions || [];
  if (!rows.length) {
    sessionsWrap.innerHTML = `<div class="small muted">${esc(t("common.empty"))}</div>`;
    delete sessionsWrap.dataset.loading;
    return;
  }
  let html =
    `<table class="data-table"><thead><tr><th>${esc(t("admin.th_slot"))}</th><th>${esc(t("cabinet.plate"))}</th><th>${esc(t("admin.th_status"))}</th><th>${esc(t("admin.th_to"))}</th><th>₽</th></tr></thead><tbody>`;
  for (const s of rows) {
    html += `<tr><td>${esc(s.slot_id)}</td><td>${formatPlate(s.plate)}</td><td>${esc(s.status)}</td><td class="muted">${esc(
      fmtTs(s.end_ts)
    )}</td><td>${formatMoneyRub(s.paid_sum)}</td></tr>`;
  }
  html += "</tbody></table>";
  sessionsWrap.innerHTML = html;
  delete sessionsWrap.dataset.loading;
}

formBook?.addEventListener("submit", async (e) => {
  e.preventDefault();
  bookMsg.textContent = "";
  const slot_id = document.getElementById("inSlotId").value.trim();
  const hours = Number(document.getElementById("inHours").value || 3);
  const note = document.getElementById("inNote").value.trim() || undefined;
  const plate = document.getElementById("inPlate")?.value.trim() || undefined;
  const redeem_points = Boolean(document.getElementById("inRedeemPoints")?.checked);
  const { res, data } = await Auth.fetchJson("/api/me/bookings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slot_id, hours, note, plate, redeem_points }),
  });
  if (res.status === 409 && data?.reason === "slot_busy") {
    bookMsg.textContent = t("msg.booking_busy");
    bookMsg.classList.remove("muted");
    return;
  }
  if (res.status === 409 && data?.reason === "slot_unavailable") {
    bookMsg.textContent = t("msg.slot_unavailable");
    bookMsg.classList.remove("muted");
    return;
  }
  if (res.status === 409 && data?.reason === "insufficient_points") {
    bookMsg.textContent = t("msg.insufficient_points");
    bookMsg.classList.remove("muted");
    return;
  }
  if (!res.ok || !data?.ok) {
    bookMsg.textContent = t("msg.booking_fail");
    return;
  }
  if (data.paid_with_points) {
    bookMsg.textContent = data.message || t("msg.booking_points_ok");
    await loadLoyalty();
  } else {
    bookMsg.textContent = `${t("msg.booking_ok")} ${data.price_rub ? `(${data.price_rub} ₽)` : ""}`;
  }
  bookMsg.classList.add("muted");
  notify(t("toast.booking_created"), "success");
  document.getElementById("inNote").value = "";
  await loadBookings();
  await loadSlotMap();
});

document.getElementById("inHours")?.addEventListener("input", () => {
  refreshTariffLine();
  refreshLoyaltyBookHint();
});

document.getElementById("formPassword")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const pwMsg = document.getElementById("pwMsg");
  if (pwMsg) pwMsg.textContent = "";
  const current_password = document.getElementById("pwCurrent").value;
  const new_password = document.getElementById("pwNew").value;
  const { res, data } = await Auth.fetchJson("/api/auth/change-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ current_password, new_password }),
  });
  if (!res.ok || !data?.ok) {
    const msg =
      data?.reason === "bad_credentials"
        ? t("err.wrong_current_password")
        : Auth.reasonMessage(data?.reason, t("err.generic"));
    if (pwMsg) pwMsg.textContent = msg;
    notify(msg, "error");
    return;
  }
  document.getElementById("formPassword").reset();
  if (pwMsg) pwMsg.textContent = "";
  notify(t("toast.password_updated"), "success");
});

function showCabinetLoadError(msg, withReload) {
  let html = `<div class="small muted">${esc(msg)}</div>`;
  if (withReload) {
    html += `<p style="margin-top:10px"><button type="button" class="btn ghost btn-sm" id="cabinetReloadBtn">${esc(
      t("cabinet.reload")
    )}</button></p>`;
  }
  if (bookingsWrap) bookingsWrap.innerHTML = html;
  if (sessionsWrap) sessionsWrap.innerHTML = html;
  document.getElementById("cabinetReloadBtn")?.addEventListener("click", () => window.location.reload());
}

async function bootCabinet() {
  setWrapLoading(bookingsWrap, true);
  setWrapLoading(sessionsWrap, true);

  if (typeof Auth === "undefined") {
    showCabinetLoadError("auth.js не загрузился. Обновите страницу (Ctrl+F5).", true);
    return;
  }
  const user = await Auth.requireAuth();
    if (!user) return;
    window.__PE_USER__ = user;
    AppShell.mount(user, "cabinet");
    bindBookingsActions();
    if (typeof I18n !== "undefined") I18n.apply(document);
    if (displayNameEl) displayNameEl.textContent = user.display_name || user.username;
    bindFamilyActions();
    await loadFamily(user);
    await loadLoyalty();

  const tr = await Auth.fetchJson("/api/tariff", {}, 15000);
    if (tr.data?.hour_rub) tariffHour = Number(tr.data.hour_rub);

    void refreshTariffLine().catch(() => {});
    void loadSlotMap().catch(() => {});

    const [bRes, sRes] = await Promise.allSettled([loadBookings(), loadSessions()]);
  if (bRes.status === "rejected") {
    console.error(bRes.reason);
    showCabinetLoadError(networkErrorMessage(bRes.reason), true);
  }
    if (sRes.status === "rejected" && sessionsWrap) {
      console.error(sRes.reason);
      sessionsWrap.innerHTML = `<div class="small muted">${esc(networkErrorMessage(sRes.reason))}</div>`;
    }

  const supportPanel = document.getElementById("supportPanel");
  if (String(user.role || "").toLowerCase() === "admin") {
    supportPanel?.classList.add("hidden");
  } else if (typeof SupportChat !== "undefined") {
    window.__PE_SUPPORT_CHAT__ = SupportChat.mountUser({
      logEl: document.getElementById("supportLog"),
      formEl: document.getElementById("formSupport"),
      inputEl: document.getElementById("supportInput"),
    });
  }

  window.__PE_REFRESH_PAGE__ = () => {
    void loadSlotMap().catch(() => {});
    reloadCabinetTables();
    window.__PE_SUPPORT_CHAT__?.refresh?.();
  };
  if (!window.__PE_CABINET_TICK__) {
    window.__PE_CABINET_TICK__ = setInterval(() => {
      if (lastBookings.length) ParkingFeatures.checkExpiryAlerts(lastBookings, expiryAlerts);
    }, 60000);
  }
}

(async () => {
  const bootTimeout = new Promise((_, reject) => {
    setTimeout(() => reject(new Error("boot_timeout")), 25000);
  });
  try {
    await Promise.race([bootCabinet(), bootTimeout]);
  } catch (e) {
    console.error("cabinet init", e);
    const msg = e?.message === "boot_timeout" ? t("msg.server_busy") : networkErrorMessage(e);
    showCabinetLoadError(msg, true);
  }
})();

window.addEventListener("pageshow", (ev) => {
  if (ev.persisted && typeof window.__PE_REFRESH_PAGE__ === "function") {
    window.__PE_REFRESH_PAGE__();
  }
});
