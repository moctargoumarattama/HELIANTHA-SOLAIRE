const STORAGE_KEY = "heliantha_phase4_wizard";
const company = window.HELIANTHA_COMPANY || {};

const DEVICE_LIBRARY = {
  "Éclairage": [
    { name: "Lampe LED", power_w: 12, hours: 6, simultaneous: true, priority: true },
    { name: "Projecteur LED", power_w: 50, hours: 4, simultaneous: true, priority: false },
  ],
  "Cuisine": [
    { name: "Réfrigérateur", power_w: 150, hours: 24, simultaneous: true, priority: true },
    { name: "Congélateur", power_w: 250, hours: 24, simultaneous: true, priority: true },
    { name: "Micro-ondes", power_w: 1200, hours: 0.5, simultaneous: false, priority: false },
    { name: "Bouilloire", power_w: 1800, hours: 0.25, simultaneous: false, priority: false },
  ],
  "Confort": [
    { name: "Ventilateur", power_w: 75, hours: 8, simultaneous: true, priority: false },
    { name: "Climatisation", power_w: 1200, hours: 6, simultaneous: true, priority: false },
    { name: "Chauffe-eau", power_w: 2000, hours: 2, simultaneous: false, priority: false },
  ],
  "Multimédia": [
    { name: "Télévision", power_w: 120, hours: 5, simultaneous: true, priority: false },
    { name: "Ordinateur", power_w: 120, hours: 6, simultaneous: true, priority: true },
    { name: "Box Internet", power_w: 15, hours: 24, simultaneous: true, priority: true },
  ],
  "Équipements techniques": [
    { name: "Pompe", power_w: 750, hours: 2, simultaneous: false, priority: false },
    { name: "Moteur", power_w: 1500, hours: 2, simultaneous: false, priority: false },
    { name: "Machine", power_w: 1000, hours: 3, simultaneous: false, priority: false },
  ],
};

const WIZARD_PROJECT_META = window.HELIANTHA_WIZARD_PROJECTS || {
  pumping: {
    engine_project: "pumping",
    aliases: [],
    payload_fields: ["pump_existing", "existing_pump_cv", "flow_m3_h", "hmt_m"],
    summary_fields: ["pump_existing", "existing_pump_cv", "flow_m3_h", "hmt_m"],
    supports_loads: false,
  },
  off_grid: {
    engine_project: "offgrid",
    aliases: ["offgrid"],
    payload_fields: ["energy_mode", "daily_kwh", "peak_kw", "autonomy", "city", "notes", "loads"],
    summary_fields: ["energy_mode", "daily_kwh", "peak_kw", "autonomy", "city", "loads"],
    supports_loads: true,
  },
  photovoltaic: {
    engine_project: "ongrid",
    aliases: ["ongrid"],
    payload_fields: ["building", "monthly_kwh", "bill", "day_profile", "network", "roof_area", "city"],
    summary_fields: ["building", "monthly_kwh", "bill", "day_profile", "network", "roof_area", "city"],
    supports_loads: false,
  },
  hybrid: {
    engine_project: "hybrid",
    aliases: [],
    payload_fields: ["energy_mode", "daily_kwh", "monthly_kwh", "bill", "peak_kw", "priority_kwh", "autonomy", "objective", "city", "loads"],
    summary_fields: ["energy_mode", "daily_kwh", "monthly_kwh", "bill", "peak_kw", "priority_kwh", "autonomy", "objective", "city", "loads"],
    supports_loads: true,
  },
  thermal: {
    engine_project: "thermal",
    aliases: [],
    payload_fields: ["people", "building", "daily_hot_water_l", "thermal_target_temp", "thermal_inlet_temp", "city"],
    summary_fields: ["people", "building", "daily_hot_water_l", "thermal_target_temp", "thermal_inlet_temp", "city"],
    supports_loads: false,
  },
  ev_charging: {
    engine_project: "ev",
    aliases: ["ev"],
    payload_fields: ["vehicle", "vehicle_battery", "daily_km", "consumption_kwh_100km", "phases", "available_power", "charger_power", "vehicle_ac_max", "distance", "city"],
    summary_fields: ["vehicle", "vehicle_battery", "daily_km", "consumption_kwh_100km", "phases", "available_power", "charger_power", "vehicle_ac_max", "distance", "city"],
    supports_loads: false,
  },
};

const PROJECTS = {
  pumping: {
    label: "Pompage solaire",
    icon: "💧",
    description: "Dimensionnez une solution pour forage, irrigation ou alimentation en eau.",
    steps: [
      {
        id: "existing_pump",
        type: "fields",
        title: "Avez-vous déjà une pompe ?",
        description: "Indiquez votre situation pour préparer votre installation solaire.",
        fields: [
          choiceField("pump_existing", "Pompe existante", [
            { value: "false", label: "Non, j’ai besoin d’une recommandation" },
            { value: "true", label: "Oui, une pompe existe déjà" },
          ], "false"),
        ],
      },
      {
        id: "existing_pump_cv",
        type: "pump-cv-picker",
        showIf: (state) => pumpExistingAnswer(state.answers.pump_existing),
        title: "Quelle est la puissance de votre pompe ?",
        description: "Choisissez la puissance indiquée sur votre pompe.",
      },
      {
        id: "site",
        type: "fields",
        showIf: (state) => !pumpExistingAnswer(state.answers.pump_existing),
        title: "Votre besoin de pompage",
        description: "Ces deux valeurs permettent de sélectionner une pompe HeliAntha adaptée.",
        fields: [
          numberField("flow_m3_h", "De quel débit avez-vous besoin ?", "m³/h", "", { required: true, min: 0.01 }),
          numberField("hmt_m", "Quelle est la HMT de votre installation ?", "m", "", {
            required: true,
            min: 0.01,
            help: "HMT : hauteur manométrique totale de l’installation.",
          }),
        ],
      },
      commonContactStep(),
      recapStep(),
    ],
  },
  off_grid: {
    label: "Site sans réseau",
    icon: "🏠",
    description: "Installation hors réseau avec batteries et autonomie.",
    steps: [
      energyModeStep("loads"),
      loadsStep(),
      {
        id: "direct_energy",
        type: "fields",
        showIf: (state) => state.answers.energy_mode !== "loads",
        title: "Votre consommation",
        description: "Si vous connaissez déjà vos besoins, vous pouvez les saisir directement.",
        fields: [
          numberField("daily_kwh", "Consommation quotidienne", "kWh / jour", "12"),
          numberField("peak_kw", "Puissance simultanée", "kW", "4"),
        ],
      },
      {
        id: "storage",
        type: "fields",
        title: "Autonomie et localisation",
        description: "L’autonomie et la ville influencent directement la batterie et la production solaire.",
        fields: [
          numberField("autonomy", "Autonomie souhaitée", "jours", "1"),
          textField("city", "Ville du projet", "ex. Agadir", "Agadir"),
          textareaField("notes", "Informations utiles", "Type de site, réseau absent, contrainte particulière…", ""),
        ],
      },
      commonContactStep(),
      recapStep(),
    ],
  },
  photovoltaic: {
    label: "Réduire ma consommation",
    icon: "☀️",
    description: "Réduire la consommation électrique du bâtiment.",
    steps: [
      {
        id: "building",
        type: "fields",
        title: "Votre bâtiment et votre consommation",
        description: "Une estimation mensuelle suffit pour lancer une première étude.",
        fields: [
          selectField("building", "Type de bâtiment", [
            ["Maison", "Maison"],
            ["Entreprise", "Entreprise"],
            ["Ferme", "Ferme"],
            ["Hôtel", "Hôtel"],
          ], "Entreprise"),
          numberField("monthly_kwh", "Consommation mensuelle", "kWh / mois", "900"),
          numberField("bill", "Montant moyen de la facture", "DH / mois", ""),
        ],
      },
      {
        id: "installation",
        type: "fields",
        title: "Votre installation",
        description: "Ces informations aident à adapter la solution à l’espace et au profil d’usage.",
        fields: [
          selectField("day_profile", "Profil de consommation", [
            ["jour", "Surtout le jour"],
            ["equilibre", "Équilibrée"],
            ["soir", "Surtout le soir"],
          ], "jour"),
          selectField("network", "Type de réseau", [
            ["", "Je ne connais pas"],
            ["monophase", "Monophasé"],
            ["triphase", "Triphasé"],
          ], ""),
          numberField("roof_area", "Surface disponible", "m²", "80"),
          textField("city", "Ville du projet", "ex. Casablanca", "Casablanca"),
        ],
      },
      commonContactStep(),
      recapStep(),
    ],
  },
  hybrid: {
    label: "Système hybride",
    icon: "🔋",
    description: "Photovoltaïque, batteries et réseau pour plus de continuité.",
    steps: [
      energyModeStep("loads"),
      loadsStep({ hybrid: true }),
      {
        id: "direct_energy",
        type: "fields",
        showIf: (state) => state.answers.energy_mode !== "loads",
        title: "Charges totales et charges prioritaires",
        description: "Si vous connaissez déjà vos besoins, indiquez la consommation globale et les charges à secourir.",
        fields: [
          numberField("daily_kwh", "Consommation quotidienne totale", "kWh / jour", "10"),
          numberField("peak_kw", "Puissance simultanée", "kW", "4"),
          numberField("priority_kwh", "Charges prioritaires", "kWh / jour", ""),
        ],
      },
      {
        id: "storage",
        type: "fields",
        title: "Autonomie et objectif",
        description: "Le système hybride peut viser le secours, le confort ou l’optimisation.",
        fields: [
          numberField("autonomy", "Autonomie sur batterie", "jours", "0.5"),
          textField("objective", "Objectif principal", "ex. Secours pendant les coupures", "Secours pendant les coupures"),
          textField("city", "Ville du projet", "ex. Rabat", "Rabat"),
        ],
      },
      commonContactStep(),
      recapStep(),
    ],
  },
  thermal: {
    label: "Chauffage solaire",
    icon: "♨️",
    description: "Eau chaude solaire pour maison, hôtel ou activité.",
    steps: [
      {
        id: "usage",
        type: "fields",
        title: "Votre besoin en eau chaude",
        description: "Le nombre d’utilisateurs suffit pour une première estimation.",
        fields: [
          numberField("people", "Nombre d’utilisateurs", "personnes", "4"),
          selectField("building", "Type de bâtiment", [
            ["Maison", "Maison"],
            ["Hôtel", "Hôtel"],
            ["Restaurant", "Restaurant"],
            ["Autre", "Autre"],
          ], "Maison"),
          numberField("daily_hot_water_l", "Besoin journalier si connu", "L / jour", ""),
        ],
      },
      {
        id: "thermal_settings",
        type: "fields",
        title: "Température et localisation",
        description: "Si vous ne connaissez pas une valeur, HeliAntha utilisera la valeur de secours prévue.",
        fields: [
          numberField("thermal_target_temp", "Température d’eau chaude souhaitée", "°C", ""),
          numberField("thermal_inlet_temp", "Température d’eau froide si connue", "°C", ""),
          textField("city", "Ville du projet", "ex. Fès", "Fès"),
        ],
      },
      commonContactStep(),
      recapStep(),
    ],
  },
  ev_charging: {
    label: "Recharge électrique",
    icon: "🚗",
    description: "Une borne adaptée au véhicule, au réseau et à l’usage réel.",
    steps: [
      {
        id: "vehicle",
        type: "fields",
        title: "Votre véhicule et votre usage",
        description: "Même si vous n’avez pas toutes les informations, nous pouvons avancer avec une estimation.",
        fields: [
          textField("vehicle", "Véhicule", "marque et modèle", ""),
          numberField("vehicle_battery", "Capacité batterie si connue", "kWh", "60"),
          numberField("daily_km", "Kilométrage quotidien", "km / jour", ""),
          numberField("consumption_kwh_100km", "Consommation si connue", "kWh / 100 km", ""),
        ],
      },
      {
        id: "ev_installation",
        type: "fields",
        title: "Votre installation électrique",
        description: "La puissance disponible et le type de réseau orientent la borne recommandée.",
        fields: [
          selectField("phases", "Réseau", [
            ["", "Je ne connais pas cette information"],
            ["monophase", "Monophasé"],
            ["triphase", "Triphasé"],
          ], ""),
          numberField("available_power", "Puissance disponible", "kW", "11"),
          numberField("charger_power", "Puissance de borne souhaitée", "kW", "11"),
          numberField("vehicle_ac_max", "Limite de charge AC si connue", "kW", ""),
          numberField("distance", "Distance tableau-borne", "m", "15"),
          textField("city", "Ville du projet", "ex. Tanger", "Tanger"),
        ],
      },
      commonContactStep(),
      recapStep(),
    ],
  },
};

