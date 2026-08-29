const publicView = window.PUBLIC_QUOTE || {};
const publicUrls = window.PUBLIC_QUOTE_URLS || {};

let activeOffer = publicView.recommended_offer || (publicView.offers || [])[0] || null;
let equipmentAutoScrollRaf = null;
let equipmentAutoScrollPaused = false;
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

  swapContent("#result-spotlight", () => renderSpotlight(offer), immediate);
  swapContent("#price-card", () => renderPriceCard(offer), immediate);
  swapContent("#equipment-grid", () => renderEquipment(offer.main_components || []), immediate);
  swapContent("#solution-diagram", () => renderDiagram(offer.diagram || {}), immediate);
  swapContent("#energy-flow-summary", () => renderEnergyFlowSummary(offer), immediate);
}

function isExistingPumpMode() {
  const final = publicView.final_results || {};
  return publicView.project === "pumping" && String(final.pump_rule_mode || "").trim().toLowerCase() === "existing_pump_cv";
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
    { label: "Pompe existante", value: displayNumber(final.pump_power_cv, 1, "CV") || "À confirmer" },
    { label: "Panneaux", value: `${panelCount}${panelPower} W`.trim() || "À confirmer" },
    { label: "Puissance solaire", value: displayNumber(final.pv_power_kwp || final.installed_power_kwp, 2, "kWp") || "À confirmer" },
    { label: "Variateur", value: driveLabel || "À confirmer" },
    { label: "Phase", value: phaseLabel(final.phase) || "À confirmer" },
  ];
}

function renderPriceCard(offer) {
  const price = document.querySelector("#offer-price");
  const subprice = document.querySelector("#offer-subprice");

  const priceText = offer.price_ttc_label || "Prix à confirmer";
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

  container.innerHTML = components.map((item) => `
    <article class="equipment-card">
      <span class="equipment-icon">${iconForEquipment(item.category)}</span>
      <small>${labelForCategory(item.category)}</small>
      <h3>${item.title || "Materiel a confirmer"}</h3>
      <p>${item.summary || "A confirmer lors de l'etude technique"}</p>
      ${item.reference ? `<p class="offer-meta">Reference ${item.reference}</p>` : `<p class="offer-meta">Reference finale a confirmer</p>`}
      <span class="equipment-source">${sourceLabel(item.source_type)}</span>
    </article>
  `).join("");

  startEquipmentAutoScroll(container);
}

function renderTechnicalDetails(offer) {
  const container = document.querySelector("#technical-details-grid");
  if (!container) return;

  const rows = buildTechnicalDetails(offer);
  container.innerHTML = rows.map((row) => `
    <article class="metric-card metric-card-soft">
      <small>${row.label}</small>
      <strong>${row.value}</strong>
      ${row.note ? `<p class="metric-note">${row.note}</p>` : ""}
    </article>
  `).join("");
}

