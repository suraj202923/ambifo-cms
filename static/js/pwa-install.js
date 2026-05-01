(function () {
  if (!window.isSecureContext) {
    return;
  }

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js").catch(function () {
        // Ignore registration errors to avoid breaking app usage.
      });
    });
  }

  let deferredPrompt = null;
  const installButtons = Array.from(document.querySelectorAll(".install-app-btn"));

  function showInstallButtons() {
    installButtons.forEach(function (btn) {
      btn.style.display = "inline-block";
    });
  }

  function hideInstallButtons() {
    installButtons.forEach(function (btn) {
      btn.style.display = "none";
    });
  }

  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    deferredPrompt = event;
    showInstallButtons();
  });

  installButtons.forEach(function (installBtn) {
    installBtn.addEventListener("click", async function () {
      if (!deferredPrompt) {
        return;
      }
      deferredPrompt.prompt();
      await deferredPrompt.userChoice;
      deferredPrompt = null;
      hideInstallButtons();
    });
  });

  window.addEventListener("appinstalled", function () {
    hideInstallButtons();
  });
})();
