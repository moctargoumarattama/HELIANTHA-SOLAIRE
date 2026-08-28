(function () {
  const DISMISS_KEY = "heliantha-pwa-install-dismissed-at";
  const SHOWN_KEY = "heliantha-pwa-install-shown-at";
  const DISMISS_COOLDOWN_MS = 14 * 24 * 60 * 60 * 1000;
  const SHOWN_COOLDOWN_MS = 7 * 24 * 60 * 60 * 1000;
  let deferredPrompt = null;
  let promptRoot = null;
  let promptCard = null;
  let installed = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;

  const readTimestamp = (key) => {
    try {
      return Number(window.localStorage.getItem(key) || 0);
    } catch (_) {
      return 0;
    }
  };

  const writeTimestamp = (key) => {
    try {
      window.localStorage.setItem(key, String(Date.now()));
    } catch (_) {
      // Ignore storage failures and keep the install flow usable.
    }
  };

  const clearTimestamp = (key) => {
    try {
      window.localStorage.removeItem(key);
    } catch (_) {
      // Ignore storage failures and keep the install flow usable.
    }
  };

  const recentlyDismissed = () => {
    const stored = readTimestamp(DISMISS_KEY);
    return Boolean(stored) && Date.now() - stored < DISMISS_COOLDOWN_MS;
  };

  const recentlyShown = () => {
    const stored = readTimestamp(SHOWN_KEY);
    return Boolean(stored) && Date.now() - stored < SHOWN_COOLDOWN_MS;
  };

  const injectStyles = () => {
    if (document.getElementById("pwa-install-style")) {
      return;
    }

    const style = document.createElement("style");
    style.id = "pwa-install-style";
    style.textContent = [
      ".pwa-install-modal{position:fixed;inset:0;display:flex;align-items:flex-end;justify-content:center;padding:18px;z-index:1200;pointer-events:none;opacity:0;transition:opacity .22s ease;}",
      ".pwa-install-modal.is-visible{opacity:1;pointer-events:auto;}",
      ".pwa-install-backdrop{position:absolute;inset:0;background:rgba(16,38,56,.22);backdrop-filter:blur(4px);}",
      ".pwa-install-card{position:relative;width:min(100%,420px);padding:20px;border-radius:24px;background:rgba(255,255,255,.98);border:1px solid rgba(16,38,56,.08);box-shadow:0 20px 60px rgba(16,38,56,.18);color:#102638;transform:translateY(18px);transition:transform .22s ease;}",
      ".pwa-install-modal.is-visible .pwa-install-card{transform:translateY(0);}",
      ".pwa-install-head{display:flex;align-items:center;gap:14px;margin-bottom:12px;}",
      ".pwa-install-logo{width:54px;height:54px;border-radius:16px;object-fit:cover;box-shadow:0 10px 24px rgba(16,38,56,.14);flex:0 0 auto;}",
      ".pwa-install-kicker{display:block;margin-bottom:4px;font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:#2877b5;}",
      ".pwa-install-title{margin:0;font-size:22px;line-height:1.12;font-weight:800;color:#102638;}",
      ".pwa-install-text{margin:0 0 16px;font-size:15px;line-height:1.55;color:rgba(16,38,56,.78);}",
      ".pwa-install-actions{display:flex;gap:10px;flex-wrap:wrap;}",
      ".pwa-install-btn{appearance:none;border:none;border-radius:999px;min-height:46px;padding:0 18px;font:inherit;font-weight:800;cursor:pointer;transition:transform .18s ease,box-shadow .18s ease,background .18s ease,color .18s ease;}",
      ".pwa-install-btn:hover,.pwa-install-btn:focus-visible{transform:translateY(-1px);outline:none;}",
      ".pwa-install-btn-primary{background:#102638;color:#fff;box-shadow:0 14px 30px rgba(16,38,56,.18);}",
      ".pwa-install-btn-secondary{background:#f4f7fb;color:#102638;border:1px solid rgba(16,38,56,.1);}",
      "@media (max-width: 640px){.pwa-install-modal{padding:12px}.pwa-install-card{width:100%;padding:18px;border-radius:22px}.pwa-install-actions{flex-direction:column}.pwa-install-btn{width:100%}}",
      "@media (prefers-reduced-motion: reduce){.pwa-install-modal,.pwa-install-card,.pwa-install-btn{transition:none}}"
    ].join("");
    document.head.appendChild(style);
  };

  const hidePrompt = (rememberChoice) => {
    if (rememberChoice) {
      writeTimestamp(DISMISS_KEY);
    }

    if (!promptRoot) {
      return;
    }

    promptRoot.classList.remove("is-visible");
    window.setTimeout(() => {
      if (promptRoot) {
        promptRoot.hidden = true;
      }
    }, 220);
  };

  const showPrompt = () => {
    if (!deferredPrompt || installed || recentlyDismissed() || recentlyShown()) {
      return;
    }

    injectStyles();

    if (!promptRoot) {
      promptRoot = document.createElement("div");
      promptRoot.className = "pwa-install-modal";
      promptRoot.hidden = true;
      promptRoot.innerHTML = [
        '<div class="pwa-install-backdrop" data-pwa-close="1"></div>',
        '<section class="pwa-install-card" role="dialog" aria-modal="true" aria-labelledby="pwa-install-title">',
        '  <div class="pwa-install-head">',
        '    <img class="pwa-install-logo" src="/assets/helin.jpeg" alt="HELIANTHA">',
        '    <div>',
        '      <span class="pwa-install-kicker">HELIANTHA</span>',
        '      <h2 class="pwa-install-title" id="pwa-install-title">Installer l\'application</h2>',
        "    </div>",
        "  </div>",
        '  <p class="pwa-install-text">Ouvrez HELIANTHA plus vite depuis votre telephone ou votre ordinateur.</p>',
        '  <div class="pwa-install-actions">',
        '    <button class="pwa-install-btn pwa-install-btn-primary" type="button" data-pwa-action="install">Installer</button>',
        '    <button class="pwa-install-btn pwa-install-btn-secondary" type="button" data-pwa-action="dismiss">Pas maintenant</button>',
        "  </div>",
        "</section>"
      ].join("");
      document.body.appendChild(promptRoot);
      promptCard = promptRoot.querySelector(".pwa-install-card");

      promptRoot.addEventListener("click", (event) => {
        const closeTarget = event.target.closest("[data-pwa-close]");
        const actionTarget = event.target.closest("[data-pwa-action]");

        if (closeTarget) {
          hidePrompt(true);
          return;
        }

        if (!actionTarget) {
          return;
        }

        if (actionTarget.dataset.pwaAction === "dismiss") {
          hidePrompt(true);
          return;
        }

        if (actionTarget.dataset.pwaAction === "install") {
          void triggerInstall();
        }
      });

      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && promptRoot && !promptRoot.hidden) {
          hidePrompt(true);
        }
      });
    }

    writeTimestamp(SHOWN_KEY);
    promptRoot.hidden = false;
    window.requestAnimationFrame(() => {
      if (promptRoot) {
        promptRoot.classList.add("is-visible");
      }
      if (promptCard) {
        const primaryButton = promptCard.querySelector('[data-pwa-action="install"]');
        if (primaryButton) {
          primaryButton.focus({ preventScroll: true });
        }
      }
    });
  };

  const triggerInstall = async () => {
    if (!deferredPrompt) {
      hidePrompt(false);
      return;
    }

    try {
      deferredPrompt.prompt();
      const choice = await deferredPrompt.userChoice;
      if (!choice || choice.outcome !== "accepted") {
        writeTimestamp(DISMISS_KEY);
      }
    } catch (_) {
      writeTimestamp(DISMISS_KEY);
    } finally {
      deferredPrompt = null;
      hidePrompt(false);
    }
  };

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt = event;
    window.setTimeout(showPrompt, 900);
  });

  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    installed = true;
    clearTimestamp(DISMISS_KEY);
    clearTimestamp(SHOWN_KEY);
    hidePrompt(false);
  });

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/service-worker.js").catch(() => {});
    });
  }
})();
