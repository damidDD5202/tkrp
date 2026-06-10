const formRegister = document.getElementById("formRegister");
const registerErr = document.getElementById("registerErr");

function showError(msg) {
  if (!registerErr) return;
  registerErr.textContent = msg || "";
  registerErr.classList.toggle("hidden", !msg);
}

formRegister?.addEventListener("submit", async (e) => {
  e.preventDefault();
  showError("");
  const display_name = document.getElementById("inName").value.trim();
  const username = document.getElementById("inUser").value.trim();
  const password = document.getElementById("inPass").value;
  const password2 = document.getElementById("inPass2").value;
  if (password !== password2) {
    showError(I18n.t("err.password_mismatch"));
    return;
  }
  const family_invite = document.getElementById("inFamilyInvite")?.value?.trim() || "";
  const { res, data } = await Auth.register(username, password, display_name || undefined, family_invite || undefined);
  if (!res.ok || !data?.ok) {
    showError(Auth.reasonMessage(data?.reason, `Ошибка регистрации (${res.status})`));
    return;
  }
  window.location.replace(Auth.defaultHome);
});

UI?.bindPasswordToggle("togglePass", "inPass");
UI?.bindPasswordToggle("togglePass2", "inPass2");

if (typeof I18n !== "undefined") {
  I18n.mountPrefs("#authPrefs");
  I18n.apply(document);
}

(async () => {
  if (await Auth.redirectIfAuthenticated()) return;
})();
