const publicView = window.PUBLIC_QUOTE || {};
const publicUrls = window.PUBLIC_QUOTE_URLS || {};

let activeOffer = publicView.recommended_offer || (publicView.offers || [])[0] || null;
window.PUBLIC_QUOTE_ACTIVE = activeOffer;

initScrollReveal();
renderPublicQuote();
bindDetailButtons();
bindVisitPanel();

function renderPublicQuote() {
  renderOfferTabs();
  renderCurrentOffer(true);
}

function initScrollReveal() {
  const items = document.querySelectorAll(".reveal-on-scroll");
  if (!items.length || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    items.forEach((item) => item.classList.add("is-visible"));
    return;
  }

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.18 });

  items.forEach((item) => observer.observe(item));
}

function renderOfferTabs() {
  const container = document.querySelector("#offer-tabs");
  const offers = publicView.offers || [];
  if (!container || !offers.length) {
    return;
  }

  container.innerHTML = offers.map((offer) => `
    <button type="button" class="offer-tab ${isActiveOffer(offer) ? "active" : ""}" data-offer-level="${offer.level}">
      ${offer.name || "Solution"}${offer.recommended ? " ⭐" : ""}
    </button>
  `).join("");

  container.querySelectorAll("[data-offer-level]").forEach((button) => {
    button.addEventListener("click", async () => {
      const offer = offers.find((item) => item.level === button.dataset.offerLevel);
      if (!offer) return;
      activeOffer = offer;
      renderCurrentOffer();
      renderOfferTabs();
      await saveOfferChoice(offer.level);
    });
  });
}

function renderCurrentOffer(immediate = false) {
  const offer = activeOffer;
  if (!offer) return;
  window.PUBLIC_QUOTE_ACTIVE = offer;

  swapContent("#compact-offer-name", () => renderCompactTitle(offer), immediate);
  swapContent("#compact-solution-list", () => renderCompactSolution(offer), immediate);
  swapContent("#compact-total-ttc", () => renderCompactPrice(offer), immediate);
  swapContent("#compact-total-ht", () => renderCompactPriceLines(offer), immediate);
  swapContent("#result-spotlight", () => renderSpotlight(offer), immediate);
  swapContent("#price-card", () => renderPriceCard(offer), immediate);
  swapContent("#equipment-grid", () => renderEquipment(offer.main_components || []), immediate);
}

function isExistingPumpMode() {
  const final = publicView.final_results || {};
  return publicView.project === "pumping" && String(final.pump_rule_mode || "").trim().toLowerCase() === "existing_pump_cv";
}

function isRecommendedPumpMode() {
  const final = publicView.final_results || {};
  return publicView.project === "pumping" && String(final.pump_rule_mode || "").trim().toLowerCase() === "recommended_curve";
}

function phaseLabel(value) {
  const normalized = String(value || "").trim().toLowerCase();
  return {
    monophase: "Monophasé",
    mono: "Monophasé",
    triphase: "Triphasé",
    tri: "Triphasé",
    three_phase: "Triphasé",
  }[normalized] || (value ? String(value) : "");
}

function pumpingExistingSummaryRows(offer) {
  const final = publicView.final_results || {};
  const drive = offerLine(offer, "drives");
  const driveLabel = [drive?.brand, displayNumber(final.solar_drive_kw, 2, "kW")].filter(Boolean).join(" ").trim() || displayNumber(final.solar_drive_kw, 2, "kW");
  const panelCount = hasValue(final.panels) ? `${displayNumber(final.panels, 0)} × ` : "";
  const panelPower = hasValue(final.panel_power_w) ? displayNumber(final.panel_power_w, 0) : "";
  return [
    { label: "Pompe existante", value: displayNumber(final.pump_power_cv, 1, "CV") || "Validation HeliAntha" },
    { label: "Panneaux", value: `${panelCount}${panelPower} W`.trim() || "Validation HeliAntha" },
    { label: "Puissance solaire", value: displayNumber(final.pv_power_kwp || final.installed_power_kwp, 2, "kWp") || "Validation HeliAntha" },
    { label: "Variateur", value: driveLabel || "Validation HeliAntha" },
    { label: "Phase", value: phaseLabel(final.phase) || "Validation HeliAntha" },
  ];
}