const PUMP_CV_OPTIONS = [
  { value: "2", label: "2 CV" },
  { value: "3", label: "3 CV" },
  { value: "5.5", label: "5,5 CV" },
  { value: "7.5", label: "7,5 CV" },
  { value: "10", label: "10 CV" },
  { value: "15", label: "15 CV" },
  { value: "20", label: "20 CV" },
  { value: "30", label: "30 CV" },
  { value: "40", label: "40 CV" },
  { value: "50", label: "50 CV" },
];
const PUMP_CV_LABELS = Object.fromEntries(PUMP_CV_OPTIONS.map((option) => [option.value, option.label]));

const state = loadState();
const wizard = document.querySelector("#wizard");
const body = document.querySelector("#wizard-body");
const aside = document.querySelector("#wizard-aside");
const form = document.querySelector("#quote-form");
const nextButton = document.querySelector("#next-button");
const backButton = document.querySelector("#back-button");

bindLanding();
initPageChrome();
initScrollReveal();
renderWizardShell();

function numberField(name, label, unit, value, extra = {}) {
  return { type: "number", name, label, unit, value, step: "any", ...extra };
}

function textField(name, label, placeholder, value, extra = {}) {
  return { type: "text", name, label, placeholder, value, ...extra };
}

function textareaField(name, label, placeholder, value, extra = {}) {
  return { type: "textarea", name, label, placeholder, value, ...extra };
}

function selectField(name, label, options, value, extra = {}) {
  return { type: "select", name, label, options, value, ...extra };
}

function choiceField(name, label, options, value, extra = {}) {
  return { type: "choice", name, label, options, value, ...extra };
}

function pumpExistingAnswer(value) {
  if (value === true) return true;
  return ["true", "yes", "1"].includes(String(value ?? "").trim().toLowerCase());
}

function cleanOppositePumpingAnswers(answers) {
  if (!answers || typeof answers !== "object") return;
  if (pumpExistingAnswer(answers.pump_existing)) {
    delete answers.flow_m3_h;
    delete answers.hmt_m;
  } else {
    delete answers.existing_pump_cv;
  }
}

function energyModeStep(defaultValue = "loads") {
  return {
    id: "energy_mode",
    type: "choice-step",
    title: "Comment souhaitez-vous décrire votre consommation ?",
    description: "Vous pouvez partir d’une bibliothèque d’équipements ou saisir directement vos chiffres.",
    name: "energy_mode",
    defaultValue,
    options: [
      { value: "loads", label: "Bibliothèque d’appareils", description: "Ajoutez des équipements et laissez l’assistant estimer les besoins." },
      { value: "direct", label: "Je connais déjà mes chiffres", description: "Saisissez directement la consommation journalière et la puissance simultanée." },
    ],
  };
}

function loadsStep(options = {}) {
  return {
    id: "loads",
    type: "loads",
    showIf: (state) => state.answers.energy_mode === "loads",
    hybrid: options.hybrid === true,
    title: options.hybrid ? "Décrivez vos charges et vos priorités" : "Décrivez vos équipements",
    description: options.hybrid
      ? "Ajoutez les appareils importants. Vous pouvez marquer ceux qui doivent rester alimentés pendant une coupure."
      : "Ajoutez vos appareils pour préparer l'estimation de votre projet.",
  };
}

function commonContactStep() {
  return {
    id: "contact",
    type: "fields",
    title: "Vos coordonnées",
    description: "Un téléphone ou un e-mail suffit.",
    fields: [
      textField("name", "Nom complet", "Votre nom", ""),
      textField("phone", "Téléphone", "06 00 00 00 00", ""),
      textField("email", "E-mail", "vous@exemple.ma", ""),
      textField("location", "Localisation précise", "Ville, commune ou adresse", ""),
      textareaField("comment", "Commentaire", "Contrainte, délai, information utile…", ""),
    ],
    contact: true,
  };
}

function recapStep() {
  return {
    id: "recap",
    type: "recap",
    title: "Vérifiez vos informations",
    description: "Tout est prêt. Vérifiez simplement vos informations avant de continuer.",
  };
}

function bindLanding() {
  document.querySelectorAll(".js-start").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      const target = document.querySelector("#solutions");
      if (target) {
        target.scrollIntoView({ behavior: "smooth", block: "start" });
        target.setAttribute("tabindex", "-1");
        target.focus({ preventScroll: true });
      }
      const menu = document.querySelector("#mobile-menu");
      const toggle = document.querySelector("#mobile-menu-toggle");
      if (menu && toggle) {
        menu.hidden = true;
        menu.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
      }
    });
  });

  document.querySelectorAll("[data-project]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      openWizard(button.dataset.project);
    });
  });

  document.querySelectorAll("[data-close]").forEach((button) => {
    button.addEventListener("click", closeWizard);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeWizard();
    }
  });

  form.addEventListener("submit", onSubmitWizard);
  backButton.addEventListener("click", onBackStep);
}

