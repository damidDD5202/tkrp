/**
 * Auth + app shell; then load page script (data-app).
 * Must capture document.currentScript before any await.
 */
(function () {
  const guardScript = document.currentScript;

  (async () => {
    const user = await Auth.requireAuth();
    if (!user) return;
    window.__PE_USER__ = user;

    const page = guardScript?.getAttribute("data-page") || "monitor";
    if (typeof AppShell !== "undefined") {
      AppShell.mount(user, page);
    }

    const appSrc = guardScript?.getAttribute("data-app");
    if (!appSrc) return;

    await new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = appSrc;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error(`Failed to load ${appSrc}`));
      document.body.appendChild(s);
    });
  })().catch((err) => {
    console.error("auth-guard", err);
    const el = document.getElementById("statsLine") || document.querySelector(".app-main");
    if (el) {
      const msg = document.createElement("p");
      msg.className = "small";
      msg.style.color = "#f87171";
      msg.textContent = "Не загрузился скрипт страницы. Обновите (Ctrl+F5).";
      el.prepend(msg);
    }
  });
})();