function pumpingRecommendedSummaryRows(offer) {
  const final = publicView.final_results || {};
  const panelCount = hasValue(final.panels) ? displayNumber(final.panels, 0) : "";
  const panelPower = hasValue(final.panel_power_w) ? displayNumber(final.panel_power_w, 0) : "";
  const panelsLabel = panelCount && panelPower ? `${panelCount} × ${panelPower} W` : "Validation HeliAntha";
  const driveLabel = [final.drive_brand, displayNumber(final.solar_drive_kw, 2, "kW")].filter(Boolean).join(" ").trim();
  const rows = [
    { label: "Pompe recommandée", value: displayNumber(final.selected_pump_cv, 1, "CV") || "Validation HeliAntha" },
    ...(final.selected_outlet_diameter ? [{ label: "Sortie de refoulement", value: final.selected_outlet_diameter }] : []),
    { label: "Débit demandé", value: displayNumber(final.flow_m3_h, 2, "m³/h") || "Validation HeliAntha" },
    { label: "HMT demandée", value: displayNumber(final.hmt_m, 1, "m") || "Validation HeliAntha" },
  ];

  if (final.solar_rule_defined === false) {
    rows.push({
      label: "Configuration solaire",
      value: "À définir par HeliAntha",
      note: `La pompe adaptée a été identifiée à ${displayNumber(final.selected_pump_cv, 1, "CV") || "cette puissance"}, mais la configuration solaire correspondante doit encore être définie.`,
    });
    return rows;
  }

  rows.push(
    { label: "Panneaux", value: panelsLabel },
    { label: "Puissance solaire", value: displayNumber(final.pv_power_kwp || final.installed_power_kwp, 2, "kWp") || "Validation HeliAntha" },
    { label: "Variateur", value: driveLabel || offerPowerSummary(offer, "drives") || "Validation HeliAntha" },
    { label: "Phase", value: phaseLabel(final.phase) || "Validation HeliAntha" },
  );
  return rows;
}

function renderCompactTitle(offer) {
  const title = document.querySelector("#compact-offer-name");
  if (title) title.textContent = offer.name || "Solution HeliAntha";
}

function renderCompactSolution(offer) {
  const container = document.querySelector("#compact-solution-list");
  if (!container) return;

  container.innerHTML = compactSolutionRows(offer).map((row) => `
    <li>
      <span>${row.label}</span>
      <strong>${row.value}</strong>
    </li>
  `).join("");
}

function renderCompactPrice(offer) {
  const total = document.querySelector("#compact-total-ttc");
  if (!total) return;
  const financial = offer.financial_breakdown || {};
  total.textContent = offer.price_ttc_label || offer.price_label || formatMoney(financial.total_ttc, financial.currency || "DH");
}

function renderCompactPriceLines(offer) {
  const financial = offer.financial_breakdown || {};
  const currency = financial.currency || "DH";
  const ht = document.querySelector("#compact-total-ht");
  const vat = document.querySelector("#compact-total-vat");
  if (ht) ht.textContent = `Total HT : ${formatMoney(financial.total_ht, currency)}`;
  if (vat) vat.textContent = `TVA : ${formatMoney(financial.vat, currency)}`;
}

function compactSolutionRows(offer) {
  if (publicView.project === "photovoltaic") {
    return compactPhotovoltaicRows(offer);
  }
  if (publicView.project === "pumping") {
    return compactPumpingRows(offer);
  }
  return [{ label: "Configuration", value: "Preparation HeliAntha" }];
}

