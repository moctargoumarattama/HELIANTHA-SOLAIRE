(() => {
  "use strict";

  const root = document.getElementById("wa-cockpit");
  if (!root) return;
  document.body.classList.add("wa-page-active");

  const POLL_INTERVAL_MS = 10000;
  const BACKOFF_INTERVAL_MS = 20000;
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const ajaxHeaders = { "X-Requested-With": "XMLHttpRequest" };
  const csrfHeaders = () => ({ ...ajaxHeaders, "X-CSRFToken": csrfToken });
  const statusBadge = document.getElementById("wa-status-badge");
  const statusText = document.getElementById("wa-status-text");
  const phone = document.getElementById("wa-phone");
  const hasQr = document.getElementById("wa-has-qr");
  const qrBox = document.getElementById("wa-qr-box");
  const testResult = document.getElementById("wa-test-result");
  const outboxResult = document.getElementById("wa-outbox-result");
  const outboxBody = document.getElementById("wa-outbox-tbody");
  const outboxCount = document.getElementById("wa-count-badge");
  const replayButton = document.getElementById("wa-retry-outbox");

  let pollingTimer = null;
  let isRequestInProgress = false;
  let activeController = null;
  let refreshWhenReady = false;
  let outboxNeedsRefresh = false;
  let outboxRefreshPromise = null;
  let outboxController = null;
  let replayInProgress = false;
  let autoRetried = false;
  let disposed = false;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function showQrText(message) {
    if (qrBox) qrBox.replaceChildren(element("p", "muted", message));
  }

  function showConnected(connectedPhone) {
    if (!qrBox) return;
    const box = element("div", "wa-connected-box");
    box.appendChild(element("span", "wa-connected-symbol", "✅"));
    box.appendChild(element("strong", "", "Session WhatsApp active"));
    const line = element("p", "muted", "Ligne connectée : ");
    line.appendChild(element("b", "", connectedPhone || "Authentifié"));
    box.appendChild(line);
    box.appendChild(element("small", "wa-ready-tag", "Prête à diffuser les devis clients"));
    qrBox.replaceChildren(box);
  }

  function updateStatusUI(payload) {
    const online = payload.online !== false;
    const connected = online && payload.connected === true;
    if (statusBadge) {
      statusBadge.className = `status whatsapp-status-badge ${!online ? "offline" : connected ? "connected" : "disconnected"}`;
      statusBadge.textContent = !online ? "Hors ligne" : connected ? "Connecté" : "Déconnecté";
    }
    if (statusText) {
      statusText.textContent = !online ? "Passerelle injoignable" : connected ? "Session WhatsApp connectée" : "En attente de scan QR";
    }
    if (phone) phone.textContent = payload.phone || "-";
    if (hasQr) hasQr.textContent = payload.has_qr ? "Oui" : "Non";
  }

  async function loadQr(signal) {
    if (!qrBox || document.hidden || signal.aborted) return true;
    showQrText("Recherche du QR code...");
    try {
      const response = await fetch(root.dataset.qrUrl, {
        headers: ajaxHeaders, signal, cache: "no-store",
      });
      if (!response.ok) throw new Error(`QR HTTP ${response.status}`);
      const payload = await response.json();
      if (document.hidden || signal.aborted) return true;
      if (payload.qr) {
        const image = element("img", "wa-qr-img");
        image.src = payload.qr;
        image.alt = "QR code WhatsApp";
        qrBox.replaceChildren(image);
      } else if (payload.connected) {
        showConnected(payload.phone);
      } else {
        showQrText(payload.error || "QR non disponible pour le moment.");
      }
      return true;
    } catch (error) {
      if (error.name === "AbortError") throw error;
      showQrText("QR momentanément indisponible.");
      return false;
    }
  }

  function scheduleNextPoll(delay) {
    clearTimeout(pollingTimer);
    pollingTimer = null;
    if (!document.hidden && !disposed) {
      pollingTimer = setTimeout(fetchStatusSafe, delay);
    }
  }

  function requestImmediatePoll() {
    if (document.hidden || disposed) return;
    if (isRequestInProgress) {
      refreshWhenReady = true;
      return;
    }
    scheduleNextPoll(0);
  }

  async function refreshOutbox() {
    if (document.hidden || disposed) {
      outboxNeedsRefresh = true;
      return;
    }
    if (outboxRefreshPromise) {
      try { await outboxRefreshPromise; } catch (_) { /* Handled by the first caller. */ }
      return;
    }
    outboxController = new AbortController();
    outboxRefreshPromise = (async () => {
      const response = await fetch(root.dataset.outboxFragmentUrl, {
        headers: ajaxHeaders, cache: "no-store", signal: outboxController.signal,
      });
      if (!response.ok) throw new Error(`Outbox HTTP ${response.status}`);
      const payload = await response.json();
      if (!payload.success || typeof payload.html !== "string") throw new Error("Outbox invalide");
      if (document.hidden || disposed) {
        outboxNeedsRefresh = true;
        return;
      }
      if (outboxBody) outboxBody.innerHTML = payload.html;
      if (outboxCount) outboxCount.textContent = `${payload.count || 0} msg`;
      outboxNeedsRefresh = false;
    })();
    try {
      await outboxRefreshPromise;
    } catch (error) {
      outboxNeedsRefresh = true;
      if (error.name !== "AbortError") console.warn("Actualisation de la file indisponible :", error);
    } finally {
      outboxRefreshPromise = null;
      outboxController = null;
    }
  }

  async function replayOutbox({ silent = false } = {}) {
    if (replayInProgress || document.hidden || disposed) return;
    replayInProgress = true;
    if (replayButton) replayButton.disabled = true;
    if (!silent && outboxResult) outboxResult.textContent = "Rejeu en cours...";
    try {
      const response = await fetch(root.dataset.retryOutboxUrl, {
        method: "POST", headers: csrfHeaders(),
      });
      if (!response.ok) throw new Error(`Rejeu HTTP ${response.status}`);
      const payload = await response.json();
      if (outboxResult) outboxResult.textContent = `${payload.sent || 0} envoyé(s), ${payload.failed || 0} échec(s).`;
      await refreshOutbox();
    } catch (error) {
      if (outboxResult) outboxResult.textContent = "Passerelle momentanément indisponible.";
      console.warn("Rejeu WhatsApp indisponible :", error);
    } finally {
      replayInProgress = false;
      if (replayButton) replayButton.disabled = false;
    }
  }

  async function fetchStatusSafe() {
    if (document.hidden || disposed) return;
    if (isRequestInProgress) {
      refreshWhenReady = true;
      return;
    }
    clearTimeout(pollingTimer);
    pollingTimer = null;
    isRequestInProgress = true;
    const controller = new AbortController();
    activeController = controller;
    let nextDelay = POLL_INTERVAL_MS;
    try {
      const response = await fetch(root.dataset.statusUrl, {
        headers: ajaxHeaders, signal: controller.signal, cache: "no-store",
      });
      if (!response.ok) throw new Error(`Statut HTTP ${response.status}`);
      const payload = await response.json();
      if (document.hidden || controller.signal.aborted) return;
      updateStatusUI(payload);
      if (payload.online === false) {
        showQrText("Passerelle injoignable.");
        nextDelay = BACKOFF_INTERVAL_MS;
      } else if (payload.connected) {
        showConnected(payload.phone);
        if (!autoRetried) {
          autoRetried = true;
          await replayOutbox({ silent: true });
        }
      } else if (!await loadQr(controller.signal)) {
        nextDelay = BACKOFF_INTERVAL_MS;
      }
    } catch (error) {
      if (error.name !== "AbortError" && !document.hidden) {
        console.warn("Supervision WhatsApp en pause temporaire (réseau) :", error);
        updateStatusUI({ online: false, connected: false, phone: null, has_qr: false });
        showQrText("Passerelle momentanément indisponible.");
        nextDelay = BACKOFF_INTERVAL_MS;
      }
    } finally {
      activeController = null;
      if (outboxNeedsRefresh && !document.hidden && !disposed) await refreshOutbox();
      isRequestInProgress = false;
      if (!document.hidden && !disposed) {
        if (refreshWhenReady) {
          refreshWhenReady = false;
          scheduleNextPoll(0);
        } else {
          scheduleNextPoll(nextDelay);
        }
      }
    }
  }

  function updateOutboxRow(row, item) {
    if (!row || !item) return;
    const status = String(item.status || "PENDING").toUpperCase();
    const visible = root.dataset.viewMode === "all"
      || (root.dataset.viewMode === "sent" ? status === "SENT" : status !== "SENT");
    if (!visible) {
      row.remove();
      if (outboxCount) outboxCount.textContent = `${outboxBody?.querySelectorAll("tr[data-id]").length || 0} msg`;
      return;
    }
    const badge = row.querySelector(".wa-status-pill");
    if (badge) {
      badge.className = `status outbox-status ${status.toLowerCase()} wa-status-pill`;
      badge.textContent = status === "SENT" ? "Envoyé" : status === "FAILED" ? "Échoué" : "En attente";
    }
    const attempts = row.querySelector(".wa-attempts-badge");
    if (attempts) attempts.textContent = item.attempts || 0;
    const detail = row.querySelector(".wa-td-error");
    if (detail) {
      const description = item.error_message || (status === "SENT" ? "Envoyé avec succès" : "En file de traitement");
      const className = item.error_message ? "wa-error-text" : status === "SENT" ? "wa-ok-text" : "muted";
      const text = element("span", className, description);
      if (item.error_message) text.title = item.error_message;
      detail.replaceChildren(text);
    }
  }

  async function retryOne(button) {
    if (button.disabled) return;
    button.disabled = true;
    const label = button.textContent;
    button.textContent = "⏳";
    const id = button.dataset.id;
    if (outboxResult) outboxResult.textContent = `Relance #${id}...`;
    try {
      const response = await fetch(button.dataset.url, { method: "POST", headers: csrfHeaders() });
      const payload = await response.json();
      if (!response.ok || !payload.success) throw new Error(payload.error || "Rejeu impossible");
      updateOutboxRow(button.closest("tr"), payload.item);
      if (outboxResult) outboxResult.textContent = payload.item?.status === "SENT"
        ? `Message #${id} envoyé !` : `Message #${id} replacé en file.`;
      await refreshOutbox();
    } catch (error) {
      if (outboxResult) outboxResult.textContent = "Impossible de confirmer la relance du message.";
      console.warn("Relance WhatsApp indisponible :", error);
    } finally {
      button.disabled = false;
      button.textContent = label;
    }
  }

  async function deleteOne(button) {
    if (button.disabled) return;
    const ok = window.confirmAdminAction
      ? await window.confirmAdminAction({
          title: "Supprimer le message",
          message: `Supprimer définitivement le message #${button.dataset.id} de la file d'attente ?`,
          icon: "🗑️",
          confirmText: "Supprimer",
          danger: true,
        })
      : confirm(`Supprimer définitivement le message #${button.dataset.id} de la file ?`);
    if (!ok) return;

    button.disabled = true;
    try {
      const response = await fetch(button.dataset.url, { method: "POST", headers: csrfHeaders() });
      const payload = await response.json();
      if (!response.ok || !payload.success) throw new Error("Suppression impossible");
      button.closest("tr")?.remove();
      if (window.showAdminToast) {
        window.showAdminToast(`Message #${button.dataset.id} supprimé de la file d'attente.`, "delete");
      }
      if (outboxResult) outboxResult.textContent = `Message #${button.dataset.id} supprimé.`;
      await refreshOutbox();
    } catch (error) {
      if (window.showAdminToast) {
        window.showAdminToast("Erreur lors de la suppression.", "error");
      }
      if (outboxResult) outboxResult.textContent = "Erreur lors de la suppression.";
      console.warn("Suppression WhatsApp indisponible :", error);
    } finally {
      button.disabled = false;
    }
  }

  outboxBody?.addEventListener("click", (event) => {
    const retry = event.target.closest(".wa-btn-row-retry");
    const remove = event.target.closest(".wa-btn-row-delete");
    if (retry) void retryOne(retry);
    else if (remove) void deleteOne(remove);
  });

  document.getElementById("wa-refresh")?.addEventListener("click", requestImmediatePoll);
  replayButton?.addEventListener("click", () => void replayOutbox());

  document.getElementById("wa-logout")?.addEventListener("click", async () => {
    const ok = window.confirmAdminAction
      ? await window.confirmAdminAction({
          title: "Déconnexion WhatsApp",
          message: "Déconnecter la passerelle WhatsApp ? Le QR code devra être scanné à nouveau.",
          icon: "📱",
          confirmText: "Déconnecter",
          danger: true,
        })
      : confirm("Déconnecter la session WhatsApp ?");
    if (!ok) return;

    try {
      const response = await fetch(root.dataset.logoutUrl, { method: "POST", headers: csrfHeaders() });
      if (!response.ok) throw new Error("Déconnexion impossible");
      if (window.showAdminToast) {
        window.showAdminToast("Session WhatsApp déconnectée.", "info");
      }
      requestImmediatePoll();
    } catch (error) {
      if (outboxResult) outboxResult.textContent = "Déconnexion momentanément indisponible.";
    }
  });

  document.getElementById("wa-test-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector('button[type="submit"]');
    if (button?.disabled) return;
    if (button) button.disabled = true;
    if (testResult) testResult.textContent = "Envoi en cours...";
    try {
      const data = Object.fromEntries(new FormData(form).entries());
      const response = await fetch(root.dataset.testUrl, {
        method: "POST",
        headers: { ...csrfHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      const payload = await response.json();
      if (testResult) {
        const success = response.ok && payload.success;
        testResult.textContent = success ? "Message envoyé avec succès." : "Échec envoi. Vérifiez la passerelle.";
        testResult.className = success ? "wa-test-feedback success" : "wa-test-feedback error";
      }
    } catch (error) {
      if (testResult) {
        testResult.textContent = "Passerelle injoignable.";
        testResult.className = "wa-test-feedback error";
      }
    } finally {
      if (button) button.disabled = false;
    }
  });

  document.getElementById("wa-btn-purge-sent")?.addEventListener("click", async (event) => {
    if (!confirm("Purger définitivement tous les messages déjà marqués comme 'Envoyé' ?")) return;
    const button = event.currentTarget;
    if (button.disabled) return;
    button.disabled = true;
    if (outboxResult) outboxResult.textContent = "Purge en cours...";
    try {
      const response = await fetch(root.dataset.purgeUrl, {
        method: "POST",
        headers: { ...csrfHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ status: "SENT" }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.success) throw new Error("Purge impossible");
      if (outboxResult) outboxResult.textContent = `${payload.count || 0} message(s) purgé(s).`;
      await refreshOutbox();
    } catch (error) {
      if (outboxResult) outboxResult.textContent = "Erreur lors de la purge.";
      console.warn("Purge WhatsApp indisponible :", error);
    } finally {
      button.disabled = false;
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      clearTimeout(pollingTimer);
      pollingTimer = null;
      activeController?.abort();
      outboxController?.abort();
    } else {
      requestImmediatePoll();
    }
  });
  window.addEventListener("pagehide", () => {
    disposed = true;
    clearTimeout(pollingTimer);
    activeController?.abort();
    outboxController?.abort();
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) {
      disposed = false;
      requestImmediatePoll();
    }
  });

  requestImmediatePoll();
})();