function startEquipmentAutoScroll(container) {
  if (!container || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return;
  }

  if (equipmentAutoScrollRaf) {
    cancelAnimationFrame(equipmentAutoScrollRaf);
    equipmentAutoScrollRaf = null;
  }

  let lastTime = performance.now();
  const speed = 10; // pixels per second
  let direction = 1;
  const pauseFor = (ms) => {
    equipmentAutoScrollPaused = true;
    window.setTimeout(() => {
      equipmentAutoScrollPaused = false;
      lastTime = performance.now();
    }, ms);
  };

  const tick = (now) => {
    const delta = (now - lastTime) / 1000;
    lastTime = now;

    if (!equipmentAutoScrollPaused && container.scrollWidth > container.clientWidth + 2) {
      const maxScroll = container.scrollWidth - container.clientWidth;
      let next = container.scrollLeft + direction * speed * delta;

      if (next >= maxScroll) {
        next = maxScroll;
        direction = -1;
        pauseFor(1600);
      } else if (next <= 0) {
        next = 0;
        direction = 1;
        pauseFor(1600);
      }

      container.scrollLeft = next;
    }

    equipmentAutoScrollRaf = requestAnimationFrame(tick);
  };

  container.onmouseenter = () => {
    equipmentAutoScrollPaused = true;
  };
  container.onmouseleave = () => {
    equipmentAutoScrollPaused = false;
    lastTime = performance.now();
  };
  container.onfocusin = () => {
    equipmentAutoScrollPaused = true;
  };
  container.onfocusout = () => {
    equipmentAutoScrollPaused = false;
    lastTime = performance.now();
  };
  container.onwheel = () => {
    pauseFor(500);
  };

  equipmentAutoScrollPaused = false;
  equipmentAutoScrollRaf = requestAnimationFrame(tick);
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
          ${diagramNode("💧", "Pompe", displayNumber(final.pump_power_cv, 1, "CV") || "À confirmer")}
        </div>
      `;
    }
    return `
      <div class="diagram-vertical">
        ${diagramNode("☀️", "Champ PV", offerPvSummary(offer) || displayNumber(final.pv_power_kwp || final.installed_power_kwp, 2, "kWp"))}
        <span class="diagram-connector"></span>
        ${diagramNode("⚙️", "Variateur", offerPowerSummary(offer, "drives") || displayNumber(final.solar_drive_kw, 2, "kW"))}
        <span class="diagram-connector"></span>
        ${diagramNode("💧", "Pompe", offerPowerSummary(offer, "pumps") || displayNumber(final.pump_power_cv, 1, "CV") || displayNumber(final.pump_power_kw, 2, "kW"))}
      </div>
    `;
  }

  if (project === "ongrid") {
    return `
      <div class="diagram-vertical">
        ${diagramNode("☀️", "Panneaux", offerPvSummary(offer) || displayNumber(final.pv_power_kwp || final.installed_power_kwp, 2, "kWp"))}
        <span class="diagram-connector"></span>
        ${diagramNode("⚡", "Onduleur", offerPowerSummary(offer, "inverters") || displayNumber(final.inverter_selected_kw, 2, "kW"))}
        <span class="diagram-connector"></span>
        ${diagramNode("🏢", "Bâtiment", displayNumber(final.annual_production_kwh, 0, "kWh/an"))}
        <span class="diagram-connector"></span>
        ${diagramNode("🔌", "Réseau", "Complément si nécessaire")}
      </div>
    `;
  }

  if (project === "ev") {
    return `
      <div class="diagram-vertical">
        ${diagramNode("🏠", "Installation", displayNumber(final.available_power_kw, 2, "kW disponibles"))}
        <span class="diagram-connector"></span>
        ${diagramNode("⚡", "Borne", offerPowerSummary(offer, "ev_chargers") || displayNumber(final.charger_power_kw, 2, "kW"))}
        <span class="diagram-connector"></span>
        ${diagramNode("🚗", "Véhicule", displayNumber(final.recharge_time_h, 2, "h estimées"))}
      </div>
    `;
  }

  if (project === "thermal") {
    return `
      <div class="diagram-vertical">
        ${diagramNode("☀️", "Capteurs", displayNumber(final.collector_surface_m2, 2, "m²"))}
        <span class="diagram-connector"></span>
        ${diagramNode("♨️", "Ballon", offerThermalSummary(offer) || displayNumber(final.tank_capacity_l, 0, "L"))}
        <span class="diagram-connector"></span>
        ${diagramNode("🚿", "Eau chaude", displayNumber(final.daily_hot_water_l, 0, "L/j"))}
      </div>
    `;
  }

  if (project === "hybrid") {
    return `
      <div class="diagram-hybrid">
        <div class="diagram-hybrid-top">
          ${diagramNode("☀️", "Champ PV", offerPvSummary(offer) || displayNumber(final.pv_power_kwp || final.installed_power_kwp, 2, "kWp"))}
        </div>
        <span class="diagram-connector"></span>
        <div class="diagram-hybrid-center">
          ${diagramNode("⚡", "Onduleur hybride", offerPowerSummary(offer, "inverters") || displayNumber(final.inverter_selected_kw, 2, "kW"))}
        </div>
        <div class="diagram-branches">
          ${diagramNode("🔋", "Batterie", offerBatterySummary(offer) || displayNumber(final.battery_commercial_kwh, 2, "kWh"))}
          ${diagramNode("🏠", "Charges", displayNumber(final.daily_consumption_kwh, 2, "kWh/j"))}
        </div>
      </div>
    `;
  }

  return `
    <div class="diagram-hybrid">
      <div class="diagram-hybrid-top">
        ${diagramNode("☀️", "Champ PV", offerPvSummary(offer) || displayNumber(final.pv_power_kwp || final.installed_power_kwp, 2, "kWp"))}
      </div>
      <span class="diagram-connector"></span>
      <div class="diagram-hybrid-center">
        ${diagramNode("⚡", "Onduleur", offerPowerSummary(offer, "inverters") || displayNumber(final.inverter_selected_kw, 2, "kW"))}
      </div>
      <div class="diagram-branches">
        ${diagramNode("🔋", "Batterie", offerBatterySummary(offer) || displayNumber(final.battery_commercial_kwh, 2, "kWh"))}
        ${diagramNode("🏠", "Maison", displayNumber(final.daily_consumption_kwh, 2, "kWh/j"))}
      </div>
    </div>
  `;
}

function diagramNode(icon, title, value) {
  return `
    <article class="diagram-node">
      <span>${icon}</span>
      <strong>${title}</strong>
      <small>${value || "À confirmer"}</small>
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
    return "Le champ photovoltaïque alimente le variateur puis la pompe.";
  }
  if (project === "ongrid") {
    return `Les panneaux alimentent l’onduleur puis le bâtiment. Le réseau reste disponible en complément si nécessaire. Puissance solaire affichée : ${offerPvSummary(offer) || displayNumber(final.pv_power_kwp || final.installed_power_kwp, 2, "kWp") || "à confirmer"}.`;
  }
  if (project === "ev") {
    return `L’installation alimente la borne de recharge, puis le véhicule. La puissance de charge retenue est de ${offerPowerSummary(offer, "ev_chargers") || displayNumber(final.charger_power_kw, 2, "kW") || "à confirmer"}.`;
  }
  if (project === "thermal") {
    return `Les capteurs chauffent le ballon pour couvrir un besoin d’environ ${displayNumber(final.daily_hot_water_l, 0, "L/j") || "à confirmer"} en eau chaude.`;
  }
  if (project === "hybrid") {
    return "Le photovoltaïque alimente l’onduleur hybride, qui répartit l’énergie entre les charges, la batterie et le réseau selon la configuration retenue.";
  }
  return "Le photovoltaïque alimente l’onduleur, puis l’énergie est répartie entre la maison et la batterie lorsque le stockage est prévu.";
}