function compactPhotovoltaicRows(offer) {
  const final = publicView.final_results || {};
  const phase = phaseLabel(final.phase);
  const inverterLine = offerLine(offer, "inverters");
  const inverterName = [inverterLine?.brand || "SolaX", displayNumber(final.inverter_power_kw || inverterLine?.power_kw, 0, "kW"), phase]
    .filter(Boolean)
    .join(" ");
  return [
    { label: "Configuration solaire", value: panelConfigurationLabel(final) },
    { label: "Repartition", value: stringLayoutLabel(final.string_layout) },
    { label: "Onduleur", value: `Onduleur reseau ${inverterName}`.trim() },
    { label: "Equipements inclus", value: "Protections AC/DC, cablage, limiteur d'injection & supervision, structure de fixation" },
  ];
}

function compactPumpingRows(offer) {
  const final = publicView.final_results || {};
  const drive = offerLine(offer, "drives");
  const driveLabel = [drive?.brand || final.drive_brand, displayNumber(final.solar_drive_kw || drive?.power_kw, 2, "kW"), phaseLabel(final.phase)]
    .filter(Boolean)
    .join(" ");
  const pumpPower = final.selected_pump_cv || final.pump_power_cv || offerPumpPower(offer);
  const pumpLabel = final.pump_rule_mode === "existing_pump_cv"
    ? `Pompe existante ${displayNumber(pumpPower, 1, "CV")}`.trim()
    : `Pompe solaire ${displayNumber(pumpPower, 1, "CV")}`.trim();
  const rows = [
    { label: "Pompe", value: final.selected_outlet_diameter ? `${pumpLabel} - refoulement ${final.selected_outlet_diameter}` : pumpLabel },
  ];
  if (final.solar_rule_defined === false) {
    rows.push({ label: "Configuration solaire", value: "Configuration finale preparee par HeliAntha" });
  } else {
    rows.push(
      { label: "Configuration solaire", value: panelConfigurationLabel(final) },
      { label: "Variateur", value: driveLabel || "Variateur solaire HeliAntha" },
    );
  }
  rows.push({ label: "Equipements inclus", value: "Protections, cablage, structure, installation et mise en service" });
  return rows;
}

function panelConfigurationLabel(final) {
  const count = final.panel_count || final.panels;
  const power = final.panel_power_w;
  const peak = final.installed_power_kwp || final.pv_power_kwp;
  if (hasValue(count) && hasValue(power) && hasValue(peak)) {
    return `${formatNumber(count, 0)} panneaux × ${displayNumber(power, 0, "W")} (Puissance crete : ${displayNumber(peak, 2, "kWc")})`;
  }
  if (hasValue(count) && hasValue(power)) {
    return `${formatNumber(count, 0)} panneaux × ${displayNumber(power, 0, "W")}`;
  }
  return "Configuration solaire HeliAntha";
}

function stringLayoutLabel(layout) {
  if (!Array.isArray(layout) || !layout.length) return "Repartition optimisee par HeliAntha";
  const unique = [...new Set(layout.map((value) => Number(value)))];
  if (unique.length === 1) {
    return `${layout.length} strings de ${formatNumber(unique[0], 0)} panneaux`;
  }
  return `${layout.length} strings : ${layout.map((value) => formatNumber(value, 0)).join(" + ")} panneaux`;
}

function renderPriceCard(offer) {
  const price = document.querySelector("#offer-price");
  const subprice = document.querySelector("#offer-subprice");

  const priceText = offer.price_label || offer.price_ttc_label || "Prix à confirmer";
  const subpriceText = offer.price_ttc_label ? "Estimation TTC" : "Prix préparé par HeliAntha";

  if (price) price.textContent = priceText;
  if (subprice) subprice.textContent = subpriceText;
}

function renderSpotlight(offer) {
  const title = document.querySelector("#offer-name");
  const resultsGrid = document.querySelector("#spotlight-results-grid");
  if (title) title.textContent = offer.name || "Solution HeliAntha";

  if (resultsGrid) {
    resultsGrid.innerHTML = buildTechnicalDetails(offer).map((row) => `
      <article class="metric-card metric-card-soft">
        <small>${row.label}</small>
        <strong>${row.value}</strong>
        ${row.note ? `<p class="metric-note">${row.note}</p>` : ""}
      </article>
    `).join("");
  }
}

