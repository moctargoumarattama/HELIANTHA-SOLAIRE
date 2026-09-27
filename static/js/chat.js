(() => {
  const root = document.querySelector("#ha-chat");
  if (!root) return;

  const endpoint = root.dataset.endpoint || "/api/assistant/chat";
  const launcher = document.querySelector("#ha-chat-launcher");
  const panel = document.querySelector("#ha-chat-panel");
  const closeButton = document.querySelector("#ha-chat-close");
  const log = document.querySelector("#ha-chat-log");
  const form = document.querySelector("#ha-chat-form");
  const input = document.querySelector("#ha-chat-input");
  const suggestions = document.querySelector("#ha-chat-suggestions");
  const messages = [];
  let pending = false;

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
    bubble.textContent = content;
    log.appendChild(bubble);
    log.scrollTop = log.scrollHeight;
    if (store) messages.push({ role, content });
    return bubble;
  }

  function setPending(value) {
    pending = value;
    if (input) input.disabled = value;
    const button = form?.querySelector("button");
    if (button) button.disabled = value;
  }

  async function sendMessage(content) {
    const text = String(content || "").trim();
    if (!text || pending) return;
    addMessage("user", text.slice(0, 1000));
    if (input) input.value = "";
    suggestions?.setAttribute("hidden", "");

    setPending(true);
    const typing = addMessage("assistant typing", "Le conseiller ecrit...", false);
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages }),
      });
      const payload = await response.json();
      typing?.remove();
      if (!response.ok) {
        throw new Error(payload.error || "Erreur assistant");
      }
      addMessage("assistant", payload.content || "Je suis disponible pour vous orienter.");
    } catch (_) {
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