function primaryMetricForOffer(offer) {
  const final = publicView.final_results || {};

  if (["offgrid", "ongrid", "hybrid", "pumping"].includes(publicView.project)) {
    return {
      value: displayNumberValue(offerPvPowerKw(offer) ?? final.pv_power_kwp ?? final.installed_power_kwp, 2),
      unit: "kWp",
      label: "Puissance solaire recommandée",
    };
  }
  if (publicView.project === "ev") {
    return {
      value: displayNumberValue(offerPowerKw(offer, "ev_chargers") ?? final.charger_power_kw ?? final.requested_power_kw, 2),
      unit: "kW",
      label: "Borne recommandée",
    };
  }
  if (publicView.project === "thermal") {
    return {
      value: displayNumberValue(offerThermalCapacity(offer) ?? final.tank_capacity_l ?? final.daily_hot_water_l, 0),
      unit: "L",
      label: "Capacité du ballon",
    };
  }

  const fallbackMetric = (publicView.metrics || [])[0] || { value: "—", label: "Estimation HeliAntha" };
  const parts = String(fallbackMetric.value || "—").split(" ");
  return {
    value: parts[0] || "—",
    unit: parts.slice(1).join(" ") || "",
    label: fallbackMetric.label || "Estimation HeliAntha",
  };
}

function buildSpotlightHighlights(offer) {
  const final = publicView.final_results || {};
  if (publicView.project === "pumping") {
    if (isExistingPumpMode()) {
      return pumpingExistingSummaryRows(offer).slice(0, 3);
    }
    return [
      { label: "Puissance solaire", value: offerPvSummary(offer) || displayNumber(final.pv_power_kwp || final.installed_power_kwp, 2, "kWp") },
      { label: "Débit", value: displayNumber(final.flow_m3_h, 2, "m³/h") },
      { label: "Hauteur", value: displayNumber(final.hmt_m, 0, "m") },
    ];
  }
  if (publicView.project === "ev") {
    return [
      { label: "Borne", value: offerPowerSummary(offer, "ev_chargers") || displayNumber(final.charger_power_kw, 2, "kW") },
      { label: "Temps", value: displayNumber(final.recharge_time_h, 2, "h") },
      { label: "Puissance dispo.", value: displayNumber(final.available_power_kw, 2, "kW") },
    ];
  }
  if (publicView.project === "thermal") {
    return [
      { label: "Capacité", value: offerThermalSummary(offer) || displayNumber(final.tank_capacity_l, 0, "L") },
      { label: "Capteurs", value: displayNumber(final.collector_surface_m2, 2, "m²") },
      { label: "Besoin", value: displayNumber(final.daily_hot_water_l, 0, "L/j") },
    ];
  }
  return [
    { label: "Puissance solaire", value: offerPvSummary(offer) || displayNumber(final.pv_power_kwp || final.installed_power_kwp, 2, "kWp") },
    { label: "Panneaux", value: offerPanelSummary(offer) || displayNumber(final.panels, 0, "panneau(x)") },
    { label: "Stockage", value: offerBatterySummary(offer) || displayNumber(final.battery_commercial_kwh, 2, "kWh") || "Selon configuration" },
  ];
}

