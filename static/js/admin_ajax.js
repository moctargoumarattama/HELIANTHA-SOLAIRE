(() => {
  "use strict";

  const pendingForms = new WeakSet();

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  /**
   * Affiche un toast flottant élégant et non intrusif en haut à droite.
   * @param {string} message - Texte informatif.
   * @param {string} [type='success'] - 'success' | 'delete' | 'error' | 'info' | 'auth'
   * @param {string|null} [title=null] - Titre court optionnel.
   */
  function showAdminToast(message, type = "success", title = null) {
    const container = document.getElementById("admin-toast-container");
    if (!container) return;

    // Normalisation automatique des types courants
    let toastType = type;
    const lowerMsg = String(message).toLowerCase();
    if (toastType === "success") {
      if (lowerMsg.includes("supprim")) toastType = "delete";
      else if (lowerMsg.includes("déconnect") || lowerMsg.includes("connect")) toastType = "auth";
    }

    // Définition de l'icône et du titre par défaut
    let icon = "✅";
    let defaultTitle = "Enregistré";
    if (toastType === "delete") {
      icon = "🗑️";
      defaultTitle = "Supprimé";
    } else if (toastType === "error") {
      icon = "⚠️";
      defaultTitle = "Attention";
    } else if (toastType === "auth") {
      icon = "👤";
      defaultTitle = "Session";
    } else if (toastType === "info") {
      icon = "ℹ️";
      defaultTitle = "Information";
    }

    const toastTitle = title || defaultTitle;

    // Évite l'accumulation de plus de 4 toasts simultanés
    while (container.children.length >= 4) {
      container.firstElementChild.remove();
    }

    const toast = document.createElement("div");
    toast.className = `admin-ajax-toast is-${toastType} toast-${toastType}`;
    toast.setAttribute("role", toastType === "error" ? "alert" : "status");
    toast.innerHTML = `
      <div class="toast-icon-wrap" aria-hidden="true">${icon}</div>
      <div class="toast-content-wrap">
        <div class="toast-title">${escapeHtml(toastTitle)}</div>
        <div class="toast-message">${escapeHtml(message)}</div>
      </div>
      <button type="button" class="toast-close-btn" aria-label="Fermer la notification">✕</button>
      <div class="toast-progress-bar"></div>
    `;

    const dismiss = () => {
      if (toast.classList.contains("toast-hiding")) return;
      toast.classList.add("toast-hiding");
      setTimeout(() => toast.remove(), 260);
    };

    toast.querySelector(".toast-close-btn")?.addEventListener("click", dismiss);
    container.appendChild(toast);

    // Auto-fermeture après 3.6 secondes
    setTimeout(dismiss, 3600);
  }

  function clearErrors(form) {
    form.querySelectorAll("[data-admin-ajax-error]").forEach((node) => node.remove());
    form.querySelectorAll(".is-invalid").forEach((node) => {
      node.classList.remove("is-invalid");
      node.removeAttribute("aria-invalid");
    });
  }

  function showErrors(form, errors = {}) {
    clearErrors(form);
    Object.entries(errors).forEach(([name, message]) => {
      const field = Array.from(form.elements).find((element) => element.name === name);
      if (!field) return;
      field.classList.add("is-invalid");
      field.setAttribute("aria-invalid", "true");
      const feedback = document.createElement("small");
      feedback.className = "invalid-feedback admin-ajax-field-error";
      feedback.dataset.adminAjaxError = "";
      feedback.textContent = String(message);
      (field.closest(".tva-input-card, .pr-field, .settings-field-box, .og-field, .qc-status-input-group") || field.parentElement).appendChild(feedback);
    });
  }

  function handleAjaxForm(form, options = {}) {
    if (!form || form.dataset.adminAjaxBound === "1") return;
    form.dataset.adminAjaxBound = "1";
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (pendingForms.has(form)) return;
      if (!form.checkValidity()) { form.reportValidity(); return; }

      pendingForms.add(form);
      const body = new FormData(form);
      const buttons = Array.from(form.querySelectorAll('button[type="submit"], input[type="submit"]'));
      const originalButtons = buttons.map((button) => ({
        button, disabled: button.disabled, html: button.innerHTML, value: button.value,
      }));
      buttons.forEach((button) => {
        button.disabled = true;
        if (button.tagName === "INPUT") button.value = "Enregistrement...";
        else button.textContent = "Enregistrement...";
      });
      form.setAttribute("aria-busy", "true");
      clearErrors(form);

      try {
        const token = document.querySelector('meta[name="csrf-token"]')?.content
          || form.querySelector('input[name="csrf_token"]')?.value || "";
        const response = await fetch(form.action, {
          method: (form.method || "POST").toUpperCase(),
          body,
          headers: {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": token,
            Accept: "application/json",
          },
        });
        const data = await response.json().catch(() => null);
        if (response.ok && data?.success) {
          try {
            if (options.onSuccess) await options.onSuccess(data, form);
            showAdminToast(data.message || options.successMessage || "Modifications enregistrées.", "success");
          } catch (_error) {
            showAdminToast("Enregistrement effectué, mais l'affichage n'a pas pu être actualisé.", "error");
          }
        } else if (response.status === 400 && data?.errors) {
          showErrors(form, data.errors);
          showAdminToast(data.message || Object.values(data.errors)[0] || "Vérifiez les champs indiqués.", "error");
        } else {
          showAdminToast("Impossible de confirmer la réponse du serveur. Vérifiez les données avant de réessayer.", "error");
        }
      } catch (_error) {
        showAdminToast("Impossible de joindre le serveur. Vérifiez les données avant de réessayer.", "error");
      } finally {
        originalButtons.forEach(({button, disabled, html, value}) => {
          button.disabled = disabled;
          if (button.tagName === "INPUT") button.value = value;
          else button.innerHTML = html;
        });
        form.removeAttribute("aria-busy");
        pendingForms.delete(form);
      }
    });
  }

  /* --- Gestion des Modales Propres --- */
  function openLogoutModal() {
    const dialog = document.getElementById("logout-confirm-dialog");
    if (dialog && typeof dialog.showModal === "function") {
      dialog.showModal();
    } else {
      // Fallback si la balise dialog n'est pas supportée
      if (confirm("Êtes-vous sûr de vouloir vous déconnecter ?")) {
        const logoutForm = dialog?.querySelector("form");
        if (logoutForm) logoutForm.submit();
      }
    }
  }

  function closeLogoutModal() {
    const dialog = document.getElementById("logout-confirm-dialog");
    if (dialog && typeof dialog.close === "function") dialog.close();
  }

  /**
   * Ouvre la modale de confirmation globale et retourne une Promesse (true si confirmé, false sinon).
   */
  function confirmAdminAction({
    title = "Confirmation",
    message = "Êtes-vous sûr de vouloir continuer ?",
    icon = "⚠️",
    confirmText = "Confirmer",
    cancelText = "Annuler",
    danger = true
  } = {}) {
    return new Promise((resolve) => {
      const dialog = document.getElementById("admin-global-confirm-dialog");
      if (!dialog || typeof dialog.showModal !== "function") {
        resolve(window.confirm(message));
        return;
      }

      const titleNode = document.getElementById("global-dialog-title");
      const msgNode = document.getElementById("admin-confirm-message");
      const iconNode = document.getElementById("admin-confirm-icon");
      const okBtn = document.getElementById("admin-confirm-ok-btn");
      const cancelBtn = document.getElementById("admin-confirm-cancel-btn");

      if (titleNode) titleNode.textContent = title;
      if (msgNode) msgNode.textContent = message;
      if (iconNode) iconNode.textContent = icon;
      if (okBtn) {
        okBtn.textContent = confirmText;
        okBtn.className = danger ? "admin-button danger-btn" : "admin-button";
      }
      if (cancelBtn) cancelBtn.textContent = cancelText;

      const onConfirm = () => { cleanup(); resolve(true); dialog.close(); };
      const onCancel = () => { cleanup(); resolve(false); dialog.close(); };
      const onDismiss = () => { cleanup(); resolve(false); };
      const onBackdrop = (e) => {
        const rect = dialog.getBoundingClientRect();
        const isIn = rect.top <= e.clientY && e.clientY <= rect.top + rect.height &&
                     rect.left <= e.clientX && e.clientX <= rect.left + rect.width;
        if (!isIn) onCancel();
      };

      function cleanup() {
        okBtn?.removeEventListener("click", onConfirm);
        cancelBtn?.removeEventListener("click", onCancel);
        dialog.removeEventListener("click", onBackdrop);
        dialog.removeEventListener("cancel", onDismiss);
        dialog.removeEventListener("close", onDismiss);
      }

      okBtn?.addEventListener("click", onConfirm);
      cancelBtn?.addEventListener("click", onCancel);
      dialog.addEventListener("click", onBackdrop);
      dialog.addEventListener("cancel", onDismiss);
      dialog.addEventListener("close", onDismiss);

      dialog.showModal();
    });
  }

  // Initialisation automatique au chargement du DOM
  document.addEventListener("DOMContentLoaded", () => {
    // 1. Fermeture au clic sur le fond pour les modales
    document.querySelectorAll("dialog.admin-modal-dialog").forEach((dlg) => {
      dlg.addEventListener("click", (e) => {
        const rect = dlg.getBoundingClientRect();
        const isInDialog = (
          rect.top <= e.clientY && e.clientY <= rect.top + rect.height &&
          rect.left <= e.clientX && e.clientX <= rect.left + rect.width
        );
        if (!isInDialog) dlg.close();
      });
    });

    // 2. Traitement des messages flashés serveur
    const flashNode = document.getElementById("flashed-toast-data");
    if (flashNode) {
      try {
        const messages = JSON.parse(flashNode.textContent || "[]");
        if (Array.isArray(messages)) {
          messages.forEach(([cat, msg], index) => {
            setTimeout(() => {
              const type = (cat === "error" || cat === "danger") ? "error" : (cat === "info" ? "info" : "success");
              showAdminToast(msg, type);
            }, index * 200);
          });
        }
      } catch (err) {
        console.warn("Notice toast flash non analysable :", err);
      }
    }

    // 3. Traitement des drapeaux d'URL courants (sans garder l'URL polluée)
    const params = new URLSearchParams(window.location.search);
    let handled = false;
    if (params.has("saved")) {
      showAdminToast("Modifications enregistrées avec succès.", "success");
      params.delete("saved");
      handled = true;
    } else if (params.has("deleted")) {
      showAdminToast("Élément supprimé avec succès.", "delete");
      params.delete("deleted");
      handled = true;
    } else if (params.has("created")) {
      showAdminToast("Création effectuée avec succès.", "success");
      params.delete("created");
      handled = true;
    } else if (params.has("status_updated")) {
      showAdminToast("Statut mis à jour avec succès.", "success");
      params.delete("status_updated");
      handled = true;
    }

    if (handled) {
      const searchStr = params.toString() ? "?" + params.toString() : "";
      window.history.replaceState({}, document.title, window.location.pathname + searchStr + window.location.hash);
    }

    // 4. Intercepteur pour formulaires avec data-confirm
    document.addEventListener("submit", (e) => {
      const form = e.target;
      if (!form || !form.getAttribute) return;
      const confirmMsg = form.getAttribute("data-confirm");
      if (!confirmMsg || form.dataset.adminConfirmed === "1") return;

      e.preventDefault();
      confirmAdminAction({
        title: form.getAttribute("data-confirm-title") || "Confirmation requise",
        message: confirmMsg,
        confirmText: form.getAttribute("data-confirm-btn") || "Confirmer",
        danger: form.getAttribute("data-confirm-danger") !== "false"
      }).then((ok) => {
        if (ok) {
          form.dataset.adminConfirmed = "1";
          if (typeof form.requestSubmit === "function") form.requestSubmit();
          else form.submit();
        }
      });
    });
  });

  window.showAdminToast = showAdminToast;
  window.handleAjaxForm = handleAjaxForm;
  window.openLogoutModal = openLogoutModal;
  window.closeLogoutModal = closeLogoutModal;
  window.confirmAdminAction = confirmAdminAction;
})();
