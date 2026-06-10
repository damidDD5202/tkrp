/**
 * Shared session auth for Parking Eye (cookie pe_session).
 */
const Auth = {
  async fetchJson(url, opts = {}, timeoutMs = 60000) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    const userSignal = opts.signal;
    if (userSignal) {
      userSignal.addEventListener("abort", () => ctrl.abort(), { once: true });
    }
    const { signal: _s, ...rest } = opts;
    try {
      const res = await fetch(url, {
        credentials: "same-origin",
        ...rest,
        signal: ctrl.signal,
      });
      const data = await res.json().catch(() => null);
      return { res, data };
    } finally {
      clearTimeout(timer);
    }
  },

  defaultHome: "/dashboard.html",

  safeNextPath(next) {
    const p = String(next || "").trim();
    if (!p.startsWith("/") || p.startsWith("//")) return this.defaultHome;
    if (p.startsWith("/login") || p.startsWith("/register")) return this.defaultHome;
    return p;
  },

  async getSession() {
    try {
      const { res, data } = await this.fetchJson("/api/auth/session", {}, 20000);
      if (res.ok && data?.ok) return data.user || null;
    } catch (e) {
      console.error("session", e);
    }
    return null;
  },

  async login(username, password) {
    return this.fetchJson("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
  },

  async register(username, password, displayName, familyInvite) {
    const body = { username, password };
    if (displayName) body.display_name = displayName;
    if (familyInvite) body.family_invite = familyInvite;
    return this.fetchJson("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  async logout() {
    return this.fetchJson("/api/auth/logout", { method: "POST" });
  },

  async requireAuth() {
    const user = await this.getSession();
    if (user) return user;
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.replace(`/login.html?next=${next}`);
    return null;
  },

  async redirectIfAuthenticated() {
    const user = await this.getSession();
    if (!user) return false;
    const params = new URLSearchParams(window.location.search);
    window.location.replace(this.safeNextPath(params.get("next") || this.defaultHome));
    return true;
  },

  mountUserChrome(user) {
    const label = document.getElementById("userLabel");
    if (label) {
      label.textContent = user.display_name || user.username;
      label.classList.remove("hidden");
    }
    const adminLink = document.getElementById("linkAdmin");
    if (adminLink && String(user.role).toLowerCase() === "admin") {
      adminLink.classList.remove("hidden");
    }
    const btnLogout = document.getElementById("btnLogoutApp");
    if (btnLogout) {
      btnLogout.classList.remove("hidden");
      if (!btnLogout.dataset.bound) {
        btnLogout.dataset.bound = "1";
        btnLogout.addEventListener("click", async () => {
          await Auth.logout();
          window.location.href = "/login.html";
        });
      }
    }
  },

  reasonMessage(reason, fallback) {
    const key = `err.${reason}`;
    if (typeof I18n !== "undefined" && I18n.dict.ru[key]) return I18n.t(key);
    return fallback || (typeof I18n !== "undefined" ? I18n.t("err.generic") : "Error");
  },
};
