(() => {
  const form = document.querySelector("[data-catalog-form]");
  const categorySelect = document.getElementById("catalog-category");
  const shell = document.getElementById("catalog-tech-shell");
  if (!form || !categorySelect || !shell) return;

  const CATEGORY_FIELDS = {
    panels: [
      { key: "power_w", label: "Puissance du panneau", kind: "number", unit: "W", required: true },
    ],
    batteries: [
      { key: "capacity_kwh", label: "Capacité", kind: "number", unit: "kWh", required: true },
    ],
    inverters: [
      { key: "type", label: "Type", kind: "choice", choices: ["on_grid", "off_grid", "hybrid"], required: true },
      { key: "power_kw", label: "Puissance", kind: "number", unit: "kW", required: true },
      { key: "phases", label: "Phase", kind: "choice", choices: ["monophase", "triphase"], required: true },
    ],
    pumps: [
      { key: "power_hp", label: "Puissance", kind: "number", unit: "CV", required: true },
      { key: "phases", label: "Phase", kind: "choice", choices: ["monophase", "triphase"] },
    ],
    drives: [
      { key: "power_kw", label: "Puissance", kind: "number", unit: "kW", required: true },
      { key: "phases", label: "Phase", kind: "choice", choices: ["monophase", "triphase"], required: true },
    ],
    ev_chargers: [
      { key: "power_kw", label: "Puissance", kind: "number", unit: "kW", required: true },
      { key: "phases", label: "Phase", kind: "choice", choices: ["monophase", "triphase"] },
      { key: "connector", label: "Connecteur", kind: "choice", choices: ["Type 1", "Type 2", "CCS", "CHAdeMO"] },
    ],
    protections: [
      { key: "protection_type", label: "Type", kind: "choice", choices: ["Disjoncteur", "Parafoudre", "Fusible", "Sectionneur", "Coffret", "Autre"], required: true },
      { key: "current_a", label: "Courant", kind: "number", unit: "A" },
      { key: "dc_or_ac", label: "Courant électrique", kind: "choice", choices: ["dc", "ac"] },
    ],
    cables: [
      { key: "dc_or_ac", label: "Type", kind: "choice", choices: ["dc", "ac"] },
      { key: "section_mm2", label: "Section", kind: "number", unit: "mm²", required: true },
    ],
    structures: [
      { key: "structure_type", label: "Type de structure", kind: "text", required: true },
    ],
    accessories: [],
    thermal: [
      { key: "tank_volume_l", label: "Volume du ballon", kind: "number", unit: "L", required: true },
    ],
    other: [],
  };

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

  const fieldName = (field) => `spec_${field.key}`;

  const fieldMarkup = (field, values = {}) => {
    const rawValue = values[field.key] ?? "";
    const required = field.required ? ' required data-required="1"' : "";
    const wide = ["power_w", "power_kw", "capacity_kwh", "power_hp", "tank_volume_l", "section_mm2"].includes(field.key)
      ? " full"
      : "";
    const input = field.kind === "choice"
      ? `<select name="${fieldName(field)}"${required}>
          <option value="">Choisir</option>
          ${field.choices.map((choice) => `<option value="${escapeHtml(choice)}"${String(rawValue) === String(choice) ? " selected" : ""}>${labelFor(field, choice)}</option>`).join("")}
        </select>`
      : `<input
          ${field.kind === "number" || field.kind === "integer" || field.kind === "percent" ? `type="number" step="${field.kind === "integer" ? "1" : "any"}"` : ""}
          name="${fieldName(field)}"
          value="${escapeHtml(rawValue)}"
          ${required}
          ${field.key === "power_hp" ? 'placeholder="ex. 15"' : ""}
        >`;

    return `<label class="${wide.trim()}">
      ${escapeHtml(field.label)}${field.required ? " *" : ""}
      ${input}
      ${field.unit ? `<small>Unité : ${escapeHtml(field.unit)}</small>` : ""}
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
      if (!field.name || !field.name.startsWith("spec_")) return;
      const key = field.name.slice(5);
      values[key] = field.value;
    });
    return values;
  };

  const categoryValues = new Map();
  let activeCategory = categorySelect.value || "";

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
    if (!nextCategory || !(CATEGORY_FIELDS[nextCategory] || []).length) {
      shell.innerHTML = "";
      return;
    }
    renderCategory(nextCategory);
  };

  categorySelect.addEventListener("change", syncCategory);
})();