function renderEquipment(components) {
  const container = document.querySelector("#equipment-grid");
  if (!container) return;

  if (!components.length) {
    container.innerHTML = `<div class="empty-state">Le materiel final sera confirme par HeliAntha lors de l'etude technique.</div>`;
    return;
  }

  container.innerHTML = components.map((item) => {
    return `
      <article class="equipment-card">
        <span class="equipment-icon">${iconForEquipment(item.category)}</span>
        <small>${labelForCategory(item.category)}</small>
        <h3>${item.title || "Materiel a confirmer"}</h3>
        <p>${item.summary || "Validation HeliAntha"}</p>
      </article>
    `;
  }).join("");
}

function renderDiagram(diagram) {
  const container = document.querySelector("#solution-diagram");
  if (!container) return;

  container.innerHTML = buildDiagramMarkup(diagram);
  container.setAttribute("aria-label", energyFlowSummary(activeOffer || {}));
}

function renderEnergyFlowSummary(offer) {
  const element = document.querySelector("#energy-flow-summary");
  if (element) {
    element.textContent = energyFlowSummary(offer);
  }
}

function buildDiagramMarkup(diagram) {
  const project = diagram.project || publicView.project;
  const offer = activeOffer || {};
  const final = publicView.final_results || {};

  if (project === "pumping") {
    if (isExistingPumpMode()) {
      return `
        <div class="diagram-vertical">
          ${diagramNode("☀️", "Champ PV", offerPvSummary(offer) || displayNumber(final.pv_power_kwp || final.installed_power_kwp, 2, "kWp"))}
          <span class="diagram-connector"></span>
          ${diagramNode("⚙️", "Variateur", [offerLine(offer, "drives")?.brand, offerLine(offer, "drives")?.model].filter(Boolean).join(" ") || displayNumber(final.solar_drive_kw, 2, "kW"))}
          <span class="diagram-connector"></span>
          ${diagramNode("💧", "Pompe", displayNumber(final.pump_power_cv, 1, "CV") || "Validation HeliAntha")}
        </div>
      `;
    }
    if (isRecommendedPumpMode() && final.solar_rule_defined === false) {
      return `
        <div class="diagram-vertical">
          ${diagramNode("💧", "Pompe recommandée", displayNumber(final.selected_pump_cv, 1, "CV") || "Validation HeliAntha")}
          <span class="diagram-connector"></span>
          ${diagramNode("⚙️", "Configuration solaire", "À définir par HeliAntha")}
        </div>
      `;
    }
    const driveLabel = [final.drive_brand, displayNumber(final.solar_drive_kw, 2, "kW")].filter(Boolean).join(" ").trim();
    return `
      <div class="diagram-vertical">
        ${diagramNode("☀️", "Champ PV", offerPvSummary(offer) || displayNumber(final.pv_power_kwp || final.installed_power_kwp, 2, "kWp"))}
        <span class="diagram-connector"></span>
        ${diagramNode("⚙️", "Variateur", driveLabel || offerPowerSummary(offer, "drives") || "Validation HeliAntha")}
        <span class="diagram-connector"></span>
        ${diagramNode("💧", "Pompe", displayNumber(final.selected_pump_cv, 1, "CV") || offerPowerSummary(offer, "pumps") || "Validation HeliAntha")}
      </div>
    `;
  }

  if (project === "photovoltaic") {
    const strings = Array.isArray(final.string_layout) ? final.string_layout.join(" + ") : "";
    return `
      <div class="diagram-vertical">
        ${diagramNode("☀️", "Champ PV", offerPvSummary(offer) || displayNumber(final.installed_power_kwp, 2, "kWc"))}
        <span class="diagram-connector"></span>
        ${diagramNode("⚡", "Onduleur SolaX", offerPowerSummary(offer, "inverters") || displayNumber(final.inverter_power_kw, 2, "kW"))}
        <span class="diagram-connector"></span>
        ${diagramNode("🏢", "Consommation", strings ? `${strings} panneaux/string` : "On-Grid")}
      </div>
    `;
  }

  return "";
}

function diagramNode(icon, title, value) {
  return `
    <article class="diagram-node">
      <span>${icon}</span>
      <strong>${title}</strong>
      <small>${value || "Validation HeliAntha"}</small>
    </article>
  `;
}

