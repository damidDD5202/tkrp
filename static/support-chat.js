/**
 * Support chat: user ↔ admin (HTTP poll).
 */
const SupportChat = {
  esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  },

  t(k, v) {
    return typeof I18n !== "undefined" ? I18n.t(k, v) : k;
  },

  fmtTs(ts) {
    const n = Number(ts);
    if (!Number.isFinite(n)) return "";
    const loc = typeof I18n !== "undefined" && I18n.lang === "en" ? "en-US" : "ru-RU";
    return new Date(n * 1000).toLocaleString(loc, { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "short" });
  },

  renderLog(host, messages, selfRole) {
    if (!host) return 0;
    const list = Array.isArray(messages) ? messages : [];
    if (!list.length) {
      host.innerHTML = `<p class="support-chat__empty small muted">${this.esc(this.t("support.empty"))}</p>`;
      return 0;
    }
    let maxId = 0;
    const parts = list.map((m) => {
      const id = Number(m.id) || 0;
      if (id > maxId) maxId = id;
      const mine = String(m.from_role) === selfRole;
      const cls = mine ? "support-chat__msg support-chat__msg--mine" : "support-chat__msg support-chat__msg--other";
      return `<div class="${cls}" data-id="${id}"><div class="support-chat__bubble">${this.esc(m.body)}</div><time class="support-chat__time muted">${this.esc(this.fmtTs(m.created_ts))}</time></div>`;
    });
    host.innerHTML = parts.join("");
    host.scrollTop = host.scrollHeight;
    return maxId;
  },

  mergeMessages(existing, incoming) {
    const byId = new Map();
    for (const m of existing || []) byId.set(Number(m.id), m);
    for (const m of incoming || []) byId.set(Number(m.id), m);
    return [...byId.values()].sort((a, b) => Number(a.id) - Number(b.id));
  },

  mountUser({ logEl, formEl, inputEl }) {
    let messages = [];
    let lastId = 0;
    let timer = null;

    const refresh = async () => {
      const q = lastId > 0 ? `?since_id=${lastId}` : "";
      const { res, data } = await Auth.fetchJson(`/api/me/support/messages${q}`);
      if (!res.ok || !data?.ok) return;
      const incoming = data.messages || [];
      if (incoming.length) {
        messages = this.mergeMessages(messages, incoming);
        lastId = this.renderLog(logEl, messages, "user");
      } else if (!messages.length) {
        this.renderLog(logEl, [], "user");
      }
    };

    formEl?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = inputEl?.value.trim();
      if (!text) return;
      const { res, data } = await Auth.fetchJson("/api/me/support/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: text }),
      });
      if (!res.ok) {
        UI?.toast(this.t("support.send_fail"), "error");
        return;
      }
      inputEl.value = "";
      if (data?.message) {
        messages = this.mergeMessages(messages, [data.message]);
        lastId = this.renderLog(logEl, messages, "user");
      } else {
        await refresh();
      }
    });

    const start = () => {
      void refresh();
      if (timer) clearInterval(timer);
      timer = setInterval(() => void refresh(), 4000);
    };
    const stop = () => {
      if (timer) clearInterval(timer);
      timer = null;
    };
    start();
    return { refresh, stop };
  },

  mountAdmin({ threadsEl, logEl, formEl, inputEl, titleEl }) {
    let activeUserId = null;
    let messages = [];
    let lastId = 0;
    let timer = null;

    const loadThreads = async () => {
      const { res, data } = await Auth.fetchJson("/api/admin/support/threads");
      if (!res.ok || !data?.ok || !threadsEl) return;
      const threads = data.threads || [];
      if (!threads.length) {
        threadsEl.innerHTML = `<p class="small muted">${this.esc(this.t("support.no_threads"))}</p>`;
        return;
      }
      let html = '<div class="support-chat__threads">';
      for (const th of threads) {
        const active = activeUserId === th.user_id ? " is-active" : "";
        const badge = th.unread > 0 ? `<span class="support-chat__badge">${th.unread}</span>` : "";
        html += `<button type="button" class="support-chat__thread${active}" data-uid="${th.user_id}">
          <span class="support-chat__thread-name">${this.esc(th.display_name)}</span>
          <span class="support-chat__thread-user muted">${this.esc(th.username)}</span>
          <span class="support-chat__thread-preview muted">${this.esc(th.last_body || "")}</span>
          ${badge}
        </button>`;
      }
      html += "</div>";
      threadsEl.innerHTML = html;
      threadsEl.querySelectorAll(".support-chat__thread").forEach((btn) => {
        btn.addEventListener("click", () => {
          const uid = Number(btn.getAttribute("data-uid"));
          if (uid) void openThread(uid);
        });
      });
    };

    const openThread = async (userId) => {
      activeUserId = userId;
      messages = [];
      lastId = 0;
      if (logEl) logEl.innerHTML = `<p class="small muted">${this.esc(this.t("cabinet.loading"))}</p>`;
      threadsEl?.querySelectorAll(".support-chat__thread").forEach((b) => {
        b.classList.toggle("is-active", Number(b.getAttribute("data-uid")) === userId);
      });
      const { res, data } = await Auth.fetchJson(`/api/admin/support/threads/${userId}/messages`);
      if (!res.ok || !data?.ok) {
        if (logEl) logEl.innerHTML = `<p class="small muted">${this.esc(this.t("admin.load_fail"))}</p>`;
        return;
      }
      if (titleEl && data.user) {
        titleEl.textContent = `${data.user.display_name} (${data.user.username})`;
      }
      messages = data.messages || [];
      lastId = this.renderLog(logEl, messages, "admin");
      await loadThreads();
    };

    const pollThread = async () => {
      if (!activeUserId) return;
      const q = lastId > 0 ? `?since_id=${lastId}` : "";
      const { res, data } = await Auth.fetchJson(
        `/api/admin/support/threads/${activeUserId}/messages${q}`
      );
      if (!res.ok || !data?.ok) return;
      const incoming = data.messages || [];
      if (incoming.length) {
        messages = this.mergeMessages(messages, incoming);
        lastId = this.renderLog(logEl, messages, "admin");
      }
    };

    formEl?.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!activeUserId) {
        UI?.toast(this.t("support.pick_user"), "warn");
        return;
      }
      const text = inputEl?.value.trim();
      if (!text) return;
      const { res, data } = await Auth.fetchJson(
        `/api/admin/support/threads/${activeUserId}/messages`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ body: text }),
        }
      );
      if (!res.ok) {
        UI?.toast(this.t("support.send_fail"), "error");
        return;
      }
      inputEl.value = "";
      if (data?.message) {
        messages = this.mergeMessages(messages, [data.message]);
        lastId = this.renderLog(logEl, messages, "admin");
      }
      await loadThreads();
    });

    const start = () => {
      void loadThreads();
      if (timer) clearInterval(timer);
      timer = setInterval(() => {
        void loadThreads();
        void pollThread();
      }, 4000);
    };
    const stop = () => {
      if (timer) clearInterval(timer);
      timer = null;
    };
    start();
    return { loadThreads, openThread, stop };
  },
};