function initPageChrome() {
  const toggle = document.querySelector("#mobile-menu-toggle");
  const menu = document.querySelector("#mobile-menu");
  if (toggle && menu) {
    toggle.addEventListener("click", () => {
      const opened = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-expanded", String(!opened));
      menu.hidden = opened;
      menu.classList.toggle("open", !opened);
    });
    menu.querySelectorAll("a, button").forEach((element) => {
      element.addEventListener("click", () => {
        toggle.setAttribute("aria-expanded", "false");
        menu.hidden = true;
        menu.classList.remove("open");
      });
    });
  }
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

function defaultState() {
  return {
    open: false,
    project: "",
    stepIndex: 0,
    mobileFieldIndex: 0,
    mobileLoadIndex: 0,
    mobileLoadCategory: "",
    pumpCvSheetOpen: false,
    answers: {},
    contact: {},
    loads: [],
    result: null,
    analysisStartedAt: null,
  };
}

function normalizeProjectKey(project) {
  const value = String(project || "").trim();
  if (!value) {
    return "";
  }
  if (PROJECTS[value]) {
    return value;
  }
  for (const [key, meta] of Object.entries(WIZARD_PROJECT_META)) {
    if ((meta.aliases || []).includes(value)) {
      return key;
    }
  }
  return "";
}

function getProjectMeta(project) {
  const key = normalizeProjectKey(project);
  return key ? WIZARD_PROJECT_META[key] || null : null;
}

function projectSupportsLoads(project) {
  return Boolean(getProjectMeta(project)?.supports_loads);
}

function projectUsesLoadLibrary(project, answers) {
  return projectSupportsLoads(project) && String((answers || {}).energy_mode || "") === "loads";
}

function getProjectFields(project, kind) {
  const meta = getProjectMeta(project);
  const fields = meta?.[kind];
  return Array.isArray(fields) ? fields : [];
}

function pruneProjectAnswers(project, answers) {
  const allowed = new Set(getProjectFields(project, "payload_fields"));
  if (!allowed.size) {
    return {};
  }
  return Object.fromEntries(
    Object.entries(answers || {}).filter(([key, value]) => allowed.has(key) && !(typeof value === "string" && value.trim() === ""))
  );
}

function parseLocaleNumber(value) {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : 0;
  }
  const normalized = String(value ?? "")
    .trim()
    .replace(/\u00a0/g, "")
    .replace(/\s/g, "");
  if (!normalized) {
    return 0;
  }
  let decimal = normalized;
  if (decimal.includes(",")) {
    if (decimal.includes(".") && decimal.lastIndexOf(",") > decimal.lastIndexOf(".")) {
      decimal = decimal.replace(/\./g, "");
    }
    decimal = decimal.replace(",", ".");
  }
  const parsed = Number(decimal);
  return Number.isFinite(parsed) ? parsed : 0;
}

function normalizeLocaleNumberAnswer(value) {
  const parsed = parseLocaleNumber(value);
  return Number.isFinite(parsed) ? parsed : value;
}

function pruneProjectLoads(project, loads, answers = {}) {
  return projectUsesLoadLibrary(project, answers) && Array.isArray(loads) ? loads : [];
}

function loadState() {
  try {
    const loaded = { ...defaultState(), ...JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "{}") };
    loaded.project = normalizeProjectKey(loaded.project) || "";
    loaded.answers = pruneProjectAnswers(loaded.project, loaded.answers);
    loaded.loads = pruneProjectLoads(loaded.project, loaded.loads, loaded.answers);
    loaded.contact = loaded.contact || {};
    loaded.result = loaded.result || null;
    return loaded;
  } catch {
    return defaultState();
  }
}

function persistState() {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
    project: state.project,
    stepIndex: state.stepIndex,
    mobileFieldIndex: state.mobileFieldIndex,
    mobileLoadIndex: state.mobileLoadIndex,
    mobileLoadCategory: state.mobileLoadCategory,
    pumpCvSheetOpen: state.pumpCvSheetOpen,
    answers: state.answers,
    contact: state.contact,
    loads: state.loads,
    result: state.result,
  }));
}

function setActiveProject(project, { reset = false } = {}) {
  const normalized = normalizeProjectKey(project);
  if (!normalized) {
    return false;
  }
  const current = normalizeProjectKey(state.project);
  const shouldReset = reset || current !== normalized;
  state.project = normalized;
  state.stepIndex = 0;
  state.mobileFieldIndex = 0;
  state.mobileLoadIndex = 0;
  state.mobileLoadCategory = "";
  state.pumpCvSheetOpen = false;
  if (shouldReset) {
    state.answers = {};
    state.contact = {};
    state.loads = [];
    state.result = null;
    state.analysisStartedAt = null;
  } else {
    state.answers = pruneProjectAnswers(normalized, state.answers);
    state.loads = pruneProjectLoads(normalized, state.loads, state.answers);
  }
  if (!projectSupportsLoads(normalized)) {
    state.loads = [];
  }
  return shouldReset;
}

function openWizard(project = "") {
  const normalized = normalizeProjectKey(project);
  if (project && !normalized) {
    toast("Projet non reconnu.");
    return;
  }
  if (normalized) {
    setActiveProject(normalized, { reset: Boolean(project) });
  } else if (!normalizeProjectKey(state.project)) {
    setActiveProject("pumping");
  } else {
    state.project = normalizeProjectKey(state.project);
    state.stepIndex = 0;
    state.mobileFieldIndex = 0;
    state.mobileLoadIndex = 0;
    state.mobileLoadCategory = "";
    state.pumpCvSheetOpen = false;
    state.answers = pruneProjectAnswers(state.project, state.answers);
    state.loads = pruneProjectLoads(state.project, state.loads, state.answers);
  }
  state.open = true;
  state.result = null;
  wizard.classList.add("open");
  wizard.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  renderWizardShell();
}

function applyWizardPrefill(prefill = {}) {
  if (prefill.project) {
    const normalized = normalizeProjectKey(prefill.project);
    if (normalized) {
      setActiveProject(normalized, { reset: true });
    }
  }
  const targetProject = normalizeProjectKey(state.project);
  state.answers = {
    ...pruneProjectAnswers(targetProject, state.answers),
    ...pruneProjectAnswers(targetProject, prefill.answers || {}),
  };
  state.contact = { ...state.contact, ...(prefill.contact || {}) };
  state.loads = pruneProjectLoads(targetProject, Array.isArray(prefill.loads) ? prefill.loads : state.loads, state.answers);
  if (prefill.result) {
    state.result = prefill.result;
  }
  persistState();
  renderWizardShell();
}

function closeWizard() {
  state.open = false;
  state.pumpCvSheetOpen = false;
  wizard.classList.remove("open");
  wizard.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
  persistState();
}

function getProjectConfig() {
  return PROJECTS[normalizeProjectKey(state.project)] || null;
}

function getSteps() {
  const project = normalizeProjectKey(state.project);
  if (!project) {
    return [];
  }
  return (PROJECTS[project]?.steps || []).filter((step) => !step.showIf || step.showIf(state));
}

function getCurrentStep() {
  const steps = getSteps();
  if (!steps.length) {
    return null;
  }
  const index = Math.min(Math.max(Number(state.stepIndex || 0), 0), steps.length - 1);
  if (index !== state.stepIndex) {
    state.stepIndex = index;
  }
  return steps[index] || null;
}

function isCompactWizard() {
  return window.matchMedia("(max-width: 760px)").matches;
}

function getVisibleFields(step) {
  return (step.fields || []).filter((field) => !field.condition || field.condition(state.answers));
}

function getFieldPages(step) {
  const fields = getVisibleFields(step);
  if (!isCompactWizard() || fields.length <= 1) {
    return [fields];
  }
  return fields.map((field) => [field]);
}

function getLoadCategories() {
  return Object.keys(DEVICE_LIBRARY);
}

function getMobileLoadCategory() {
  const categories = getLoadCategories();
  if (!categories.length) {
    return "";
  }
  if (categories.includes(state.mobileLoadCategory)) {
    return state.mobileLoadCategory;
  }
  return categories[0];
}

function getLoadPages() {
  return isCompactWizard() ? ["categories", "devices", "selected", "custom"] : ["desktop"];
}

function renderWizardShell() {
  if (!wizard) {
    return;
  }

  body.innerHTML = "";
  aside.innerHTML = "";
  renderAside();
  renderStep();
}

function renderAside() {
  const project = getProjectConfig();
  const totals = computeLoads();
  const currentProject = normalizeProjectKey(state.project);
  const items = [
    project ? `<div class="aside-project"><span class="aside-project-icon">${project.icon}</span><div><strong>${project.label}</strong><div class="field-hint">${project.description}</div></div></div>` : `<div class="aside-project"><span class="aside-project-icon">??</span><div><strong>HeliAntha Smart Quote</strong><div class="field-hint">Choisissez votre projet et avançons étape par étape.</div></div></div>`,
  ];

  const summary = buildProjectSummary(currentProject, totals);

  aside.innerHTML = `
    <div class="aside-guide">
      <h3>Votre ?tude</h3>
      ${items.join("")}
    </div>
    <ul class="aside-list">
      ${summary.length ? summary.map(([label, value]) => `<li><span>${label}</span><strong>${value}</strong></li>`).join("") : ""}
    </ul>
  `;
}

