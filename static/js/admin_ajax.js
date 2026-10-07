(() => {
  "use strict";

  const pendingForms = new WeakSet();

  function showAdminToast(message, type = "success") {
    const container = document.getElementById("admin-toast-container");
    if (!container) return;
    const toast = document.createElement("div");
    toast.className = `admin-ajax-toast ${type === "error" ? "is-error" : "is-success"}`;
    toast.setAttribute("role", type === "error" ? "alert" : "status");
    toast.textContent = String(message);
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3800);
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
            showAdminToast(data.message || options.successMessage || "Modifications enregistrées.");
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

  window.showAdminToast = showAdminToast;
  window.handleAjaxForm = handleAjaxForm;
})();
