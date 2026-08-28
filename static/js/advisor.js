(() => {
  const company = window.HELIANTHA_COMPANY || {};
  const publicQuote = window.PUBLIC_QUOTE || {};
  const printMode = document.body.classList.contains("page-print");
  const STORAGE_KEY = "heliantha_advisor_state_v2";
  const POSITION_KEY = "heliantha_advisor_position_v1";
  const LAUNCHER_POSITION_KEY = "heliantha_advisor_launcher_position_v1";
  const desktopDragMedia = window.matchMedia("(min-width: 769px)");

  if (printMode) return;
  ensureShell();

  const launcher = document.querySelector("#advisor-launcher");
  const panel = document.querySelector("#advisor-panel");
  const messages = document.querySelector("#advisor-messages");
  const quickActions = document.querySelector("#advisor-quick-actions");
  const form = document.querySelector("#advisor-form");
  const input = document.querySelector("#advisor-input");
  const closeButtons = document.querySelectorAll("[data-advisor-close]");
  const shell = panel?.querySelector(".advisor-shell");
  const header = panel?.querySelector(".advisor-header");
  if (!launcher || !panel || !messages || !quickActions || !form || !input) return;

  let state = loadState();
  let lastFocus = null;
  let dragState = null;
  let launcherDragState = null;
  let suppressLauncherClick = false;

  renderHistory();
  renderActions(defaultActions());
  applyLauncherPosition(true);

  launcher.addEventListener("click", (event) => {
    if (suppressLauncherClick) {
      event.preventDefault();
      suppressLauncherClick = false;
      return;
    }
    openAdvisor();
  });
  launcher.addEventListener("pointerdown", onLauncherDragStart);
  closeButtons.forEach((button) => button.addEventListener("click", closeAdvisor));
  form.addEventListener("submit", onSubmit);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !panel.hidden) closeAdvisor();
  });

  if (header && shell) {
    header.addEventListener("pointerdown", onDragStart);
    window.addEventListener("pointermove", onDragMove);
    window.addEventListener("pointerup", onDragEnd);
    window.addEventListener("resize", () => {
      applyLauncherPosition(true);
      if (!panel.hidden) applyPosition(true);
    });
  }
  window.addEventListener("pointermove", onLauncherDragMove);
  window.addEventListener("pointerup", onLauncherDragEnd);

  function defaultState() {
    return {
      project_type: publicQuote.project || null,
      project_confidence: 0,
      current_intent: null,
      last_question_id: null,
      wizard_step: null,
      collected_data: {},
      missing_data: [],
      quote_reference: publicQuote.quote_number || null,
      history: [],
    };
  }

  function loadState() {
    try {
      return { ...defaultState(), ...(JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") || {}) };
    } catch {
      return defaultState();
    }
  }

  function saveState() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      ...state,
      history: (state.history || []).slice(-16),
    }));
  }

  function ensureShell() {
    if (document.querySelector("#advisor-launcher") && document.querySelector("#advisor-panel")) return;
    document.body.insertAdjacentHTML("beforeend", `
      <button class="advisor-launcher" type="button" id="advisor-launcher" aria-expanded="false" aria-controls="advisor-panel" aria-label="Ouvrir le conseiller HELIANTHA">Conseiller</button>
      <div class="advisor-panel" id="advisor-panel" hidden aria-hidden="true">
        <div class="advisor-backdrop" data-advisor-close></div>
        <section class="advisor-shell" role="dialog" aria-modal="true" aria-labelledby="advisor-title">
          <header class="advisor-header">
            <div>
              <span class="eyebrow">Conseiller HeliAntha</span>
              <h2 id="advisor-title">Conseiller</h2>
            </div>
            <button class="close-button" type="button" data-advisor-close aria-label="Fermer le conseiller">x</button>
          </header>
          <div class="advisor-messages" id="advisor-messages"></div>
          <div class="advisor-quick-actions" id="advisor-quick-actions"></div>
          <form class="advisor-composer" id="advisor-form">
            <label class="sr-only" for="advisor-input">Votre message</label>
            <input id="advisor-input" type="text" placeholder="Ecrivez votre besoin" maxlength="2000">
            <button class="button button-primary" type="submit">Envoyer</button>
          </form>
        </section>
      </div>
    `);
  }

  function renderHistory() {
    messages.innerHTML = "";
    const history = state.history && state.history.length ? state.history : [{ role: "bot", text: initialText() }];
    history.forEach((item) => addMessage(item.role, item.text, false));
  }

  function initialText() {
    if (publicQuote.quote_number) {
      return "Je peux expliquer votre devis, le prix ou le materiel retenu.";
    }
    return "Bonjour. Dites-moi votre besoin, je vous oriente vers la bonne etude.";
  }

  function openAdvisor() {
    lastFocus = document.activeElement;
    panel.hidden = false;
    panel.setAttribute("aria-hidden", "false");
    launcher.setAttribute("aria-expanded", "true");
    window.requestAnimationFrame(() => applyPosition(false));
    input.focus();
  }

  function closeAdvisor() {
    onDragEnd();
    panel.hidden = true;
    panel.setAttribute("aria-hidden", "true");
    launcher.setAttribute("aria-expanded", "false");
    saveState();
    if (lastFocus && typeof lastFocus.focus === "function") lastFocus.focus();
  }

  async function onSubmit(event) {
    event.preventDefault();
    const value = input.value.trim();
    if (!value) return;
    input.value = "";
    addMessage("user", value);
    await sendMessage(value);
  }

  async function sendMessage(message) {
    setBusy(true);
    try {
      const response = await fetch("/api/advisor/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, state, quote_number: publicQuote.quote_number || "" }),
      });
      const payload = await response.json();
      updateFromPayload(payload);
    } catch {
      addMessage("bot", "Je n'arrive pas a repondre maintenant. Vous pouvez contacter HeliAntha.");
      renderActions([{ label: "Parler a HeliAntha", action: "call" }]);
    } finally {
      setBusy(false);
    }
  }

  async function calculateFromChat() {
    setBusy(true);
    try {
      const response = await fetch("/api/advisor/calculate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ state }),
      });
      const payload = await response.json();
      updateFromPayload(payload);
    } catch {
      addMessage("bot", "Le calcul n'a pas pu etre lance. Ouvrez le questionnaire pour verifier les donnees.");
      renderActions([{ label: "Ouvrir le questionnaire", action: "start_estimate" }]);
    } finally {
      setBusy(false);
    }
  }

  function updateFromPayload(payload) {
    if (payload.state) state = { ...state, ...payload.state };
    if (payload.reply) addMessage("bot", payload.reply);
    renderActions(payload.actions || defaultActions());
    saveState();
  }

  function addMessage(role, text, persist = true) {
    const item = document.createElement("article");
    item.className = `advisor-message advisor-message-${role}`;
    item.innerHTML = `<p>${escapeHtml(text).replace(/\n/g, "<br>")}</p>`;
    messages.appendChild(item);
    messages.scrollTop = messages.scrollHeight;
    if (persist) {
      state.history = [...(state.history || []), { role, text }].slice(-16);
      saveState();
    }
  }

  function renderActions(actions) {
    quickActions.innerHTML = (actions || []).map((item) => {
      const label = escapeHtml(item.label || "");
      if (item.href) return `<a class="advisor-chip" href="${escapeHtml(item.href)}">${label}</a>`;
      return `<button type="button" class="advisor-chip" data-action="${escapeHtml(item.action || "")}">${label}</button>`;
    }).join("");
    quickActions.querySelectorAll("[data-action]").forEach((button) => {
      button.addEventListener("click", () => handleAction(button.dataset.action));
    });
  }

  function defaultActions() {
    if (publicQuote.quote_number) {
      return [
        { label: "Comprendre le prix", action: "say:prix" },
        { label: "Materiel retenu", action: "say:materiel" },
        { label: "Parler a HeliAntha", action: "call" },
      ];
    }
    return [
      { label: "Pompage solaire", action: "project:pumping" },
      { label: "Site sans reseau", action: "project:offgrid" },
      { label: "Solaire avec batteries", action: "project:hybrid" },
    ];
  }

  function handleAction(action) {
    if (!action) return;
    if (action.startsWith("project:")) {
      const project = action.split(":")[1];
      state.project_type = project;
      sendMessage(projectLabel(project));
      return;
    }
    if (action.startsWith("say:")) {
      sendMessage(action.slice(4));
      return;
    }
    if (action === "calculate") {
      calculateFromChat();
      return;
    }
    if (action === "start_estimate") {
      window.HELIANTHA_WIZARD?.applyPrefill?.({
        project: state.project_type || "",
        answers: state.collected_data || {},
      });
      window.HELIANTHA_WIZARD?.open?.(state.project_type || "");
      closeAdvisor();
      return;
    }
    if (action === "call") {
      if (company.phone_url) window.location.href = company.phone_url;
      return;
    }
    if (action === "whatsapp") {
      if (company.whatsapp_url) window.location.href = company.whatsapp_url;
    }
  }

  function projectLabel(project) {
    return {
      pumping: "pompage solaire",
      offgrid: "site sans reseau",
      ongrid: "reduire ma consommation",
      hybrid: "solaire avec batteries",
      thermal: "chauffage solaire",
      ev: "recharge electrique",
    }[project] || "projet solaire";
  }

  function setBusy(active) {
    input.disabled = active;
    form.querySelector("button")?.toggleAttribute("disabled", active);
  }

  function onDragStart(event) {
    if (!desktopDragMedia.matches || panel.hidden || event.button !== 0) return;
    if (event.target.closest("button, input, textarea, a")) return;
    const rect = shell.getBoundingClientRect();
    dragState = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, left: rect.left, top: rect.top };
    shell.classList.add("is-dragging");
    event.preventDefault();
  }

  function onDragMove(event) {
    if (!dragState || event.pointerId !== dragState.pointerId) return;
    const width = shell.offsetWidth || 360;
    const height = shell.offsetHeight || 460;
    const left = clamp(dragState.left + event.clientX - dragState.startX, 16, window.innerWidth - width - 16);
    const top = clamp(dragState.top + event.clientY - dragState.startY, 16, window.innerHeight - height - 16);
    setPosition(left, top);
  }

  function onDragEnd() {
    if (!dragState || !shell) return;
    shell.classList.remove("is-dragging");
    localStorage.setItem(POSITION_KEY, JSON.stringify({
      left: parseFloat(shell.style.left || "0"),
      top: parseFloat(shell.style.top || "0"),
    }));
    dragState = null;
  }

  function onLauncherDragStart(event) {
    if (!desktopDragMedia.matches || event.button !== 0) return;
    const rect = launcher.getBoundingClientRect();
    launcherDragState = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      left: rect.left,
      top: rect.top,
      width: rect.width,
      height: rect.height,
      dragged: false,
    };
    launcher.classList.add("is-dragging");
    event.preventDefault();
  }

  function onLauncherDragMove(event) {
    if (!launcherDragState || event.pointerId !== launcherDragState.pointerId) return;
    const deltaX = event.clientX - launcherDragState.startX;
    const deltaY = event.clientY - launcherDragState.startY;
    if (!launcherDragState.dragged && Math.hypot(deltaX, deltaY) < 4) return;
    launcherDragState.dragged = true;
    const width = launcherDragState.width || launcher.offsetWidth || 180;
    const height = launcherDragState.height || launcher.offsetHeight || 56;
    const left = clamp(launcherDragState.left + deltaX, 12, window.innerWidth - width - 12);
    const top = clamp(launcherDragState.top + deltaY, 12, window.innerHeight - height - 12);
    setLauncherPosition(left, top);
  }

  function onLauncherDragEnd() {
    if (!launcherDragState) return;
    launcher.classList.remove("is-dragging");
    if (launcherDragState.dragged) {
      localStorage.setItem(LAUNCHER_POSITION_KEY, JSON.stringify({
        left: parseFloat(launcher.style.left || "0"),
        top: parseFloat(launcher.style.top || "0"),
      }));
      suppressLauncherClick = true;
      window.setTimeout(() => {
        suppressLauncherClick = false;
      }, 0);
    }
    launcherDragState = null;
  }

  function applyLauncherPosition(forceClamp) {
    if (!launcher || !desktopDragMedia.matches) {
      launcher?.removeAttribute("style");
      return;
    }
    let stored = {};
    try { stored = JSON.parse(localStorage.getItem(LAUNCHER_POSITION_KEY) || "{}") || {}; } catch {}
    if (stored.left == null || stored.top == null) {
      launcher.removeAttribute("style");
      return;
    }
    const width = launcher.offsetWidth || 180;
    const height = launcher.offsetHeight || 56;
    const left = forceClamp ? clamp(stored.left, 12, window.innerWidth - width - 12) : stored.left;
    const top = forceClamp ? clamp(stored.top, 12, window.innerHeight - height - 12) : stored.top;
    setLauncherPosition(left, top);
  }

  function setLauncherPosition(left, top) {
    launcher.style.left = `${Math.round(left)}px`;
    launcher.style.top = `${Math.round(top)}px`;
    launcher.style.right = "auto";
    launcher.style.bottom = "auto";
    launcher.style.margin = "0";
  }

  function applyPosition(forceClamp) {
    if (!shell || !desktopDragMedia.matches) {
      if (shell) shell.removeAttribute("style");
      return;
    }
    let stored = {};
    try { stored = JSON.parse(localStorage.getItem(POSITION_KEY) || "{}") || {}; } catch {}
    const width = shell.offsetWidth || 360;
    const height = shell.offsetHeight || 460;
    const left = forceClamp || !stored.left ? window.innerWidth - width - 16 : stored.left;
    const top = forceClamp || !stored.top ? window.innerHeight - height - 24 : stored.top;
    setPosition(clamp(left, 16, window.innerWidth - width - 16), clamp(top, 16, window.innerHeight - height - 16));
  }

  function setPosition(left, top) {
    shell.style.left = `${Math.round(left)}px`;
    shell.style.top = `${Math.round(top)}px`;
    shell.style.right = "auto";
    shell.style.bottom = "auto";
    shell.style.margin = "0";
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), Math.max(min, max));
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  window.HELIANTHA_ADVISOR = {
    getState: () => state,
    sendMessage,
  };
})();