function buildProjectSummary(project, totals) {
  const summary = [];
  const projectMeta = getProjectMeta(project);
  if (!projectMeta) {
    return summary;
  }

  for (const fieldName of getProjectFields(project, "summary_fields")) {
    if (fieldName === "loads") {
      if (projectUsesLoadLibrary(project, state.answers) && state.loads.length) {
        summary.push(["Appareils", `${state.loads.length} appareil(s)`]);
      }
      continue;
    }

    const value = getSummaryValue(fieldName, project, totals);
    if (value === null || value === undefined || value === "") {
      continue;
    }
    const fieldLabel = getFieldLabel(project, fieldName);
    summary.push([fieldLabel, value]);
  }

  if (state.contact.name) summary.push(["Contact", state.contact.name]);
  if (state.contact.phone) summary.push(["Téléphone", state.contact.phone]);
  if (state.contact.email) summary.push(["E-mail", state.contact.email]);
  if (state.contact.location) summary.push(["Localisation", state.contact.location]);
  return summary;
}

function getFieldLabel(project, fieldName) {
  const definition = getFieldDefinition(project, fieldName);
  if (definition?.label) {
    return definition.label;
  }
  const fallback = {
    pump_existing: "Pompe existante",
    existing_pump_cv: "Puissance de la pompe",
    flow_m3_h: "Débit demandé",
    hmt_m: "HMT demandée",
    distance: "Distance horizontale",
    city: "Ville du projet",
    energy_mode: "Mode de saisie",
    daily_kwh: "Consommation quotidienne",
    monthly_kwh: "Consommation mensuelle",
    peak_kw: "Puissance simultanée",
    autonomy: "Autonomie",
    objective: "Objectif principal",
    priority_kwh: "Charges prioritaires",
    building: "Type de bâtiment",
    bill: "Facture moyenne",
    day_profile: "Profil de consommation",
    network: "Type de réseau",
    roof_area: "Surface disponible",
    people: "Nombre d’utilisateurs",
    daily_hot_water_l: "Besoin journalier",
    thermal_target_temp: "Température souhaitée",
    thermal_inlet_temp: "Température d’entrée",
    vehicle: "Véhicule",
    vehicle_battery: "Capacité batterie",
    daily_km: "Kilométrage quotidien",
    consumption_kwh_100km: "Consommation",
    phases: "Réseau",
    available_power: "Puissance disponible",
    charger_power: "Puissance de borne",
    vehicle_ac_max: "Limite AC",
  };
  return fallback[fieldName] || fieldName;
}

function getFieldDefinition(project, fieldName) {
  const config = PROJECTS[normalizeProjectKey(project)];
  if (!config) {
    return null;
  }
  for (const step of config.steps || []) {
    if (step.name === fieldName) {
      return step;
    }
    for (const field of step.fields || []) {
      if (field.name === fieldName) {
        return field;
      }
    }
  }
  return null;
}

function getSummaryValue(fieldName, project, totals) {
  if (fieldName === "energy_mode") {
    return {
      loads: "Bibliothèque d’appareils",
      direct: "Saisie directe",
    }[state.answers.energy_mode] || state.answers.energy_mode || "";
  }
  if (fieldName === "pump_existing") {
    return state.answers.pump_existing === true || state.answers.pump_existing === "true" || state.answers.pump_existing === "yes"
      ? "Oui, j’ai déjà une pompe"
      : state.answers.pump_existing === false || state.answers.pump_existing === "false" || state.answers.pump_existing === "no"
        ? "Non, j’ai besoin d’une recommandation"
        : "";
  }
  if (fieldName === "loads") {
    return projectSupportsLoads(project) ? `${state.loads.length} appareil(s)` : "";
  }
  if (fieldName === "priority_kwh") {
    return totals.priority_kwh > 0 ? `${formatNumber(totals.priority_kwh)} kWh / jour` : "";
  }

  const definition = getFieldDefinition(project, fieldName);
  const value = state.answers[fieldName];
  if (value === null || value === undefined || value === "") {
    return "";
  }
  if (definition?.type === "select" || definition?.type === "choice" || definition?.type === "choice-step") {
    const options = definition.options || [];
    const option = options.find((item) => String(item.value) === String(value));
    return option ? option.label : String(value);
  }
  if (definition?.type === "number") {
    const formatted = formatNumber(value);
    return definition.unit ? `${formatted} ${definition.unit}` : formatted;
  }
  return String(value);
}

function renderStep() {
  const current = getCurrentStep();
  if (!current) {
    document.querySelector("#step-label").textContent = "Projet non reconnu";
    document.querySelector("#progress-label").textContent = "0 %";
    document.querySelector("#progress-bar").style.width = "0%";
    renderProgressSteps(1, 0);
    backButton.style.visibility = "hidden";
    nextButton.textContent = "Continuer";
    nextButton.disabled = true;
    body.innerHTML = `
      <section class="wizard-step">
        <span class="eyebrow">Configuration indisponible</span>
        <h2>Projet non reconnu</h2>
        <p>Merci de sélectionner un projet valide pour continuer.</p>
      </section>
    `;
    return;
  }
  nextButton.disabled = false;
  backButton.disabled = false;
  const steps = getSteps();
  const total = steps.length || 1;
  const stepNumber = current.id === "project" ? 1 : state.stepIndex + 1;
  const progress = current.id === "project" ? 8 : Math.round((stepNumber / total) * 100);
  const fieldPages = current.type === "fields" ? getFieldPages(current) : [];
  const loadPages = current.type === "loads" ? getLoadPages() : [];
  const isMobilePager = current.type === "fields" && isCompactWizard() && fieldPages.length > 1;
  const isMobileLoadPager = current.type === "loads" && isCompactWizard() && loadPages.length > 1;
  const maxFieldPage = Math.max(fieldPages.length - 1, 0);
  const maxLoadPage = Math.max(loadPages.length - 1, 0);

  if (isMobilePager) {
    state.mobileFieldIndex = Math.min(Number(state.mobileFieldIndex || 0), maxFieldPage);
  } else {
    state.mobileFieldIndex = 0;
  }

  if (isMobileLoadPager) {
    state.mobileLoadIndex = Math.min(Number(state.mobileLoadIndex || 0), maxLoadPage);
  } else if (current.type !== "loads") {
    state.mobileLoadIndex = 0;
  }

  document.querySelector("#step-label").textContent = current.id === "project"
    ? "Choix du projet"
    : isMobileLoadPager
      ? `Étape ${stepNumber} sur ${total} · page ${state.mobileLoadIndex + 1}/${loadPages.length}`
    : isMobilePager
      ? `Étape ${stepNumber} sur ${total} · page ${state.mobileFieldIndex + 1}/${fieldPages.length}`
      : `Étape ${stepNumber} sur ${total}`;
  document.querySelector("#progress-label").textContent = `${progress} %`;
  document.querySelector("#progress-bar").style.width = `${progress}%`;
  renderProgressSteps(total, current.id === "project" ? 0 : stepNumber - 1);

  backButton.style.visibility = current.id === "project" ? "hidden" : "visible";
  nextButton.textContent = current.id === "recap"
    ? "Voir mon estimation"
    : ((isMobilePager && state.mobileFieldIndex < maxFieldPage) || (isMobileLoadPager && state.mobileLoadIndex < maxLoadPage))
      ? "Suivant"
      : "Continuer";

  if (current.type === "project") {
    state.stepIndex = 0;
    renderWizardShell();
    return;
  }
  if (current.type === "choice-step") {
    renderChoiceStep(current);
    return;
  }
  if (current.type === "pump-cv-picker") {
    renderPumpCvStep(current);
    return;
  }
  if (current.type === "loads") {
    renderLoadsStep(current);
    return;
  }
  if (current.type === "recap") {
    renderRecapStep();
    return;
  }
  renderFieldsStep(current);
}

function renderProgressSteps(total, activeIndex) {
  const container = document.querySelector("#progress-steps");
  if (!container) {
    return;
  }
  container.innerHTML = Array.from({ length: Math.max(total, 1) }, (_, index) => `
    <span class="progress-step ${index < activeIndex ? "done" : ""} ${index === activeIndex ? "active" : ""}"></span>
  `).join("");
}

