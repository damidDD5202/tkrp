const formLogin = document.getElementById("formLogin");
const loginErr = document.getElementById("loginErr");

function showError(msg) {
  if (!loginErr) return;
  loginErr.textContent = msg || "";
  loginErr.classList.toggle("hidden", !msg);
}

formLogin?.addEventListener("submit", async (e) => {
  e.preventDefault();
  showError("");
  const username = document.getElementById("inUser").value.trim();
  const password = document.getElementById("inPass").value;
  const { res, data } = await Auth.login(username, password);
  if (!res.ok || !data?.ok) {
    let msg = Auth.reasonMessage(data?.reason, `Ошибка входа (${res.status})`);
    if (data?.reason === "blocked" && data?.block_reason) {
      msg = `${msg}: ${data.block_reason}`;
    }
    showError(msg);
    return;
  }
  const params = new URLSearchParams(window.location.search);
  window.location.replace(Auth.safeNextPath(params.get("next") || Auth.defaultHome));
});

UI?.bindPasswordToggle("togglePass", "inPass");

if (typeof I18n !== "undefined") {
  I18n.mountPrefs("#authPrefs");
  I18n.apply(document);
}

(async () => {
  if (await Auth.redirectIfAuthenticated()) return;
})();
