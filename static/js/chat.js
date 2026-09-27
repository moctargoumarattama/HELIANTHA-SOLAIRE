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
  let dragState = null;
  let suppressClick = false;
  let nudgeTimer = null;

  const welcome = "Bonjour, je suis l'assistant IA de HeliAntha. Je peux vous orienter simplement vers le bon projet : pompage solaire, reduction de facture, site isole ou recharge electrique.";

  initInstantTapFeedback();

  function openChat() {
    hideNudge();
    panel.hidden = false;
    root.classList.add("is-open");
    launcher.setAttribute("aria-expanded", "true");
    if (!messages.length) addMessage("assistant", welcome, false);
    window.setTimeout(() => input?.focus(), 60);
  }

  function initInstantTapFeedback() {
    const selector = "button, a";
    let activeElement = null;

    const clear = () => {
      if (activeElement) {
        activeElement.classList.remove("is-pressing");
        activeElement = null;
      }
    };

    root.addEventListener("pointerdown", (event) => {
      const target = event.target.closest(selector);
      if (!target || target.disabled) return;
      activeElement = target;
      activeElement.classList.add("is-pressing");
    }, { passive: true });

    ["pointerup", "pointercancel", "pointerleave"].forEach((eventName) => {
      root.addEventListener(eventName, clear, { passive: true });
    });
  }

  function closeChat() {
    panel.hidden = true;
    root.classList.remove("is-open");
    launcher.setAttribute("aria-expanded", "false");
  }

  function hideNudge() {
    window.clearTimeout(nudgeTimer);
    root.classList.add("nudge-hidden");
    root.querySelector("#ha-chat-nudge")?.remove();
  }

  function startNudgeTimer(delayMs = 0) {
    window.clearTimeout(nudgeTimer);
    nudgeTimer = window.setTimeout(() => {
      if (!root.querySelector("#ha-chat-nudge")) return;
      root.classList.remove("nudge-hidden");
      nudgeTimer = window.setTimeout(hideNudge, 3000);
    }, delayMs);
  }

  function restoreLauncherPosition() {
    try {
      const saved = JSON.parse(window.sessionStorage.getItem("haChatPosition") || "null");
      if (!saved || typeof saved.left !== "number" || typeof saved.top !== "number") return;
      setLauncherPosition(saved.left, saved.top, false);
      root.classList.add("has-moved");
    } catch (_) {
      // Ignore invalid session storage data.
    }
  }

  function setLauncherPosition(left, top, save = true) {
    const rect = root.getBoundingClientRect();
    const width = rect.width || 56;
    const height = rect.height || 56;
    const margin = 8;
    const maxLeft = Math.max(margin, window.innerWidth - width - margin);
    const maxTop = Math.max(margin, window.innerHeight - height - margin);
    const nextLeft = Math.min(Math.max(margin, left), maxLeft);
    const nextTop = Math.min(Math.max(margin, top), maxTop);

    root.style.left = `${nextLeft}px`;
    root.style.top = `${nextTop}px`;
    root.style.right = "auto";
    root.style.bottom = "auto";

    if (save) {
      window.sessionStorage.setItem("haChatPosition", JSON.stringify({ left: nextLeft, top: nextTop }));
    }
  }

  function bindLauncherDrag() {
    if (!launcher) return;

    launcher.addEventListener("pointerdown", (event) => {
      if (!panel.hidden) return;
      const rect = root.getBoundingClientRect();
      dragState = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        left: rect.left,
        top: rect.top,
        moved: false,
      };
      launcher.setPointerCapture?.(event.pointerId);
    });

    launcher.addEventListener("pointermove", (event) => {
      if (!dragState || dragState.pointerId !== event.pointerId) return;
      const dx = event.clientX - dragState.startX;
      const dy = event.clientY - dragState.startY;
      if (!dragState.moved && Math.hypot(dx, dy) < 7) return;

      dragState.moved = true;
      suppressClick = true;
      root.classList.add("is-dragging", "has-moved");
      hideNudge();
      setLauncherPosition(dragState.left + dx, dragState.top + dy);
    });

    const finishDrag = (event) => {
      if (!dragState || dragState.pointerId !== event.pointerId) return;
      launcher.releasePointerCapture?.(event.pointerId);
      if (dragState.moved) {
        window.setTimeout(() => {
          suppressClick = false;
        }, 0);
      }
      dragState = null;
      root.classList.remove("is-dragging");
    };

    launcher.addEventListener("pointerup", finishDrag);
    launcher.addEventListener("pointercancel", finishDrag);
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
    if (value) {
      suggestions?.setAttribute("hidden", "");
    } else if (messages.length <= 1) {
      suggestions?.removeAttribute("hidden");
    }
  }

  function startProgress(bubble) {
    const steps = [
      "Connexion au conseiller...",
      "Analyse de votre demande...",
      "Recherche de la meilleure orientation...",
      "Preparation de la reponse...",
      "Presque termine, merci de patienter...",
      "Le conseiller finalise sa reponse...",
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
    const typing = addMessage("assistant typing", "Connexion au conseiller...", false);
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

  restoreLauncherPosition();
  bindLauncherDrag();
  if (!root.classList.contains("has-moved")) {
    const hasWelcomePopup = Boolean(document.querySelector("#welcome-popup"));
    startNudgeTimer(hasWelcomePopup ? 3400 : 500);
  }

  launcher?.addEventListener("click", () => {
    if (suppressClick) {
      suppressClick = false;
      return;
    }
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

  window.addEventListener("resize", () => {
    const rect = root.getBoundingClientRect();
    if (root.style.left && root.style.top) {
      setLauncherPosition(rect.left, rect.top);
    }
  });
})();