function renderProjectStep() {
  body.innerHTML = `
    <section class="wizard-step">
      <span class="eyebrow">Commençons</span>
      <h2>Quel est votre projet ?</h2>
      <p>Choisissez le besoin principal. Le questionnaire s’adaptera automatiquement.</p>
      <div class="project-grid">
        ${Object.entries(PROJECTS).map(([key, project]) => `
          <button class="project-card ${normalizeProjectKey(state.project) === key ? "active" : ""}" type="button" data-pick-project="${key}">
            <span class="project-icon">${project.icon}</span>
            <strong>${project.label}</strong>
            <p>${project.description}</p>
            ${normalizeProjectKey(state.project) === key ? `<span class="project-choice-state" aria-hidden="true">?</span>` : ""}
            <span class="project-action">${key === "ev_charging" ? "Choisir ma borne" : "Estimer mon installation"}</span>
          </button>
        `).join("")}
      </div>
    </section>
  `;

  body.querySelectorAll("[data-pick-project]").forEach((button) => {
    button.addEventListener("click", () => {
      openWizard(button.dataset.pickProject);
      persistState();
    });
  });
}

function renderChoiceStep(step) {
  const currentValue = state.answers[step.name] || step.defaultValue || "";
  body.innerHTML = `
    <section class="wizard-step">
      <span class="eyebrow">${getProjectConfig().icon} ${getProjectConfig().label}</span>
      <h2>${step.title}</h2>
      <p>${step.description}</p>
      <div class="choice-grid">
        ${step.options.map((option) => `
          <button type="button" class="choice-card ${currentValue === option.value ? "active" : ""}" data-choice-name="${step.name}" data-choice-value="${option.value}">
            ${currentValue === option.value ? `<span class="choice-state" aria-hidden="true">?</span>` : ""}
            <strong>${option.label}</strong>
            <p>${option.description}</p>
          </button>
        `).join("")}
      </div>
    </section>
  `;

  body.querySelectorAll("[data-choice-name]").forEach((button) => {
    button.addEventListener("click", () => {
      state.answers[step.name] = button.dataset.choiceValue;
      if (button.dataset.choiceName === "energy_mode") {
        if (button.dataset.choiceValue === "loads" && !state.loads.length) {
          state.loads.push(defaultCustomLoad("Lampe LED", 4, 12, 5, true, step.hybrid));
        }
        if (button.dataset.choiceValue === "direct") {
          state.loads = [];
          state.mobileLoadIndex = 0;
          state.mobileLoadCategory = "";
        }
      }
      renderWizardShell();
      persistState();
    });
  });
}

function renderFieldsStep(step) {
  const store = step.contact ? state.contact : state.answers;
  const pages = getFieldPages(step);
  const pageIndex = Math.min(Number(state.mobileFieldIndex || 0), pages.length - 1);
  const fields = pages[pageIndex] || getVisibleFields(step);
  body.innerHTML = `
    <section class="wizard-step">
      <span class="eyebrow">${getProjectConfig().icon} ${getProjectConfig().label}</span>
      <h2>${step.title}</h2>
      <p>${step.description}</p>
      ${pages.length > 1 ? `<div class="wizard-page-badge">Page ${pageIndex + 1} sur ${pages.length}</div>` : ""}
      <div class="form-grid wizard-page-grid">
        ${fields.map((field) => renderField(field, store)).join("")}
      </div>
    </section>
  `;

  body.querySelectorAll("[data-inline-choice]").forEach((button) => {
    button.addEventListener("click", () => {
      const group = button.dataset.inlineChoice;
      const value = button.dataset.inlineValue;
      const target = step.contact ? state.contact : state.answers;
      target[group] = value;
      if (state.project === "pumping" && group === "pump_existing") {
        cleanOppositePumpingAnswers(target);
      }
      renderWizardShell();
      persistState();
    });
  });
}

function renderPumpCvStep(step) {
  const currentValue = String(state.answers.existing_pump_cv || "");
  const currentLabel = PUMP_CV_LABELS[currentValue] || "Choisir la puissance";
  const sheetOpen = Boolean(state.pumpCvSheetOpen);

  body.innerHTML = `
    <section class="wizard-step pump-cv-step">
      <span class="eyebrow">${getProjectConfig().icon} ${getProjectConfig().label}</span>
      <h2>${step.title}</h2>
      <p>${step.description}</p>

      <div class="field full pump-cv-field">
        <label for="pump-cv-trigger">Puissance de la pompe</label>
        <button
          id="pump-cv-trigger"
          class="pump-cv-trigger"
          type="button"
          data-pump-cv-trigger
          aria-haspopup="dialog"
          aria-expanded="${sheetOpen ? "true" : "false"}"
        >
          <span class="pump-cv-trigger-value">${escapeHtml(currentLabel)}</span>
          <span class="pump-cv-trigger-chevron" aria-hidden="true">▾</span>
        </button>
        <input type="hidden" name="existing_pump_cv" value="${escapeHtml(currentValue)}" data-pump-cv-value>
      </div>
    </section>
    ${renderPumpCvSheet(sheetOpen, currentValue)}
  `;

  const trigger = body.querySelector("[data-pump-cv-trigger]");
  const hiddenInput = body.querySelector("[data-pump-cv-value]");
  const sheet = body.querySelector("[data-pump-cv-sheet]");
  const closeButtons = body.querySelectorAll("[data-pump-cv-close]");
  const options = body.querySelectorAll("[data-pump-cv-option]");

  const openSheet = () => {
    state.pumpCvSheetOpen = true;
    persistState();
    renderWizardShell();
  };

  const closeSheet = () => {
    state.pumpCvSheetOpen = false;
    persistState();
    renderWizardShell();
  };

  const selectValue = (value) => {
    state.answers.existing_pump_cv = value;
    state.pumpCvSheetOpen = false;
    persistState();
    renderWizardShell();
  };

  trigger?.addEventListener("click", openSheet);
  trigger?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openSheet();
    }
  });
  hiddenInput?.addEventListener("change", () => {
    state.answers.existing_pump_cv = hiddenInput.value;
    persistState();
  });
  closeButtons.forEach((button) => button.addEventListener("click", closeSheet));
  sheet?.addEventListener("click", (event) => {
    if (event.target === sheet) {
      closeSheet();
    }
  });
  options.forEach((button) => {
    button.addEventListener("click", () => selectValue(button.dataset.pumpCvOption || ""));
  });
}

function renderPumpCvSheet(open, currentValue) {
  const current = String(currentValue || "");
  return `
    <div class="pump-cv-sheet-shell ${open ? "is-open" : ""}" data-pump-cv-sheet ${open ? "" : "hidden"}>
      <div class="pump-cv-sheet-backdrop" data-pump-cv-close></div>
      <section class="pump-cv-sheet" role="dialog" aria-modal="true" aria-labelledby="pump-cv-sheet-title">
        <header class="pump-cv-sheet-header">
          <div>
            <span class="eyebrow">Pompage solaire</span>
            <h3 id="pump-cv-sheet-title">Choisir la puissance de la pompe</h3>
          </div>
          <button type="button" class="pump-cv-sheet-close" data-pump-cv-close aria-label="Fermer">×</button>
        </header>
        <div class="pump-cv-sheet-options" role="radiogroup" aria-label="Puissance de la pompe">
          ${PUMP_CV_OPTIONS.map((option) => `
            <button
              type="button"
              class="pump-cv-sheet-option ${current === option.value ? "active" : ""}"
              data-pump-cv-option="${option.value}"
              role="radio"
              aria-checked="${current === option.value ? "true" : "false"}"
            >
              <span class="pump-cv-option-mark" aria-hidden="true">${current === option.value ? "●" : "○"}</span>
              <span>${option.label}</span>
            </button>
          `).join("")}
        </div>
        <button type="button" class="admin-button secondary pump-cv-sheet-close-button" data-pump-cv-close>Fermer</button>
      </section>
    </div>
  `;
}

function renderField(field, store) {
  const value = store[field.name] ?? field.value ?? "";
  const required = field.required ? "required" : "";
  const full = field.type === "textarea" || field.full ? "full" : "";

  if (field.type === "select") {
    return `
      <div class="field ${full}">
        <label for="${field.name}">${field.label}</label>
        <select id="${field.name}" name="${field.name}" ${required}>
          ${field.options.map(([optionValue, optionLabel]) => `<option value="${optionValue}" ${String(value) === String(optionValue) ? "selected" : ""}>${optionLabel}</option>`).join("")}
        </select>
      </div>
    `;
  }

  if (field.type === "choice") {
    return `
      <div class="field ${full}">
        <label>${field.label}</label>
        <div class="choice-grid">
          ${field.options.map((option) => `
            <button type="button" class="choice-card ${String(value || field.value || "") === String(option.value) ? "active" : ""}" data-inline-choice="${field.name}" data-inline-value="${option.value}">
              ${String(value) === String(option.value) ? `<span class="choice-state" aria-hidden="true">?</span>` : ""}
              <strong>${option.label}</strong>
            </button>
          `).join("")}
        </div>
      </div>
    `;
  }

  if (field.type === "textarea") {
    return `
      <div class="field ${full}">
        <label for="${field.name}">${field.label}</label>
        <textarea id="${field.name}" name="${field.name}" placeholder="${field.placeholder || ""}" ${required}>${escapeHtml(value)}</textarea>
      </div>
    `;
  }

  return `
    <div class="field ${full}">
      <label for="${field.name}">${field.label}</label>
      <input id="${field.name}" name="${field.name}" type="${field.type || "text"}" placeholder="${field.unit || field.placeholder || ""}" value="${escapeHtml(value)}" ${field.step ? `step="${field.step}"` : ""} ${field.min !== undefined ? `min="${field.min}"` : ""} ${field.max !== undefined ? `max="${field.max}"` : ""} ${required}>
      ${(field.unit || field.help) ? `<p class="field-hint">${field.help || field.unit}</p>` : ""}
    </div>
  `;
}