function energyFlowSummary(offer) {
  const final = publicView.final_results || {};
  const project = publicView.project;

  if (project === "pumping") {
    if (isExistingPumpMode()) {
      return "";
    }
    if (isRecommendedPumpMode() && final.solar_rule_defined === false) {
      return "La pompe adaptée est identifiée. La configuration solaire HeliAntha correspondante reste à définir.";
    }
    return "Le champ photovoltaïque alimente le variateur puis la pompe.";
  }
  if (project === "photovoltaic") {
    return "Le champ photovoltaïque alimente l’onduleur réseau SolaX puis le tableau électrique du site.";
  }
  return "";
}

function buildTechnicalDetails(offer) {
  const final = publicView.final_results || {};
  const project = publicView.project;
  const rows = [];

  if (project === "pumping") {
    if (isExistingPumpMode()) {
      rows.push(...pumpingExistingSummaryRows(offer));
      return rows.slice(0, 8);
    }
    if (isRecommendedPumpMode()) {
      rows.push(...pumpingRecommendedSummaryRows(offer));
      return rows.slice(0, 8);
    }
    return rows;
  }

  if (project === "photovoltaic") {
    rows.push({ label: "Puissance cible", value: displayNumber(final.target_kwp, 2, "kWc") });
    rows.push({ label: "Panneaux", value: `${displayNumber(final.panel_count, 0)} × ${displayNumber(final.panel_power_w, 0, "W")}` });
    rows.push({ label: "Puissance installée", value: displayNumber(final.installed_power_kwp, 2, "kWc") });
    rows.push({ label: "Strings", value: Array.isArray(final.string_layout) ? final.string_layout.join(" + ") : "Validation HeliAntha" });
    rows.push({ label: "Onduleur", value: displayNumber(final.inverter_power_kw, 2, "kW") });
  }

  return rows.slice(0, 8);
}

function offerLine(offer, category) {
  return (offer.selected_equipment || []).find((item) => item.category === category);
}

function offerPvPowerKw(offer) {
  const panels = offerLine(offer, "panels");
  if (!panels) return null;
  if (hasValue(panels.power_w) && hasValue(panels.quantity)) return (Number(panels.power_w) * Number(panels.quantity)) / 1000;
  if (hasValue(panels.power_kw) && hasValue(panels.quantity)) return Number(panels.power_kw) * Number(panels.quantity);
  return null;
}

function offerPowerKw(offer, category) {
  const line = offerLine(offer, category);
  if (!line || !hasValue(line.power_kw)) return null;
  return Number(line.power_kw);
}

function offerPumpPower(offer) {
  const line = offerLine(offer, "pumps");
  if (!line) return null;
  if (hasValue(line.power_cv)) return Number(line.power_cv);
  if (hasValue(line.power_kw)) return Number(line.power_kw);
  return null;
}

function offerPvSummary(offer) {
  const value = offerPvPowerKw(offer);
  return hasValue(value) ? `${formatNumber(value, 2)} kWp` : "";
}

function offerPanelSummary(offer) {
  const line = offerLine(offer, "panels");
  if (!line || !hasValue(line.quantity)) return "";
  return `${formatNumber(line.quantity, 0)} panneau(x)`;
}

function offerPowerSummary(offer, category) {
  if (category === "pumps") {
    const line = offerLine(offer, "pumps");
    if (line && hasValue(line.power_cv)) {
      return `${formatNumber(line.power_cv, 1)} CV`;
    }
    const value = offerPumpPower(offer);
    return hasValue(value) ? `${formatNumber(value, 2)} kW` : "";
  }
  const value = offerPowerKw(offer, category);
  return hasValue(value) ? `${formatNumber(value, 2)} kW` : "";
}

function primaryEquipmentLabel(offer) {
  const components = offer.main_components || [];
  if (!components.length) return "Validation HeliAntha";
  const primary = components[0];
  return [primary.title, primary.summary].filter(Boolean).join(" · ") || "Validation HeliAntha";
}

