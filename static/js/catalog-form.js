(() => {
  const form = document.querySelector("[data-catalog-form]");
  const categorySelect = document.getElementById("catalog-category");
  const shell = document.getElementById("catalog-tech-shell");
  if (!form || !categorySelect || !shell) return;

  const definitions = document.getElementById("catalog-field-definitions");
  if (!definitions) return;
  const CATEGORY_FIELDS = JSON.parse(definitions.textContent);

  const CHOICE_LABELS = {
    on_grid: "On-Grid",
    off_grid: "Off-Grid",
    hybrid: "Hybride",
    monophase: "Monophasé",
    triphase: "Triphasé",
    dc: "DC",
    ac: "AC",
  };

  const escapeHtml = (value) =>
    String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");

  const labelFor = (field, value) => {
    if (field.kind !== "choice") return escapeHtml(value);
    return escapeHtml(CHOICE_LABELS[value] || value);
  };

  const fieldName = (field) => field.form_name || `spec_${field.key}`;

  const fieldMarkup = (field, values = {}) => {
    const rawValue = values[field.key] ?? "";
    const required = field.required ? ' required data-required="1"' : "";
    const wide = ["power_w", "power_kw", "capacity_kwh", "power_hp", "tank_volume_l", "section_mm2", "curve_points"].includes(field.key)
      ? " full"
      : "";
    const input = field.kind === "choice"
      ? `<select name="${fieldName(field)}"${required}>
          <option value="">Choisir</option>
          ${field.choices.map((choice) => `<option value="${escapeHtml(choice)}"${String(rawValue) === String(choice) ? " selected" : ""}>${labelFor(field, choice)}</option>`).join("")}
        </select>`
      : field.kind === "pump_curve"
        ? `<textarea
            name="${fieldName(field)}"
            rows="8"
            placeholder="0:95&#10;1:91&#10;1,5:89"
            ${required}
          >${escapeHtml(rawValue)}</textarea>`
        : `<input
          ${field.kind === "number" || field.kind === "integer" || field.kind === "percent" ? `type="number" step="${field.kind === "integer" ? "1" : "any"}"` : ""}
          name="${fieldName(field)}"
          value="${escapeHtml(rawValue)}"
          ${field.min !== undefined ? `min="${escapeHtml(field.min)}"` : ""}
          ${field.max !== undefined ? `max="${escapeHtml(field.max)}"` : ""}
          ${required}
          ${field.key === "power_hp" ? 'placeholder="ex. 15"' : ""}
        >`;

    return `<label class="${wide.trim()}">
      ${escapeHtml(field.label)}${field.required ? " *" : ""}
      ${input}
      ${field.unit ? `<small>Unité : ${escapeHtml(field.unit)}</small>` : ""}
      ${field.help ? `<small>${escapeHtml(field.help)}</small>` : ""}
    </label>`;
  };

  const sectionMarkup = (category, values = {}) => {
    const fields = CATEGORY_FIELDS[category] || [];
    if (!fields.length) return "";
    return `
      <div class="form-section" id="catalog-tech-section">
        <h2>Caractéristiques</h2>
        <div id="catalog-characteristics">
          <div class="form-grid">
            ${fields.map((field) => fieldMarkup(field, values)).join("")}
          </div>
        </div>
      </div>
    `;
  };

  const readValues = (container) => {
    const values = {};
    if (!container) return values;
    container.querySelectorAll("input, select, textarea").forEach((field) => {
      if (!field.name || (field.name !== "power_w" && !field.name.startsWith("spec_"))) return;
      const key = field.name === "power_w" ? "power_w" : field.name.slice(5);
      values[key] = field.value;
    });
    return values;
  };

  const categoryValues = new Map();
  let activeCategory = categorySelect.value || "";
  const referenceField = form.querySelector("[data-pump-reference-field]");
  const referenceInput = form.querySelector("input[name='reference']");
  const brandInput = form.querySelector("input[name='brand']");
  const requiredMarkers = form.querySelectorAll("[data-non-pump-required-marker]");
  const stockField = form.querySelector("[data-pump-stock-field]");
  const priceLabel = form.querySelector("[data-current-price-label]");
  const priceNote = form.querySelector("[data-pump-price-note]");
  const vatLabel = form.querySelector("[data-vat-label]");
  const vatInput = form.querySelector("input[name='vat_rate']");

  const syncPumpCommercialFields = (category) => {
    const isPump = category === "pumps";
    if (referenceField) referenceField.hidden = isPump;
    if (stockField) stockField.hidden = isPump;
    if (referenceInput) referenceInput.required = !isPump;
    if (brandInput) brandInput.required = !isPump;
    requiredMarkers.forEach((marker) => {
      marker.hidden = isPump;
    });
    if (priceLabel) priceLabel.textContent = isPump ? "Prix interne PT *" : "Prix HT *";
    if (priceNote) priceNote.hidden = !isPump;
    if (vatLabel) vatLabel.textContent = isPump ? "TVA pompe dans Regles Pompage" : "TVA *";
    if (vatInput) {
      vatInput.required = !isPump;
      if (isPump && vatInput.dataset.vatExplicit !== "1") {
        vatInput.value = "";
      } else if (!isPump && !vatInput.value && vatInput.dataset.vatExplicit !== "1") {
        vatInput.value = "20";
      }
    }
  };

  const currentSection = document.getElementById("catalog-tech-section");
  const currentContainer = document.getElementById("catalog-characteristics");
  if (currentSection && currentContainer && activeCategory) {
    categoryValues.set(activeCategory, readValues(currentContainer));
  }

  const renderCategory = (category) => {
    const values = categoryValues.get(category) || {};
    shell.innerHTML = sectionMarkup(category, values);
  };

  const syncCategory = () => {
    const nextCategory = categorySelect.value || "";
    if (activeCategory) {
      const visibleContainer = document.getElementById("catalog-characteristics");
      if (visibleContainer) {
        categoryValues.set(activeCategory, readValues(visibleContainer));
      }
    }
    activeCategory = nextCategory;
    syncPumpCommercialFields(nextCategory);
    if (!nextCategory || !(CATEGORY_FIELDS[nextCategory] || []).length) {
      shell.innerHTML = "";
      return;
    }
    renderCategory(nextCategory);
  };

  categorySelect.addEventListener("change", syncCategory);
  syncPumpCommercialFields(activeCategory);
})();