function renderLoadsStep(step) {
  const totals = computeLoads();
  if (isCompactWizard()) {
    const pages = getLoadPages();
    const pageIndex = Math.min(Number(state.mobileLoadIndex || 0), pages.length - 1);
    const category = getMobileLoadCategory();
    const devices = DEVICE_LIBRARY[category] || [];
    const categories = getLoadCategories();
    state.mobileLoadIndex = pageIndex;
    state.mobileLoadCategory = category;

    const pageHints = [
      "Choisissez un groupe.",
      "Ajoutez un appareil.",
      "Tout reste modifiable.",
      "Saisissez un équipement simple.",
    ];

    body.innerHTML = `
      <section class="wizard-step loads-mobile-shell">
        <span class="eyebrow">${getProjectConfig().icon} ${getProjectConfig().label}</span>
        <h2>${step.title}</h2>
        <p>${pageHints[pageIndex] || "Tout reste modifiable."}</p>
        ${pages.length > 1 ? `<div class="wizard-page-badge">Page ${pageIndex + 1} sur ${pages.length}</div>` : ""}

        <div class="summary-cards summary-cards-sticky">
          <article class="summary-card">
            <small>Consommation quotidienne</small>
            <strong>${formatNumber(totals.daily_kwh)} kWh / jour</strong>
          </article>
          <article class="summary-card">
            <small>Puissance simultanée</small>
            <strong>${formatNumber(totals.peak_kw)} kW</strong>
          </article>
          <article class="summary-card">
            <small>${step.hybrid ? "Charges prioritaires" : "Appareils ajoutés"}</small>
            <strong>${step.hybrid ? `${formatNumber(totals.priority_kwh)} kWh / jour` : `${state.loads.length} appareil(s)`}</strong>
          </article>
        </div>

        ${pageIndex === 0 ? `
          <div class="load-mobile-panels">
            <div class="load-category-grid load-category-grid-mobile">
              ${categories.map((name) => {
                const list = DEVICE_LIBRARY[name] || [];
                const active = name === category;
                return `
                  <button type="button" class="load-mobile-category ${active ? "active" : ""}" data-mobile-load-category="${name}">
                    <span class="library-icon">${iconForDevice(list[0]?.name || name, name)}</span>
                    <strong>${name}</strong>
                    <small>${list.length} appareil(s)</small>
                  </button>
                `;
              }).join("")}
            </div>
          </div>
        ` : ""}

        ${pageIndex === 1 ? `
          <div class="load-mobile-panels">
            <div class="load-mobile-head">
              <h3>${category}</h3>
              <p class="field-hint">Vous pouvez corriger la puissance avant ajout.</p>
            </div>
            <div class="load-device-list">
              ${devices.map((device, index) => `
                <div class="library-item library-card load-device-card">
                  <div class="load-device-main">
                    <span class="library-icon">${iconForDevice(device.name, category)}</span>
                    <div>
                      <strong>${device.name}</strong>
                      <div class="field-hint">${device.power_w} W • ${device.hours} h/j</div>
                    </div>
                  </div>
                  <div class="load-device-edit">
                    <div class="field">
                      <label for="mobile_${category}_${index}_power">Puissance</label>
                      <input id="mobile_${category}_${index}_power" type="number" step="any" value="${device.power_w}" data-mobile-load-power="${category}" data-mobile-load-index="${index}">
                    </div>
                    <div class="field">
                      <label for="mobile_${category}_${index}_hours">Heures / jour</label>
                      <input id="mobile_${category}_${index}_hours" type="number" step="any" value="${device.hours}" data-mobile-load-hours="${category}" data-mobile-load-index="${index}">
                    </div>
                    <button type="button" data-add-library="${category}" data-add-index="${index}">Ajouter</button>
                  </div>
                </div>
              `).join("")}
            </div>
          </div>
        ` : ""}

        ${pageIndex === 2 ? `
          <div class="load-mobile-panels">
            <div class="load-mobile-head">
              <h3>Vos appareils</h3>
              <p class="field-hint">Chaque valeur reste modifiable.</p>
            </div>
            <div class="selected-loads" id="selected-loads">
              ${state.loads.length ? state.loads.map((load, index) => renderLoadItem(load, index, step.hybrid)).join("") : `<div class="empty-state">Ajoutez au moins un appareil.</div>`}
            </div>
          </div>
        ` : ""}

        ${pageIndex === 3 ? `
          <div class="load-mobile-panels">
            <div class="load-mobile-head">
              <h3>Appareil personnalisé</h3>
              <p class="field-hint">Nom, puissance et durée suffisent.</p>
            </div>
            <div class="helper-card">
              <div class="form-grid load-custom-grid">
                <div class="field"><label for="custom_name">Nom</label><input id="custom_name" type="text" placeholder="Ex. Machine spéciale"></div>
                <div class="field"><label for="custom_qty">Quantité</label><input id="custom_qty" type="number" step="1" value="1"></div>
                <div class="field"><label for="custom_power">Puissance</label><input id="custom_power" type="number" step="any" placeholder="W"></div>
                <div class="field"><label for="custom_hours">Utilisation</label><input id="custom_hours" type="number" step="any" placeholder="h / jour"></div>
              </div>
              <div class="hero-actions">
                <button class="button button-primary" type="button" id="add-custom-load">Ajouter cet appareil</button>
              </div>
            </div>
          </div>
        ` : ""}
      </section>
    `;

    bindLoadsStep(step.hybrid);
    return;
  }
  body.innerHTML = `
    <section class="wizard-step">
      <span class="eyebrow">${getProjectConfig().icon} ${getProjectConfig().label}</span>
      <h2>${step.title}</h2>
      <p>${step.description}</p>

      <div class="summary-cards summary-cards-sticky">
        <article class="summary-card">
          <small>Consommation quotidienne estimée</small>
          <strong>${formatNumber(totals.daily_kwh)} kWh / jour</strong>
        </article>
        <article class="summary-card">
          <small>Puissance simultanée estimée</small>
          <strong>${formatNumber(totals.peak_kw)} kW</strong>
        </article>
        <article class="summary-card">
          <small>${step.hybrid ? "Charges prioritaires" : "Équipements ajoutés"}</small>
          <strong>${step.hybrid ? `${formatNumber(totals.priority_kwh)} kWh / jour` : `${state.loads.length} appareil(s)`}</strong>
        </article>
      </div>

      <div class="load-library">
        <article class="load-summary">
          <h3>Bibliothèque d’appareils</h3>
          <p class="field-hint">Ajoutez vos appareils pour préparer l’estimation de votre projet.</p>
          <div class="load-category-grid">
            ${Object.entries(DEVICE_LIBRARY).map(([category, devices]) => `
              <section class="load-card load-category">
                <h3>${category}</h3>
                ${devices.map((device, index) => `
                  <div class="library-item library-card">
                    <div>
                      <span class="library-icon">${iconForDevice(device.name, category)}</span>
                      <strong>${device.name}</strong>
                      <div class="field-hint">${device.power_w} W • ${device.hours} h/j</div>
                    </div>
                    <button type="button" data-add-library="${category}" data-add-index="${index}">Ajouter</button>
                  </div>
                `).join("")}
              </section>
            `).join("")}
          </div>
        </article>

        <article class="load-summary">
          <h3>Mes appareils</h3>
          <div class="selected-loads" id="selected-loads">
            ${state.loads.length ? state.loads.map((load, index) => renderLoadItem(load, index, step.hybrid)).join("") : `<div class="empty-state">Ajoutez quelques équipements pour lancer l’estimation.</div>`}
          </div>

          <div class="helper-card">
            <h3>Ajouter un appareil personnalisé</h3>
            <div class="form-grid">
              <div class="field"><label for="custom_name">Nom</label><input id="custom_name" type="text" placeholder="Ex. Machine spéciale"></div>
              <div class="field"><label for="custom_qty">Quantité</label><input id="custom_qty" type="number" step="1" value="1"></div>
              <div class="field"><label for="custom_power">Puissance</label><input id="custom_power" type="number" step="any" placeholder="W"></div>
              <div class="field"><label for="custom_hours">Utilisation</label><input id="custom_hours" type="number" step="any" placeholder="h / jour"></div>
            </div>
            <div class="hero-actions">
              <button class="button button-primary" type="button" id="add-custom-load">Ajouter cet appareil</button>
            </div>
          </div>
        </article>
      </div>
    </section>
  `;

  bindLoadsStep(step.hybrid);
}

