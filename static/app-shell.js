/**
 * Shared app layout: sidebar (desktop) + bottom nav (mobile).
 */
const AppShell = {
  pages: [
    { id: "dashboard", href: "/dashboard.html", labelKey: "nav.dashboard", shortKey: "nav.dashboard" },
    { id: "monitor", href: "/", labelKey: "nav.monitor", shortKey: "nav.monitor_short" },
    { id: "cabinet", href: "/cabinet.html", labelKey: "nav.cabinet", shortKey: "nav.cabinet" },
    { id: "admin", href: "/admin.html", labelKey: "nav.admin", shortKey: "nav.admin", adminOnly: true },
  ],

  pageMeta: {
    dashboard: { crumbs: [{ labelKey: "nav.dashboard" }] },
    monitor: {
      crumbs: [
        { labelKey: "nav.dashboard", href: "/dashboard.html" },
        { labelKey: "nav.monitor" },
      ],
    },
    cabinet: {
      crumbs: [
        { labelKey: "nav.dashboard", href: "/dashboard.html" },
        { labelKey: "nav.cabinet" },
      ],
    },
    admin: {
      crumbs: [
        { labelKey: "nav.dashboard", href: "/dashboard.html" },
        { labelKey: "nav.admin" },
      ],
    },
  },

  icon(id) {
    const icons = {
      dashboard:
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/></svg>',
      monitor:
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>',
      cabinet:
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 7H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2z"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/></svg>',
      admin:
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>',
    };
    return icons[id] || icons.dashboard;
  },

  mount(user, activePage) {
    const root = document.getElementById("appShell");
    if (!root || !user) return;

    window.__PE_USER__ = user;
    window.__PE_ACTIVE_PAGE__ = activePage;

    const isAdmin = String(user.role).toLowerCase() === "admin";
    const name = user.display_name || user.username;
    const initial = String(name).trim().charAt(0).toUpperCase() || "?";
    const t = (k) => (typeof I18n !== "undefined" ? I18n.t(k) : k);

    const navItems = this.pages
      .filter((p) => !p.adminOnly || isAdmin)
      .map((p) => {
        const active = p.id === activePage ? " is-active" : "";
        const label = t(p.labelKey);
        return `<a class="app-nav-link${active}" href="${p.href}" data-page="${p.id}">
          <span class="app-nav-icon">${this.icon(p.id)}</span>
          <span class="app-nav-label">${this.esc(label)}</span>
        </a>`;
      })
      .join("");

    const bottomItems = this.pages
      .filter((p) => !p.adminOnly || isAdmin)
      .map((p) => {
        const active = p.id === activePage ? " is-active" : "";
        const label = t(p.labelKey);
        const short = t(p.shortKey);
        return `<a class="app-bottom-link${active}" href="${p.href}" title="${this.esc(label)}">
          <span class="app-nav-icon">${this.icon(p.id)}</span>
          <span class="app-bottom-label">${this.esc(short)}</span>
        </a>`;
      })
      .join("");

    root.innerHTML = `
      <aside class="app-sidebar" data-i18n-aria="nav.aria">
        <a class="app-brand" href="/dashboard.html">
          <span class="app-brand-mark">PE</span>
          <span class="app-brand-text" data-i18n="app.name">Parking Eye</span>
        </a>
        <nav class="app-nav">${navItems}</nav>
        <div id="shellPrefs" class="shell-prefs-wrap"></div>
        <div class="app-sidebar-user">
          <div class="app-avatar" aria-hidden="true">${initial}</div>
          <div class="app-user-meta">
            <div class="app-user-name">${this.esc(name)}</div>
            <div class="app-user-role">${this.esc(isAdmin ? t("role.admin") : t("role.user"))}</div>
          </div>
          <button type="button" class="btn ghost btn-sm app-logout" id="shellLogout" data-i18n="common.logout">Log out</button>
        </div>
      </aside>
      <nav class="app-bottom-nav" data-i18n-aria="nav.sections">${bottomItems}</nav>
    `;

    if (typeof I18n !== "undefined") {
      I18n.mountPrefs(document.getElementById("shellPrefs"));
      I18n.apply(root);
    }

    document.getElementById("shellLogout")?.addEventListener("click", async () => {
      await Auth.logout();
      window.location.href = "/login.html";
    });

    document.body.classList.add("has-shell");
    this._ensureBreadcrumbs();
    this._mountCrumbs(activePage);
    if (typeof UI !== "undefined") UI.pageEnter();
  },

  refresh() {
    const user = window.__PE_USER__;
    const page = window.__PE_ACTIVE_PAGE__;
    if (user && page) this.mount(user, page);
  },

  _mountCrumbs(activePage) {
    const meta = this.pageMeta[activePage];
    if (!meta || typeof UI === "undefined" || typeof I18n === "undefined") return;
    const crumbs = meta.crumbs.map((c) => ({
      label: I18n.t(c.labelKey),
      href: c.href,
    }));
    UI.mountBreadcrumbs(crumbs);
  },

  _ensureBreadcrumbs() {
    const main = document.querySelector(".app-main");
    if (!main || document.getElementById("breadcrumbs")) return;
    const nav = document.createElement("nav");
    nav.id = "breadcrumbs";
    nav.className = "breadcrumbs hidden";
    nav.setAttribute("data-i18n-aria", "bc.label");
    main.insertBefore(nav, main.firstChild);
    if (typeof I18n !== "undefined") I18n.apply(nav);
  },

  esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  },

  syncModeTabs(mode) {
    document.querySelectorAll("[data-mode-tab]").forEach((el) => {
      el.classList.toggle("is-active", el.getAttribute("data-mode-tab") === mode);
    });
  },
};

if (typeof I18n !== "undefined") {
  I18n.onChange((e) => {
    if (e.detail?.lang) {
      I18n.apply(document);
      if (window.__PE_ACTIVE_PAGE__) AppShell.refresh();
      if (typeof window.__PE_REFRESH_PAGE__ === "function") window.__PE_REFRESH_PAGE__();
    }
  });
}