function buildTechnicalDetails(offer) {
  const final = publicView.final_results || {};
  const project = publicView.project;
  const rows = [];

  if (["offgrid", "ongrid", "hybrid", "pumping"].includes(project)) {
    if (project === "pumping" && isExistingPumpMode()) {
      rows.push(...pumpingExistingSummaryRows(offer));
      return rows.slice(0, 8);
    }
    rows.push({ label: "Puissance solaire", value: offerPvSummary(offer) || displayNumber(final.pv_power_kwp || final.installed_power_kwp, 2, "kWp") });
    rows.push({ label: "Panneaux", value: offerPanelSummary(offer) || displayNumber(final.panels, 0, "panneau(x)") });
  }

  if (["offgrid", "hybrid"].includes(project)) {
    rows.push({ label: "Onduleur", value: offerPowerSummary(offer, "inverters") || displayNumber(final.inverter_selected_kw, 2, "kW") });
    rows.push({ label: "Stockage", value: offerBatterySummary(offer) || displayNumber(final.battery_commercial_kwh, 2, "kWh") || "Selon configuration" });
  }

  if (project === "ongrid") {
    const metricCoverage = metricValue("Couverture");
    rows.push({ label: "Onduleur", value: offerPowerSummary(offer, "inverters") || displayNumber(final.inverter_selected_kw, 2, "kW") });
    rows.push({ label: "Production annuelle", value: displayNumber(final.annual_production_kwh, 0, "kWh/an") });
    rows.push({ label: "Couverture estimée", value: metricCoverage || "—" });
  }

  if (project === "pumping") {
    rows.push({ label: "Variateur", value: offerPowerSummary(offer, "drives") || displayNumber(final.solar_drive_kw, 2, "kW") });
    rows.push({ label: "Pompe", value: offerPowerSummary(offer, "pumps") || displayNumber(final.pump_power_cv, 1, "CV") || displayNumber(final.pump_power_kw, 2, "kW") });
    rows.push({ label: "Débit", value: displayNumber(final.flow_m3_h, 2, "m³/h") });
    rows.push({ label: "Hauteur de pompage", value: displayNumber(final.hmt_m, 0, "m") });
  }

  if (project === "ev") {
    rows.push({ label: "Borne", value: offerPowerSummary(offer, "ev_chargers") || displayNumber(final.charger_power_kw, 2, "kW") });
    rows.push({ label: "Temps de charge", value: displayNumber(final.recharge_time_h, 2, "h") });
    rows.push({ label: "Puissance dispo.", value: displayNumber(final.available_power_kw, 2, "kW") });
  }

  if (project === "thermal") {
    rows.push({ label: "Capacité du ballon", value: offerThermalSummary(offer) || displayNumber(final.tank_capacity_l, 0, "L") });
    rows.push({ label: "Capteurs", value: displayNumber(final.collector_surface_m2, 2, "m²") });
    rows.push({ label: "Besoin d'eau chaude", value: displayNumber(final.daily_hot_water_l, 0, "L/j") });
  }

  return rows.slice(0, 8);
}

function metricValue(label) {
  const metric = (publicView.metrics || []).find((item) => String(item.label || "").toLowerCase().includes(label.toLowerCase()));
  return metric ? metric.value : "";
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

function offerBatteryCapacity(offer) {
  const line = offerLine(offer, "batteries");
  if (!line || !hasValue(line.capacity_kwh) || !hasValue(line.quantity)) return null;
  return Number(line.capacity_kwh) * Number(line.quantity);
}

function offerThermalCapacity(offer) {
  const line = offerLine(offer, "thermal");
  if (!line || !hasValue(line.capacity_l)) return null;
  return Number(line.capacity_l);
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

function offerBatterySummary(offer) {
  const value = offerBatteryCapacity(offer);
  return hasValue(value) ? `${formatNumber(value, 2)} kWh` : "";
}

function offerThermalSummary(offer) {
  const value = offerThermalCapacity(offer);
  return hasValue(value) ? `${formatNumber(value, 0)} L` : "";
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
  if (!components.length) return "À confirmer";
  const primary = components[0];
  return [primary.title, primary.summary].filter(Boolean).join(" · ") || "À confirmer";
}

function displayNumber(value, digits, unit) {
  if (!hasValue(value)) return "";
  return `${formatNumber(value, digits)} ${unit}`.trim();
}

function displayNumberValue(value, digits) {
  if (!hasValue(value)) return "—";
  return formatNumber(value, digits);
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
    batteries: "🔋",
    pumps: "💧",
    drives: "⚙️",
    thermal: "♨️",
    ev_chargers: "🔌",
  }[category] || "🧩";
}

function labelForCategory(category) {
  return {
    panels: "Panneaux",
    inverters: "Onduleur",
    batteries: "Batterie",
    pumps: "Pompe",
    drives: "Variateur",
    thermal: "Thermique",
    ev_chargers: "Borne EV",
  }[category] || "Matériel";
}

function sourceLabel(sourceType) {
  return {
    product: "Donnée produit",
    manufacturer: "Donnée produit",
    fallback: "Valeur de secours",
    demo: "HeliAntha",
    manual_validation: "À confirmer",
  }[sourceType] || "À confirmer";
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
