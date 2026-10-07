(() => {
  "use strict";

  const filterForm = document.querySelector("[data-live-catalog-filters]");
  const tbody = document.querySelector(".catalog-table-wrap tbody");
  const visibleCount = document.querySelector("[data-live-catalog-count]");
  const totalCount = document.querySelector("[data-catalog-total]");
  const activeCount = document.querySelector("[data-catalog-active]");
  const noResults = document.querySelector("[data-live-catalog-empty]");
  const modal = document.getElementById("modal-product");
  const modalForm = document.getElementById("modal-product-form");
  const categoryInput = document.getElementById("modal-f-category");
  const techWrapper = document.getElementById("modal-tech-wrapper");
  const techContainer = document.getElementById("modal-tech-container");
  const submitButton = document.getElementById("modal-btn-submit");
  const loading = document.getElementById("modal-product-loading");
  const toast = document.getElementById("catalog-toast");
  const definitions = document.getElementById("catalog-field-definitions");
  const categoryFields = definitions ? JSON.parse(definitions.textContent || "{}") : {};
  if (!filterForm || !tbody || !modal || !modalForm || !submitButton) return;

  let requestNumber = 0;
  let editController = null;
  let saving = false;
  let toastTimer = null;
  let nextCatalogOrder = -1;
  tbody.querySelectorAll("[data-catalog-row]").forEach((row, index) => {
    row.dataset.catalogOrder = String(index);
  });

  const normalize = (value) => String(value ?? "").trim().toLocaleLowerCase("fr");
  const numberValue = (value) => Number.parseFloat(value || "0") || 0;
  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
  const choiceLabels = {
    on_grid: "On-Grid", off_grid: "Off-Grid", hybrid: "Hybride",
    monophase: "Monophasé", triphase: "Triphasé", dc: "DC", ac: "AC",
  };

  function showToast(message, error = false) {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.toggle("is-error", error);
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, 4500);
  }

  function matches(row) {
    const {category, active, q, brand} = filterForm.elements;
    if (category.value && row.dataset.category !== category.value) return false;
    if (active.value && row.dataset.active !== active.value) return false;
    if (brand.value && !normalize(row.dataset.brand).includes(normalize(brand.value))) return false;
    if (q.value && !normalize(row.dataset.search).includes(normalize(q.value))) return false;
    return true;
  }

  function applyFilters() {
    const rows = Array.from(tbody.querySelectorAll("[data-catalog-row]"));
    const pumpOnly = filterForm.elements.category.value === "pumps";
    tbody.closest("table").querySelectorAll("[data-pump-hidden-column]").forEach((cell) => {
      cell.hidden = pumpOnly;
    });
    const shown = rows.filter(matches);
    const sort = filterForm.elements.sort.value;
    shown.sort((a, b) => {
      if (sort === "brand") return normalize(a.dataset.brand).localeCompare(normalize(b.dataset.brand));
      if (sort === "price_asc") return numberValue(a.dataset.price) - numberValue(b.dataset.price);
      if (sort === "price_desc") return numberValue(b.dataset.price) - numberValue(a.dataset.price);
      if (sort === "updated") return normalize(b.dataset.updated).localeCompare(normalize(a.dataset.updated));
      return numberValue(a.dataset.catalogOrder) - numberValue(b.dataset.catalogOrder);
    });
    rows.forEach((row) => { row.hidden = true; row.style.display = "none"; });
    shown.forEach((row) => {
      row.hidden = false;
      row.style.display = "";
      row.querySelectorAll("[data-pump-hidden-column]").forEach((cell) => { cell.hidden = pumpOnly; });
      tbody.appendChild(row);
    });
    const originalEmpty = tbody.querySelector("[data-catalog-empty]");
    if (originalEmpty) originalEmpty.hidden = rows.length > 0;
    if (visibleCount) visibleCount.textContent = String(shown.length);
    if (noResults) noResults.hidden = shown.length > 0 || rows.length === 0;
  }

  function updateCounts(counts) {
    if (!counts) return;
    if (totalCount) totalCount.textContent = String(counts.total);
    if (activeCount) activeCount.textContent = String(counts.active);
  }

  function replaceRow(html, productId, created = false) {
    const fragment = document.createElement("template");
    fragment.innerHTML = html || "";
    const next = fragment.content.querySelector("tr[data-catalog-row]");
    if (!next || String(next.dataset.productId) !== String(productId)) {
      throw new Error("Réponse catalogue incomplète");
    }
    const old = Array.from(tbody.querySelectorAll("tr[data-catalog-row]"))
      .find((row) => row.dataset.productId === String(productId));
    next.dataset.catalogOrder = old ? old.dataset.catalogOrder : String(nextCatalogOrder--);
    if (old) old.replaceWith(next);
    else if (created) tbody.prepend(next);
    else throw new Error("Ligne catalogue introuvable");
    const scrollTop = window.scrollY;
    applyFilters();
    window.scrollTo(0, scrollTop);
  }

  function hideErrors() {
    const box = document.getElementById("modal-product-errors");
    if (box) box.hidden = true;
    modalForm.querySelectorAll(".cat-field-error").forEach((node) => node.remove());
    modalForm.querySelectorAll("[aria-invalid]").forEach((node) => node.removeAttribute("aria-invalid"));
  }

  function showErrors(errors, message) {
    hideErrors();
    const box = document.getElementById("modal-product-errors");
    const title = document.getElementById("modal-product-errors-title");
    const list = document.getElementById("modal-product-errors-list");
    if (title) title.textContent = message || "Veuillez corriger les points signalés :";
    if (list) list.replaceChildren();
    Object.entries(errors || {}).forEach(([field, text]) => {
      if (list) {
        const item = document.createElement("li");
        item.textContent = String(text);
        list.appendChild(item);
      }
      const name = field === "power_w" ? "power_w" : field;
      const input = Array.from(modalForm.elements).find((element) => element.name === name || element.name === `spec_${name}`);
      const label = input?.closest(".cat-m-field");
      if (label) {
        input.setAttribute("aria-invalid", "true");
        const detail = document.createElement("small");
        detail.className = "cat-field-error";
        detail.textContent = String(text);
        label.appendChild(detail);
      }
    });
    if (box) box.hidden = false;
  }

  function renderTechFields(category, values = {}) {
    const fields = categoryFields[category] || [];
    techWrapper.hidden = !fields.length;
    techContainer.replaceChildren();
    const html = fields.map((field) => {
      const raw = values[field.key] ?? "";
      const wide = ["power_w", "power_kw", "capacity_kwh", "power_hp", "tank_volume_l", "section_mm2", "curve_points"].includes(field.key);
      const required = field.required ? "required" : "";
      const name = escapeHtml(field.form_name || `spec_${field.key}`);
      let input;
      if (field.kind === "choice") {
        input = `<select name="${name}" ${required}><option value="">Choisir...</option>${(field.choices || []).map((choice) =>
          `<option value="${escapeHtml(choice)}"${String(raw) === String(choice) ? " selected" : ""}>${escapeHtml(choiceLabels[choice] || choice)}</option>`).join("")}</select>`;
      } else if (field.kind === "pump_curve") {
        input = `<textarea name="${name}" rows="6" placeholder="0:95&#10;1:91&#10;1,5:89" ${required}>${escapeHtml(raw)}</textarea><small class="cat-m-hint">Format : Débit(m³/h):HMT(m) - un couple par ligne</small>`;
      } else {
        const numeric = ["number", "integer", "percent"].includes(field.kind);
        const step = field.kind === "integer" ? "1" : "any";
        const min = field.min !== undefined ? `min="${escapeHtml(field.min)}"` : "";
        const max = field.max !== undefined ? `max="${escapeHtml(field.max)}"` : "";
        const placeholder = field.key === "power_hp" ? 'placeholder="ex: 15"' : "";
        input = `<input ${numeric ? `type="number" step="${step}"` : 'type="text"'} name="${name}" value="${escapeHtml(raw)}" ${min} ${max} ${placeholder} ${required}>
          ${field.unit ? `<small class="cat-m-hint">Unité : ${escapeHtml(field.unit)}</small>` : ""}
          ${field.help ? `<small class="cat-m-hint">${escapeHtml(field.help)}</small>` : ""}`;
      }
      return `<label class="cat-m-field ${wide ? "full" : ""}"><span class="cat-m-label">${escapeHtml(field.label)}${field.required ? ' <span class="cat-m-req">*</span>' : ""}</span>${input}</label>`;
    }).join("");
    techContainer.innerHTML = html;
  }

  function syncPumpFields(category) {
    const pump = category === "pumps";
    const referenceField = modalForm.querySelector("[data-pump-reference-field]");
    const referenceInput = document.getElementById("modal-f-reference");
    const brandInput = document.getElementById("modal-f-brand");
    const priceLabel = modalForm.querySelector("[data-current-price-label]");
    const priceNote = modalForm.querySelector("[data-pump-price-note]");
    if (referenceField) referenceField.hidden = pump;
    if (referenceInput) referenceInput.required = !pump;
    if (brandInput) brandInput.required = !pump;
    modalForm.querySelectorAll("[data-non-pump-required-marker]").forEach((marker) => { marker.hidden = pump; });
    if (priceLabel) priceLabel.textContent = pump ? "Prix interne PT (DH) *" : "Prix HT (DH) *";
    if (priceNote) priceNote.hidden = !pump;
  }

  function openModal() {
    modal.classList.add("qc-modal-open");
    modal.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
  }

  window.closeProductModal = () => {
    requestNumber++;
    if (editController) editController.abort();
    modal.classList.remove("qc-modal-open");
    modal.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    hideErrors();
  };
  window.closeProductModalOnBg = (event) => {
    if (event.target === modal) window.closeProductModal();
  };

  function fillEdit(prod, productId) {
    const brandModel = [prod.brand, prod.model].filter(Boolean).join(" ");
    document.getElementById("modal-product-title").textContent = `✏️ Modifier : ${brandModel || prod.reference || `Équipement #${productId}`}`;
    document.getElementById("modal-product-subtitle").textContent = `Réf : ${prod.reference || "-"} | Catégorie : ${prod.category || "-"}`;
    modalForm.action = `/admin/catalogue/${productId}/edit`;
    document.getElementById("modal-product-id").value = productId;
    document.getElementById("modal-f-reference").value = prod.reference || "";
    categoryInput.value = prod.category || "";
    document.getElementById("modal-f-brand").value = prod.brand || "";
    document.getElementById("modal-f-model").value = prod.model || "";
    document.getElementById("modal-f-price").value = prod.sale_price ?? "";
    document.getElementById("modal-f-active").checked = Boolean(prod.active);
    renderTechFields(prod.category, prod.form_specs || prod.technical_specs || {});
    syncPumpFields(prod.category);
  }

  window.openProductModal = async (mode, event, productId = null) => {
    if (event) event.preventDefault();
    if (saving) return;
    requestNumber++;
    const thisRequest = requestNumber;
    if (editController) editController.abort();
    hideErrors();
    openModal();
    loading.hidden = mode !== "edit";
    modalForm.hidden = mode === "edit";
    if (mode === "new") {
      modalForm.reset();
      modalForm.action = "/admin/catalogue/new";
      document.getElementById("modal-product-id").value = "";
      document.getElementById("modal-product-title").textContent = "➕ Ajouter un équipement";
      document.getElementById("modal-product-subtitle").textContent = "Saisissez les caractéristiques techniques et commerciales de l'équipement.";
      document.getElementById("modal-f-active").checked = true;
      renderTechFields("");
      syncPumpFields("");
      return;
    }
    if (mode !== "edit" || !productId) return;
    editController = new AbortController();
    try {
      const response = await fetch(`/admin/catalogue/${productId}/edit?format=json`, {
        headers: {Accept: "application/json", "X-Requested-With": "XMLHttpRequest"},
        signal: editController.signal,
      });
      const data = await response.json();
      if (!response.ok || !data.product) throw new Error("La fiche produit est indisponible. Veuillez réessayer.");
      if (thisRequest !== requestNumber) return;
      fillEdit(data.product, productId);
      modalForm.hidden = false;
    } catch (error) {
      if (thisRequest === requestNumber && error.name !== "AbortError") {
        showErrors({}, "Impossible de charger la fiche. Vérifiez votre connexion et réessayez.");
      }
    } finally {
      if (thisRequest === requestNumber) loading.hidden = true;
    }
  };

  filterForm.addEventListener("submit", (event) => event.preventDefault());
  filterForm.addEventListener("input", applyFilters);
  filterForm.addEventListener("change", applyFilters);
  categoryInput.addEventListener("change", () => {
    syncPumpFields(categoryInput.value);
    renderTechFields(categoryInput.value);
  });

  modalForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (saving) return;
    if (!modalForm.checkValidity()) { modalForm.reportValidity(); return; }
    saving = true;
    submitButton.disabled = true;
    const label = submitButton.querySelector(".cat-btn-text");
    const original = label?.textContent;
    if (label) label.textContent = "Enregistrement en cours...";
    hideErrors();
    try {
      const token = document.querySelector('meta[name="csrf-token"]')?.content || modalForm.elements.csrf_token?.value || "";
      const response = await fetch(modalForm.action, {
        method: "POST", body: new FormData(modalForm),
        headers: {"X-Requested-With": "XMLHttpRequest", Accept: "application/json", "X-CSRFToken": token},
      });
      const data = await response.json().catch(() => null);
      if (response.ok && data?.success && data.product && data.html_row) {
        replaceRow(data.html_row, data.product.id, data.action === "created");
        updateCounts(data.counts);
        window.closeProductModal();
        showToast("Équipement enregistré avec succès.");
      } else if (response.status === 400 && data?.errors) {
        showErrors(data.errors, data.message);
      } else {
        showErrors({}, "Erreur de communication avec le serveur. La fiche n'a pas été modifiée. Veuillez réessayer.");
      }
    } catch (_error) {
      showErrors({}, "Erreur de communication avec le serveur. La fiche n'a pas été modifiée. Veuillez réessayer.");
    } finally {
      saving = false;
      submitButton.disabled = false;
      if (label) label.textContent = original;
    }
  });

  tbody.addEventListener("submit", async (event) => {
    const form = event.target.closest(".cat-action-form");
    if (!form) return;
    event.preventDefault();
    if (form.dataset.pending === "1") return;
    form.dataset.pending = "1";
    const button = form.querySelector("button");
    if (button) button.disabled = true;
    try {
      const token = document.querySelector('meta[name="csrf-token"]')?.content || form.elements.csrf_token?.value || "";
      const response = await fetch(form.action, {
        method: "POST", body: new FormData(form),
        headers: {"X-Requested-With": "XMLHttpRequest", Accept: "application/json", "X-CSRFToken": token},
      });
      const data = await response.json().catch(() => null);
      if (response.ok && data?.success) {
        replaceRow(data.html_row, data.product_id);
        updateCounts(data.counts);
        showToast(data.is_active ? "Équipement activé." : "Équipement désactivé.");
      } else {
        showToast(Object.values(data?.errors || {})[0] || "Impossible de modifier le statut. Veuillez réessayer.", true);
      }
    } catch (_error) {
      showToast("Erreur de communication avec le serveur. Veuillez réessayer.", true);
    } finally {
      form.dataset.pending = "0";
      if (button) button.disabled = false;
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal.classList.contains("qc-modal-open")) window.closeProductModal();
  });
  applyFilters();
})();