function renderLoadItem(load, index, hybrid) {
  return `
    <div class="selected-load">
      <div>
        <label for="load_name_${index}">Appareil</label>
        <input id="load_name_${index}" type="text" value="${escapeHtml(load.name)}" data-load-field="name" data-load-index="${index}">
      </div>
      <div>
        <label for="load_qty_${index}">Quantité</label>
        <input id="load_qty_${index}" type="number" step="1" value="${load.quantity}" data-load-field="quantity" data-load-index="${index}">
      </div>
      <div>
        <label for="load_power_${index}">Puissance (W)</label>
        <input id="load_power_${index}" type="number" step="any" value="${load.power_w}" data-load-field="power_w" data-load-index="${index}">
      </div>
      <div>
        <label for="load_hours_${index}">Heures / jour</label>
        <input id="load_hours_${index}" type="number" step="any" value="${load.hours}" data-load-field="hours" data-load-index="${index}">
      </div>
      <label class="toggle-group"><input type="checkbox" ${load.simultaneous ? "checked" : ""} data-load-field="simultaneous" data-load-index="${index}"> Simultané</label>
      ${hybrid ? `<label class="toggle-group"><input type="checkbox" ${load.priority ? "checked" : ""} data-load-field="priority" data-load-index="${index}"> Prioritaire</label>` : `<div class="toggle-group"></div>`}
      <button type="button" class="load-remove" data-remove-load="${index}">Retirer</button>
    </div>
  `;
}

function bindLoadsStep(hybrid) {
  body.querySelectorAll("[data-mobile-load-category]").forEach((button) => {
    button.addEventListener("click", () => {
      state.mobileLoadCategory = button.dataset.mobileLoadCategory;
      state.mobileLoadIndex = 1;
      renderWizardShell();
      persistState();
    });
  });

  body.querySelectorAll("[data-add-library]").forEach((button) => {
    button.addEventListener("click", () => {
      const category = button.dataset.addLibrary;
      const index = Number(button.dataset.addIndex);
      const device = DEVICE_LIBRARY[category][index];
      const card = button.closest(".library-card");
      const powerInput = card?.querySelector("[data-mobile-load-power]");
      const hoursInput = card?.querySelector("[data-mobile-load-hours]");
      const power = Number(powerInput?.value || device.power_w || 0);
      const hours = Number(hoursInput?.value || device.hours || 0);
      state.loads.push(defaultCustomLoad(device.name, 1, power, hours, device.simultaneous, hybrid ? device.priority : false));
      renderWizardShell();
      persistState();
    });
  });

  body.querySelectorAll("[data-remove-load]").forEach((button) => {
    button.addEventListener("click", () => {
      state.loads.splice(Number(button.dataset.removeLoad), 1);
      renderWizardShell();
      persistState();
    });
  });

  body.querySelectorAll("[data-load-field]").forEach((input) => {
    input.addEventListener("input", () => {
      updateLoadFromInput(input);
      updateLoadSummary();
      persistState();
    });
    input.addEventListener("change", () => {
      updateLoadFromInput(input);
      updateLoadSummary();
      persistState();
    });
  });

  const addCustomButton = body.querySelector("#add-custom-load");
  if (addCustomButton) {
    addCustomButton.addEventListener("click", () => {
      const name = body.querySelector("#custom_name").value.trim();
      const quantity = Number(body.querySelector("#custom_qty").value || 1);
      const power = Number(body.querySelector("#custom_power").value || 0);
      const hours = Number(body.querySelector("#custom_hours").value || 0);
      if (!name || power <= 0 || hours <= 0) {
        toast("Ajoutez au moins un nom, une puissance et des heures d’utilisation.");
        return;
      }
      state.loads.push(defaultCustomLoad(name, quantity, power, hours, true, false));
      renderWizardShell();
      persistState();
    });
  }
}

function updateLoadFromInput(input) {
  const index = Number(input.dataset.loadIndex);
  const field = input.dataset.loadField;
  const item = state.loads[index];
  if (!item) {
    return;
  }
  if (field === "simultaneous" || field === "priority") {
    item[field] = input.checked;
    return;
  }
  if (field === "name") {
    item[field] = input.value;
    return;
  }
  item[field] = Number(input.value || 0);
}

function updateLoadSummary() {
  const totals = computeLoads();
  const cards = body.querySelectorAll(".summary-card strong");
  if (!cards.length) {
    return;
  }
  cards[0].textContent = `${formatNumber(totals.daily_kwh)} kWh / jour`;
  cards[1].textContent = `${formatNumber(totals.peak_kw)} kW`;
  cards[2].textContent = getCurrentStep().hybrid ? `${formatNumber(totals.priority_kwh)} kWh / jour` : `${state.loads.length} appareil(s)`;
}

function renderRecapStep() {
  syncCurrentInputs();
  const payload = buildApiPayload();
  const items = buildRecapItems(payload);
  body.innerHTML = `
    <section class="wizard-step">
      <span class="eyebrow">${getProjectConfig().icon} ${getProjectConfig().label}</span>
      <h2>Vérifiez vos informations</h2>
      <p>Tout est prêt. Vérifiez simplement vos informations avant de continuer.</p>
      <article class="recap-card">
        <div class="recap-header">
          <strong>${getProjectConfig().icon} ${getProjectConfig().label}</strong>
          ${state.contact.location || state.answers.city ? `<span>${state.contact.location || state.answers.city}</span>` : ""}
        </div>
        <dl class="summary-list">
          ${items.map(([label, value]) => `<div><dt>${label}</dt><dd>${value}</dd></div>`).join("")}
        </dl>
      </article>
    </section>
  `;
}

function buildRecapItems(payload) {
  const data = payload.data || {};
  const pumpingProject = state.project === "pumping";
  const existingPumpMode = pumpingProject && data.pump_existing === true;
  const recommendedPumpMode = pumpingProject && data.pump_existing === false;
  const items = existingPumpMode
    ? [
        ["Projet", getProjectConfig().label],
        ["Situation", "Pompe déjà installée"],
        ["Puissance de la pompe", `${String(data.existing_pump_cv || state.answers.existing_pump_cv || "").replace(".", ",")} CV`],
      ]
    : [["Projet", getProjectConfig().label]];

  if (recommendedPumpMode) {
    items.push(["Situation", "Recommandation de pompe"]);
    if (data.flow_m3_h) items.push(["Débit demandé", `${formatNumber(data.flow_m3_h)} m³/h`]);
    if (data.hmt_m) items.push(["HMT demandée", `${formatNumber(data.hmt_m)} m`]);
  }
  if (!pumpingProject && (data.city || state.contact.location)) {
    items.push(["Localisation", data.city || state.contact.location]);
  }
  if (!pumpingProject) {
    if (data.daily_kwh) items.push(["Consommation", `${formatNumber(data.daily_kwh)} kWh / jour`]);
    if (data.monthly_kwh) items.push(["Consommation mensuelle", `${formatNumber(data.monthly_kwh)} kWh / mois`]);
    if (data.peak_kw) items.push(["Puissance simultanée", `${formatNumber(data.peak_kw)} kW`]);
    if (data.autonomy) items.push(["Autonomie", `${formatNumber(data.autonomy)} jour(s)`]);
    if (data.available_power) items.push(["Puissance disponible", `${formatNumber(data.available_power)} kW`]);
  }
  if (state.contact.name) items.push(["Contact", state.contact.name]);
  if (state.contact.phone) items.push(["Téléphone", state.contact.phone]);
  if (state.contact.email) items.push(["E-mail", state.contact.email]);
  if (state.contact.location) items.push(["Localisation", state.contact.location]);
  if (state.contact.comment) items.push(["Commentaire", state.contact.comment]);
  return items;
}

function syncCurrentInputs() {
  const current = getCurrentStep();
  if (current.type !== "fields") {
    return;
  }
  const target = current.contact ? state.contact : state.answers;
  body.querySelectorAll("input[name], select[name], textarea[name]").forEach((input) => {
    if (input.type === "checkbox") {
      target[input.name] = input.checked;
    } else {
      target[input.name] = input.value;
    }
  });
  body.querySelectorAll("[data-inline-choice]").forEach((button) => {
    if (button.classList.contains("active")) {
      target[button.dataset.inlineChoice] = button.dataset.inlineValue;
    }
  });
  if (state.project === "pumping" && target === state.answers) {
    cleanOppositePumpingAnswers(target);
  }
  persistState();
}

