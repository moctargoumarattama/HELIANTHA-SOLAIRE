(() => {
  const root = document.querySelector("#ha-chat");
  if (!root) return;

  const endpoint = root.dataset.endpoint || "/api/assistant/chat";
  const logoUrl = root.dataset.logo || "";
  const launcher = document.querySelector("#ha-chat-launcher");
  const panel = document.querySelector("#ha-chat-panel");
  const closeButton = document.querySelector("#ha-chat-close");
  const log = document.querySelector("#ha-chat-log");
  const form = document.querySelector("#ha-chat-form");
  const input = document.querySelector("#ha-chat-input");
  const suggestions = document.querySelector("#ha-chat-suggestions");
  const messages = [];
  let pending = false;
  let progressTimer = null;

  const welcome = "Bonjour, je suis le conseiller HeliAntha. Je peux vous aider a choisir entre pompage solaire, reduction de facture, site isole ou recharge electrique.";

  function openChat() {
    panel.hidden = false;
    launcher.setAttribute("aria-expanded", "true");
    if (!messages.length) addMessage("assistant", welcome, false);
    window.setTimeout(() => input?.focus(), 60);
  }

  function closeChat() {
    panel.hidden = true;
    launcher.setAttribute("aria-expanded", "false");
  }

  function addMessage(role, content, store = true) {
    if (!log || !content) return null;
    const bubble = document.createElement("div");
    bubble.className = `ha-chat-message ${role}`;
    const cleanRole = String(role || "").split(" ")[0];
    if (cleanRole === "assistant") {
      const avatar = logoUrl
        ? `<span class="ha-chat-avatar" aria-hidden="true"><img src="${logoUrl}" alt=""></span>`
        : `<span class="ha-chat-avatar" aria-hidden="true">IA</span>`;
      bubble.innerHTML = `${avatar}<span class="ha-chat-bubble-text"></span>`;
      bubble.querySelector(".ha-chat-bubble-text").textContent = content;
    } else {
      bubble.innerHTML = `<span class="ha-chat-bubble-text"></span>`;
      bubble.querySelector(".ha-chat-bubble-text").textContent = content;
    }
    log.appendChild(bubble);
    log.scrollTop = log.scrollHeight;
    if (store) messages.push({ role, content });
    return bubble;
  }

  function addQuoteCard(quote) {
    if (!log || !quote) return;
    const card = document.createElement("div");
    card.className = "chat-quote-card";
    card.innerHTML = `
      <div class="quote-card-header">
        <span class="badge-success">Devis officiel genere</span>
        <h4 class="quote-price"></h4>
        <p class="quote-summary"></p>
      </div>
      <div class="quote-card-actions">
        <a target="_blank" rel="noreferrer" class="btn-download-pdf">Telecharger le devis (PDF)</a>
        <a target="_blank" rel="noreferrer" class="btn-view-quote">Voir le recapitulatif</a>
      </div>
    `;
    card.querySelector(".quote-price").textContent = quote.total_ttc || "";
    card.querySelector(".quote-summary").textContent = quote.system_summary || "Devis HeliAntha";
    card.querySelector(".btn-download-pdf").href = quote.download_url || "#";
    card.querySelector(".btn-view-quote").href = quote.view_url || "#";
    log.appendChild(card);
    log.scrollTop = log.scrollHeight;
  }

  function setPending(value) {
    pending = value;
    if (input) input.disabled = value;
    const button = form?.querySelector("button");
    if (button) button.disabled = value;
  }

  function startProgress(bubble) {
    const steps = [
      "Connexion au conseiller local...",
      "Analyse de votre demande...",
      "Recherche de la meilleure orientation...",
      "Preparation de la reponse...",
      "Presque termine, merci de patienter...",
      "Le modele local finalise sa reponse...",
    ];
    let index = 0;
    if (!bubble) return;
    const text = bubble.querySelector(".ha-chat-bubble-text");
    if (text) text.innerHTML = progressMarkup(steps[index]);
    progressTimer = window.setInterval(() => {
      index = Math.min(index + 1, steps.length - 1);
      const target = bubble.querySelector(".ha-chat-bubble-text");
      if (target) target.innerHTML = progressMarkup(steps[index]);
      log.scrollTop = log.scrollHeight;
    }, 6500);
  }

  function stopProgress() {
    if (progressTimer) {
      window.clearInterval(progressTimer);
      progressTimer = null;
    }
  }

  function progressMarkup(text) {
    return `
      <span class="ha-chat-progress">
        <span>${text}</span>
        <i aria-hidden="true"></i><i aria-hidden="true"></i><i aria-hidden="true"></i>
      </span>
    `;
  }

  function fetchWithTimeout(url, options, timeoutMs = 50000) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    return fetch(url, { ...options, signal: controller.signal }).finally(() => {
      window.clearTimeout(timer);
    });
  }

  async function sendMessage(content) {
    const text = String(content || "").trim();
    if (!text || pending) return;
    addMessage("user", text.slice(0, 1000));
    if (input) input.value = "";
    suggestions?.setAttribute("hidden", "");

    setPending(true);
    const typing = addMessage("assistant typing", "Connexion au conseiller local...", false);
    startProgress(typing);
    try {
      const response = await fetchWithTimeout(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages }),
      });
      const payload = await response.json();
      stopProgress();
      typing?.remove();
      if (!response.ok) {
        throw new Error(payload.error || "Erreur assistant");
      }
      addMessage("assistant", payload.content || "Je suis disponible pour vous orienter.");
      if (payload.quote_ready && payload.quote) {
        addQuoteCard(payload.quote);
      }
    } catch (_) {
      stopProgress();
      typing?.remove();
      addMessage("assistant", "Notre conseiller est actuellement tres sollicite. Vous pouvez lancer votre simulation directement via notre configurateur en ligne ou nous contacter par telephone.");
    } finally {
      setPending(false);
      input?.focus();
    }
  }

  launcher?.addEventListener("click", () => {
    if (panel.hidden) openChat();
    else closeChat();
  });
  closeButton?.addEventListener("click", closeChat);

  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage(input?.value);
  });

  suggestions?.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => sendMessage(button.textContent));
  });

  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !panel.hidden) closeChat();
  });
})();
