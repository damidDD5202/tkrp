/**
 * Toasts, breadcrumbs, page transitions.
 */
const UI = {
  _toastRoot: null,

  ensureToastRoot() {
    if (this._toastRoot) return this._toastRoot;
    const el = document.createElement("div");
    el.id = "toastRoot";
    el.className = "toast-root";
    el.setAttribute("aria-live", "polite");
    document.body.appendChild(el);
    this._toastRoot = el;
    return el;
  },

  toast(message, type = "info", ms = 3200) {
    const root = this.ensureToastRoot();
    const t = document.createElement("div");
    t.className = `toast toast--${type}`;
    t.textContent = String(message || "");
    root.appendChild(t);
    requestAnimationFrame(() => t.classList.add("is-visible"));
    const remove = () => {
      t.classList.remove("is-visible");
      setTimeout(() => t.remove(), 280);
    };
    setTimeout(remove, ms);
    t.addEventListener("click", remove);
    return t;
  },

  mountBreadcrumbs(items) {
    const host = document.getElementById("breadcrumbs");
    if (!host || !Array.isArray(items) || !items.length) return;
    const parts = items.map((item, i) => {
      const isLast = i === items.length - 1;
      const label = this.esc(item.label || "");
      if (!isLast && item.href) {
        return `<a href="${this.esc(item.href)}">${label}</a><span class="bc-sep" aria-hidden="true">/</span>`;
      }
      return `<span class="bc-current" aria-current="page">${label}</span>`;
    });
    host.innerHTML = parts.join("");
    host.classList.remove("hidden");
  },

  pageEnter() {
    const main = document.querySelector(".app-main");
    if (!main) return;
    const key = `pe-enter:${location.pathname}`;
    if (sessionStorage.getItem(key)) return;
    sessionStorage.setItem(key, "1");
    main.classList.remove("is-entering");
    void main.offsetWidth;
    main.classList.add("is-entering");
  },

  bindPasswordToggle(btnId, inputId) {
    const btn = document.getElementById(btnId);
    const input = document.getElementById(inputId);
    if (!btn || !input) return;
    btn.addEventListener("click", () => {
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      if (typeof I18n !== "undefined") {
        btn.setAttribute("aria-label", I18n.t(show ? "common.hide_password_aria" : "common.show_password_aria"));
        btn.textContent = I18n.t(show ? "common.hide_password" : "common.show_password");
      } else {
        btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
        btn.textContent = show ? "Hide" : "Show";
      }
    });
  },

  esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  },
};