async function onSubmitWizard(event) {
  event.preventDefault();
  const current = getCurrentStep();

  if (current.id === "project") {
    if (!state.project) {
      toast("Choisissez d’abord votre projet.");
      return;
    }
    state.stepIndex = 0;
    renderWizardShell();
    persistState();
    return;
  }

  if (current.type === "fields") {
    syncCurrentInputs();
    if (!validateCurrentStep(current)) {
      return;
    }
    if (current.contact) {
      const pages = getFieldPages(current);
      const pageIndex = Math.min(Number(state.mobileFieldIndex || 0), pages.length - 1);
      const isFinalContactPage = !isCompactWizard() || pages.length <= 1 || pageIndex >= pages.length - 1;
      if (isFinalContactPage) {
        const phone = String(state.contact.phone || "").trim();
        const email = String(state.contact.email || "").trim();
        if (!phone && !email) {
          toast("Un téléphone ou un e-mail suffit pour transmettre l’étude.");
          return;
        }
      }
    }
    const pages = getFieldPages(current);
    const pageIndex = Math.min(Number(state.mobileFieldIndex || 0), pages.length - 1);
    if (isCompactWizard() && pages.length > 1 && pageIndex < pages.length - 1) {
      state.mobileFieldIndex += 1;
      renderWizardShell();
      persistState();
      return;
    }
  }

  if (current.type === "choice-step") {
    if (!state.answers[current.name]) {
      state.answers[current.name] = current.defaultValue;
    }
  }

  if (current.type === "pump-cv-picker") {
    syncCurrentInputs();
    if (!state.answers.existing_pump_cv) {
      toast("Choisissez la puissance de votre pompe.");
      return;
    }
  }

  if (current.type === "loads") {
    const pages = getLoadPages();
    const pageIndex = Math.min(Number(state.mobileLoadIndex || 0), pages.length - 1);
    const maxLoadPage = Math.max(pages.length - 1, 0);
    if (isCompactWizard() && pages.length > 1 && pageIndex < maxLoadPage) {
      state.mobileLoadIndex += 1;
      renderWizardShell();
      persistState();
      return;
    }

    const totals = computeLoads();
    if (totals.daily_kwh <= 0) {
      toast("Ajoutez au moins un appareil ou utilisez la saisie directe.");
      return;
    }
  }

  if (current.type === "recap") {
    await calculate();
    return;
  }

  state.stepIndex += 1;
  state.mobileFieldIndex = 0;
  renderWizardShell();
  persistState();
}

function onBackStep() {
  if (state.stepIndex <= -1) {
    return;
  }
  syncCurrentInputs();
  const current = getCurrentStep();
  if (current.type === "fields" && isCompactWizard()) {
    const pages = getFieldPages(current);
    if ((state.mobileFieldIndex || 0) > 0 && pages.length > 1) {
      state.mobileFieldIndex -= 1;
      renderWizardShell();
      persistState();
      return;
    }
  }
  if (current.type === "loads" && isCompactWizard()) {
    const pages = getLoadPages();
    if ((state.mobileLoadIndex || 0) > 0 && pages.length > 1) {
      state.mobileLoadIndex -= 1;
      renderWizardShell();
      persistState();
      return;
    }
  }
  if (state.stepIndex === 0) {
    state.stepIndex = -1;
  } else {
    state.stepIndex -= 1;
  }
  state.mobileFieldIndex = 0;
  state.mobileLoadIndex = 0;
  renderWizardShell();
  persistState();
}

function validateCurrentStep(step) {
  const requiredInputs = body.querySelectorAll("[required]");
  for (const input of requiredInputs) {
    if (!input.value.trim()) {
      input.focus();
      toast("Merci de compléter les informations obligatoires.");
      return false;
    }
  }
  return true;
}

function buildApiPayload() {
  const project = normalizeProjectKey(state.project);
  const projectMeta = getProjectMeta(project);
  const data = pruneProjectAnswers(project, state.answers);
  const totals = computeLoads();

  if (project === "pumping") {
    data.pump_existing = pumpExistingAnswer(state.answers.pump_existing);
    if (data.pump_existing) {
      delete data.flow_m3_h;
      delete data.hmt_m;
    } else {
      delete data.existing_pump_cv;
      data.flow_m3_h = normalizeLocaleNumberAnswer(data.flow_m3_h);
      data.hmt_m = normalizeLocaleNumberAnswer(data.hmt_m);
    }
  }

  if (state.answers.energy_mode === "loads") {
    data.daily_kwh = roundTo(totals.daily_kwh, 2);
    data.peak_kw = roundTo(totals.peak_kw, 2);
    if (project === "hybrid" && totals.priority_kwh > 0) {
      data.priority_kwh = roundTo(totals.priority_kwh, 2);
    }
  }

  if (project !== "pumping" && !data.city && state.contact.location) {
    data.city = state.contact.location;
  }
  if (projectUsesLoadLibrary(project, state.answers) && state.loads.length) {
    data.loads = state.loads;
  }

  return {
    project: projectMeta?.engine_project || project,
    project_type: project,
    data,
    contact: { ...state.contact },
  };
}

async function calculate() {
  nextButton.disabled = true;
  backButton.disabled = true;
  renderAnalysisStep();
  try {
    const response = await fetch("/api/calculate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildApiPayload()),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || "Nous n'avons pas pu terminer l'étude.");
    }
    state.result = result;
    persistState();
    sessionStorage.removeItem(STORAGE_KEY);
    window.location.href = result.public_url || `/simulation/${result.quote_number}`;
  } catch (error) {
    nextButton.disabled = false;
    backButton.disabled = false;
    state.stepIndex = getSteps().length - 1;
    renderWizardShell();
    toast(error.message || "Nous n'avons pas pu terminer l'étude.");
  }
}

function renderAnalysisStep() {
  const analysisSteps = [
    "Besoin énergétique analysé",
    "Données locales prises en compte",
    "Dimensionnement effectué",
    "Catalogue HeliAntha analysé",
    "Compatibilités vérifiées",
    "Estimation financière préparée",
  ];

  body.innerHTML = `
    <section class="wizard-step">
      <span class="eyebrow">Analyse en cours</span>
      <h2>Analyse de votre projet</h2>
      <p>HeliAntha prépare votre estimation à partir des informations saisies.</p>
      <div class="analysis-grid">
        ${analysisSteps.map((item, index) => `
          <article class="analysis-card ${index === 0 ? "active" : ""}" data-analysis-index="${index}">
            <span class="analysis-icon">${index === 0 ? "…" : "•"}</span>
            <div>
              <strong>${item}</strong>
              <div class="analysis-line">${index < analysisSteps.length - 1 ? "Étape en cours de vérification" : "Préparation du résultat"}</div>
            </div>
          </article>
        `).join("")}
      </div>
    </section>
  `;

  let index = 0;
  const timer = setInterval(() => {
    const cards = body.querySelectorAll("[data-analysis-index]");
    if (!cards.length) {
      clearInterval(timer);
      return;
    }
    cards.forEach((card, position) => {
      card.classList.toggle("done", position < index);
      card.classList.toggle("active", position === index);
      const icon = card.querySelector(".analysis-icon");
      if (icon) {
        icon.textContent = position < index ? "✓" : position === index ? "…" : "•";
      }
    });
    index = (index + 1) % analysisSteps.length;
  }, 300);
}

function computeLoads() {
  return state.loads.reduce((totals, load) => {
    const quantity = Number(load.quantity || 0);
    const power = Number(load.power_w || 0);
    const hours = Number(load.hours || 0);
    const daily = (quantity * power * hours) / 1000;
    totals.daily_kwh += daily;
    if (load.simultaneous) {
      totals.peak_kw += (quantity * power) / 1000;
    }
    if (load.priority) {
      totals.priority_kwh += daily;
    }
    return totals;
  }, { daily_kwh: 0, peak_kw: 0, priority_kwh: 0 });
}

function defaultCustomLoad(name, quantity, power_w, hours, simultaneous, priority) {
  return { name, quantity, power_w, hours, simultaneous, priority };
}

function iconForDevice(name, category) {
  const label = `${category} ${name}`.toLowerCase();
  if (label.includes("lampe") || label.includes("éclairage")) return "💡";
  if (label.includes("réfrig") || label.includes("congél")) return "🧊";
  if (label.includes("micro") || label.includes("bouilloire")) return "🍽️";
  if (label.includes("ventil") || label.includes("clim")) return "🌬️";
  if (label.includes("télé") || label.includes("ordinateur") || label.includes("internet")) return "🖥️";
  if (label.includes("pompe")) return "💧";
  if (label.includes("moteur") || label.includes("machine")) return "⚙️";
  return "🔌";
}

function roundTo(value, digits = 2) {
  const factor = 10 ** digits;
  return Math.round(parseLocaleNumber(value) * factor) / factor;
}

function formatNumber(value, digits = 1) {
  const number = parseLocaleNumber(value);
  return new Intl.NumberFormat("fr-FR", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  }).format(number);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
function toast(message) {
  const element = document.querySelector("#toast");
  element.textContent = message;
  element.classList.add("show");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => element.classList.remove("show"), 3000);
}

window.HELIANTHA_WIZARD = {
  open: openWizard,
  applyPrefill: applyWizardPrefill,
  getState: () => state,
};