function displayNumber(value, digits, unit) {
  if (!hasValue(value)) return "";
  return `${formatNumber(value, digits)} ${unit}`.trim();
}

function displayNumberValue(value, digits) {
  if (!hasValue(value)) return "—";
  return formatNumber(value, digits);
}

function formatMoney(value, currency = "DH") {
  if (!hasValue(value)) return "-";
  return `${formatNumber(value, 0)} ${currency}`.trim();
}

function hasValue(value) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}

function swapContent(selector, renderFn, immediate = false) {
  const element = document.querySelector(selector);
  if (!element) return;
  if (immediate || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    renderFn();
    return;
  }
  element.classList.add("is-swapping");
  window.setTimeout(() => {
    renderFn();
    requestAnimationFrame(() => element.classList.remove("is-swapping"));
  }, 140);
}

function formatNumber(value, digits = 1) {
  return new Intl.NumberFormat("fr-FR", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  }).format(Number(value || 0));
}

function iconForEquipment(category) {
  return {
    panels: "☀️",
    inverters: "⚡",
    pumps: "💧",
    drives: "⚙️",
    structures: "▦",
  }[category] || "🧩";
}

function labelForCategory(category) {
  return {
    panels: "Panneaux",
    inverters: "Onduleur",
    pumps: "Pompe",
    drives: "Variateur",
    structures: "Structure",
  }[category] || "Matériel";
}

function sourceLabel(sourceType) {
  return {
    product: "Donnée produit",
    manufacturer: "Donnée produit",
    fallback: "Valeur de secours",
    demo: "HeliAntha",
    manual_validation: "Validation HeliAntha",
  }[sourceType] || "Validation HeliAntha";
}

function isActiveOffer(offer) {
  return activeOffer && offer.level === activeOffer.level;
}

function bindVisitPanel() {
  const panel = document.querySelector("#visit-panel");
  const toggle = document.querySelector("#visit-toggle");
  const close = document.querySelector("#visit-close");
  const closeButton = document.querySelector("#visit-close-button");
  const cancel = document.querySelector("#visit-cancel");
  const form = document.querySelector("#visit-form");

  if (!panel || !form) return;

  const openPanel = () => {
    panel.hidden = false;
    panel.classList.add("open");
  };
  const closePanel = () => {
    panel.classList.remove("open");
    panel.hidden = true;
  };

  [toggle, document.querySelector("#visit-toggle-bottom")].forEach((element) => element?.addEventListener("click", openPanel));
  [close, closeButton, cancel].forEach((element) => element?.addEventListener("click", closePanel));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    if (!data.address || !data.phone) {
      toast("Merci d’indiquer au moins l’adresse et le téléphone.");
      return;
    }

    try {
      const response = await fetch(publicUrls.visit, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Erreur lors de l’envoi");
      }
      toast(payload.message || "Demande de visite enregistrée.");
      closePanel();
      form.reset();
    } catch (error) {
      toast(error.message || "Impossible d’enregistrer la demande.");
    }
  });
}

function bindDetailButtons() {
  const techButton = document.querySelector("#open-tech-details");
  const warningButton = document.querySelector("#open-warning-details");
  const techDetails = document.querySelector("#technical-details-section");
  const warningSection = document.querySelector("#warnings-section");

  techButton?.addEventListener("click", () => {
    if (techDetails && "open" in techDetails) {
      techDetails.open = true;
    }
    techDetails?.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  warningButton?.addEventListener("click", () => {
    const warningDetails = warningSection?.querySelector(".tech-details");
    if (warningDetails && "open" in warningDetails) {
      warningDetails.open = true;
    }
    warningSection?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

async function saveOfferChoice(level) {
  if (!publicUrls.selectOffer || !publicView.quote_number || !level) return;
  try {
    await fetch(publicUrls.selectOffer, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ level }),
    });
  } catch (_) {
    /* no-op */
  }
}

function toast(message) {
  const element = document.querySelector("#toast");
  if (!element) return;
  element.textContent = message;
  element.classList.add("show");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => element.classList.remove("show"), 3000);
}
