"""Script to apply pumping context retention, 50cv direct sizing, role reversal sanitization, and technical guardrails in ai_service.py."""

import re
from pathlib import Path

file_path = Path("app/services/ai_service.py")
content = file_path.read_text(encoding="utf-8").replace("\r\n", "\n")

# 1. Update _DEFAULT_BATTERIES image URLs & Add _DEFAULT_DRIVES
old_batteries = '''    {
        "id": 202232,
        "reference": "DEYE-BOS-G-5.12",
        "name": "Batterie Lithium LiFePO4 Deye 5.12 kWh",
        "brand": "Deye",
        "model": "SE-G5.1PRO-B",
        "category": "batteries",
        "power_w": 5120.0,
        "description": "Batterie LiFePO4 5.12 kWh 51.2V 100Ah",
        "price": 16000.0,
        "price_tax": "HT",
        "currency": "DH",
        "en_stock": True,
        "datasheet_url": "",
        "source": "local_sqlite",
        "image_url": "/v1/products/331/image?image_id=552",
    },
    {
        "id": 202233,
        "reference": "DEYE-RW-M6.1",
        "name": "Batterie Lithium LiFePO4 Deye 10.24 kWh",
        "brand": "Deye",
        "model": "RW-M6.1-B",
        "category": "batteries",
        "power_w": 10240.0,
        "description": "Pack Batterie LiFePO4 10 kWh",
        "price": 29000.0,
        "price_tax": "HT",
        "currency": "DH",
        "en_stock": True,
        "datasheet_url": "",
        "source": "local_sqlite",
        "image_url": "/v1/products/331/image?image_id=552",
    },
]'''

new_batteries_and_drives = '''    {
        "id": 202232,
        "reference": "DEYE-BOS-G-5.12",
        "name": "Batterie Lithium LiFePO4 Deye 5.12 kWh",
        "brand": "Deye",
        "model": "SE-G5.1PRO-B",
        "category": "batteries",
        "power_w": 5120.0,
        "description": "Batterie LiFePO4 5.12 kWh 51.2V 100Ah",
        "price": 16000.0,
        "price_tax": "HT",
        "currency": "DH",
        "en_stock": True,
        "datasheet_url": "",
        "source": "local_sqlite",
        "image_url": "/v1/products/330/image?image_id=545",
    },
    {
        "id": 202233,
        "reference": "DEYE-RW-M6.1",
        "name": "Batterie Lithium LiFePO4 Deye 10.24 kWh",
        "brand": "Deye",
        "model": "RW-M6.1-B",
        "category": "batteries",
        "power_w": 10240.0,
        "description": "Pack Batterie LiFePO4 10 kWh",
        "price": 29000.0,
        "price_tax": "HT",
        "currency": "DH",
        "en_stock": True,
        "datasheet_url": "",
        "source": "local_sqlite",
        "image_url": "/v1/products/330/image?image_id=545",
    },
]

_DEFAULT_DRIVES = [
    {
        "id": 5,
        "reference": "SI23-D5-5R5",
        "name": "Variateur Solaire MPPT Inomax 5.5 kW (7.5 CV)",
        "brand": "Inomax",
        "model": "SI23-D5-5R5",
        "category": "drives",
        "power_kw": 5.5,
        "description": "Variateur MPPT solaire 5.5 kW / 7.5 CV 380V Triphasé",
        "price": 2375.0,
        "price_tax": "HT",
        "currency": "DH",
        "en_stock": True,
        "datasheet_url": "",
        "source": "local_sqlite",
        "image_url": "/v1/products/338/image?image_id=576",
    },
    {
        "id": 8,
        "reference": "SI23-T3-015",
        "name": "Variateur Solaire MPPT Inomax 15 kW (20 CV)",
        "brand": "Inomax",
        "model": "SI23-T3-015",
        "category": "drives",
        "power_kw": 15.0,
        "description": "Variateur MPPT solaire 15 kW / 20 CV 380V Triphasé",
        "price": 4583.33,
        "price_tax": "HT",
        "currency": "DH",
        "en_stock": True,
        "datasheet_url": "",
        "source": "local_sqlite",
        "image_url": "/v1/products/338/image?image_id=576",
    },
]'''

assert old_batteries in content, "old_batteries not found in content"
content = content.replace(old_batteries, new_batteries_and_drives, 1)

# 2. Update get_dynamic_suggested_products fallback to handle "drives"
old_fallback = '''    # Repli de secours garanti avec images propres
    if category == "inverters":
        fallback = [dict(p) for p in _DEFAULT_INVERTERS]
    elif category == "batteries":
        fallback = [dict(p) for p in _DEFAULT_BATTERIES]
    else:
        fallback = [dict(p) for p in _DEFAULT_PANELS]'''

new_fallback = '''    # Repli de secours garanti avec images propres
    if category == "drives":
        fallback = [dict(p) for p in _DEFAULT_DRIVES]
    elif category == "inverters":
        fallback = [dict(p) for p in _DEFAULT_INVERTERS]
    elif category == "batteries":
        fallback = [dict(p) for p in _DEFAULT_BATTERIES]
    else:
        fallback = [dict(p) for p in _DEFAULT_PANELS]'''

assert old_fallback in content, "old_fallback not found in content"
content = content.replace(old_fallback, new_fallback, 1)

# 3. Add _detect_pumping_power before _sanitize_ai_response and enhance _sanitize_ai_response
detect_pumping_code = '''
def _detect_pumping_power(
    query: str, history_text: str = "", branch: str = ""
) -> dict[str, Any] | None:
    """Détecte avec précision la puissance d'une pompe agricole (CV ou kW) et dimensionne au fil du soleil."""
    import math

    q = (query or "").lower().strip()
    h = (history_text or "").lower().strip()
    if not q:
        return None

    # 1. Détection explicite en CV / CH / HP / CHEVAUX
    cv_match = re.search(r"\\b(\\d+(?:[.,]\\d+)?)\\s*(?:cv|ch|chevaux|cheval|hp)\\b", q)

    # 2. Contexte pompage agricole
    pumping_context = (
        branch == "pumping"
        or any(w in q for w in ["pomp", "puits", "bassin", "forage", "irrigation", "variateur", "fellah"])
        or match_darija(q, "pompage")
        or any(w in h for w in ["pomp", "puits", "bassin", "forage", "irrigation", "variateur", "fellah"])
        or match_darija(h, "pompage")
        or bool(re.search(r"puissance\\s+de\\s+votre\\s+pompe|en\\s+cv\\s+ou\\s+(?:en\\s+)?kw", h))
    )

    kw_val = None
    cv_val = None

    if cv_match:
        try:
            cv_val = float(cv_match.group(1).replace(",", "."))
            kw_val = round(cv_val * 0.746, 2)
        except (ValueError, TypeError):
            return None
    elif pumping_context:
        # Détection en kW dans un contexte pompage
        kw_match = re.search(r"\\b(\\d+(?:[.,]\\d+)?)\\s*(?:kw|kilowatt[s]?)\\b", q)
        if kw_match:
            try:
                kw_val = float(kw_match.group(1).replace(",", "."))
                cv_val = round(kw_val / 0.746, 1)
            except (ValueError, TypeError):
                return None
        else:
            # Réponse numérique brute si l'assistant vient de demander la puissance de la pompe
            if re.search(r"puissance\\s+de\\s+votre\\s+pompe|en\\s+cv\\s+ou\\s+(?:en\\s+)?kw", h):
                num_match = re.match(r"^(?:environ\\s+|c['’]est\\s+)?(\\d+(?:[.,]\\d+)?)\\s*$", q)
                if num_match:
                    try:
                        cv_val = float(num_match.group(1).replace(",", "."))
                        kw_val = round(cv_val * 0.746, 2)
                    except (ValueError, TypeError):
                        return None

    if cv_val is None or kw_val is None or cv_val <= 0 or cv_val > 500:
        return None

    # Ratio solaire HeliAntha officiel : 1.35x la puissance nominale de la pompe
    solar_kwc = round(kw_val * 1.35, 1)
    panels_725 = math.ceil(solar_kwc * 1000 / 725)
    panels_585 = math.ceil(solar_kwc * 1000 / 585)

    # Calibre standard du variateur MPPT (Triphasé 380V standard au Maroc)
    if kw_val <= 2.2:
        variateur_kw = 2.2
    elif kw_val <= 4.0:
        variateur_kw = 4.0
    elif kw_val <= 5.5:
        variateur_kw = 5.5
    elif kw_val <= 7.5:
        variateur_kw = 7.5
    elif kw_val <= 11.0:
        variateur_kw = 11.0
    elif kw_val <= 15.0:
        variateur_kw = 15.0
    elif kw_val <= 18.5:
        variateur_kw = 18.5
    elif kw_val <= 22.0:
        variateur_kw = 22.0
    elif kw_val <= 30.0:
        variateur_kw = 30.0
    elif kw_val <= 37.5:
        variateur_kw = 45.0 if kw_val > 30 else 37.0
    elif kw_val <= 45.0:
        variateur_kw = 45.0
    elif kw_val <= 55.0:
        variateur_kw = 55.0
    elif kw_val <= 75.0:
        variateur_kw = 75.0
    else:
        variateur_kw = round(kw_val * 1.2, 1)

    return {
        "cv": int(cv_val) if cv_val.is_integer() else round(cv_val, 1),
        "kw": int(kw_val) if kw_val.is_integer() else round(kw_val, 1),
        "solar_kwc": solar_kwc,
        "panels_725": panels_725,
        "panels_585": panels_585,
        "variateur_kw": variateur_kw,
    }

'''

old_sanitize = '''def _sanitize_ai_response(text: str, user_count: int = 1) -> str:
    if not isinstance(text, str):
        return text

    cleaned = text.strip()

    # 1. Bannissement absolu des introductions de politesse répétées
    if user_count > 1:
        patterns = [
            r"^(Bonjour|Bonsoir|Salut)\s*[!,.]?\s*",
            r"^(Je suis\s+)?(ravi|heureux|enchante)\s+d['’](entendre|apprendre|accueillir)[^\n.!?]*[.!?:]*\s*",
            r"^(Je suis\s+)?(ravi|heureux|enchante)\s+de\s+vous\s+aider[^\n.!?]*[.!?:]*\s*",
            r"^C['’]est un plaisir de vous aider[^\n.!?]*[.!?:]*\s*",
            r"^Bonjour\s*!\s*Je suis votre conseiller[^\n.!?]*[.!?:]*\s*",
            r"^(En tant que conseiller|Bienvenue chez HeliAntha)[^\n.!?]*[.!?:]*\s*",
        ]
        for _ in range(2):
            for p in patterns:
                cleaned = re.sub(p, "", cleaned, flags=re.IGNORECASE).strip()

    # 2. Éradication des hallucinations ("solaires à pile", "piles")
    cleaned = re.sub(r"solaires?\s+[aà]\s+pile[s]?", "panneaux photovoltaïques", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"panneaux?\s+[aà]\s+pile[s]?", "panneaux solaires", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bpile[s]?\b", "batteries", cleaned, flags=re.IGNORECASE)'''

new_sanitize = detect_pumping_code + '''def _sanitize_ai_response(text: str, user_count: int = 1) -> str:
    if not isinstance(text, str):
        return text

    cleaned = text.strip()

    # 1. Bannissement absolu des introductions de politesse répétées
    if user_count > 1:
        patterns = [
            r"^(Bonjour|Bonsoir|Salut)\s*[!,.]?\s*",
            r"^(Je suis\s+)?(ravi|heureux|enchante)\s+d['’](entendre|apprendre|accueillir)[^\n.!?]*[.!?:]*\s*",
            r"^(Je suis\s+)?(ravi|heureux|enchante)\s+de\s+vous\s+aider[^\n.!?]*[.!?:]*\s*",
            r"^C['’]est un plaisir de vous aider[^\n.!?]*[.!?:]*\s*",
            r"^Bonjour\s*!\s*Je suis votre conseiller[^\n.!?]*[.!?:]*\s*",
            r"^(En tant que conseiller|Bienvenue chez HeliAntha)[^\n.!?]*[.!?:]*\s*",
        ]
        for _ in range(2):
            for p in patterns:
                cleaned = re.sub(p, "", cleaned, flags=re.IGNORECASE).strip()

    # 1.bis Éradication des inversions de rôles (l'assistant qui s'exprime comme un client)
    role_inversions = [
        r"^Je suis à la recherche d['’][^\n.!?]*[.!?:]*\s*",
        r"^Je recherche\s+[^\n.!?]*[.!?:]*\s*",
        r"^Je cherche\s+[^\n.!?]*[.!?:]*\s*",
        r"^J['’]ai besoin d['’][^\n.!?]*[.!?:]*\s*",
        r"^Je souhaite\s+(?:installer|acheter|trouver|acquérir)[^\n.!?]*[.!?:]*\s*",
        r"^Je voudrais\s+(?:savoir|trouver|un\s+devis)[^\n.!?]*[.!?:]*\s*",
    ]
    for p in role_inversions:
        cleaned = re.sub(p, "", cleaned, flags=re.IGNORECASE).strip()

    # 1.ter Correction des unités erronées ("W/c" -> "Wc")
    cleaned = re.sub(r"\bW/c\b", "Wc", cleaned, flags=re.IGNORECASE)

    # 2. Éradication des hallucinations ("solaires à pile", "piles")
    cleaned = re.sub(r"solaires?\s+[aà]\s+pile[s]?", "panneaux photovoltaïques", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"panneaux?\s+[aà]\s+pile[s]?", "panneaux solaires", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bpile[s]?\b", "batteries", cleaned, flags=re.IGNORECASE)'''

assert old_sanitize in content, "old_sanitize not found in content"
content = content.replace(old_sanitize, new_sanitize, 1)

# 4. Update _get_commercial_direct_answer signature & insert pump detection
old_get_comm = '''def _get_commercial_direct_answer(query: str) -> dict[str, Any] | None:
    """Fast-Path intelligent tolérant au Darija, français et phonétique."""
    q = (query or "").lower().strip()
    if not q:
        return None

    # Si la question est technique pointue, laisser passer vers Ollama ou le calculateur
    if any(term in q for term in ["mppt", "pwm", "micro-onduleur", "microonduleur", "optimiseur", "cos phi", "section de cable"]):
        return None

    cta = _detect_bill_and_build_cta(query)'''

new_get_comm = '''def _get_commercial_direct_answer(
    query: str, messages: list[dict[str, str]] | None = None
) -> dict[str, Any] | None:
    """Fast-Path commercial intelligent avec détection pompage agricole, factures, Darija et CTA."""
    q = (query or "").lower().strip()
    if not q:
        return None

    # Si la question est une comparaison théorique pointue, laisser passer vers le moteur expert
    if any(term in q for term in ["mppt vs pwm", "pwm vs mppt", "section de cable"]):
        return None

    branch = project_branch(messages) if messages else ""
    history_str = (
        " ".join(str(m.get("content") or "") for m in messages[:-1])
        if messages and len(messages) > 1
        else ""
    )

    # Cas 0 : Détection directe d'une puissance de pompe agricole (CV ou kW pompage)
    pump = _detect_pumping_power(query, history_text=history_str, branch=branch)
    if pump:
        content = (
            f"Pour une pompe agricole de **{pump['cv']} CV** (~{pump['kw']} kW), nous préconisons un champ solaire d'environ **{pump['solar_kwc']} kWc** "
            f"(soit environ {pump['panels_725']} panneaux HeliAntha 725 Wc ou {pump['panels_585']} panneaux de 585 Wc) associé à un **variateur de pompage solaire MPPT de {pump['variateur_kw']:g} kW** (Triphasé 380V).\\n\\n"
            f"Le système fonctionne directement au fil du soleil, sans aucune batterie ni onduleur hybride, avec coffret de protection DC/AC et sondes de puits. Cliquez ci-dessous pour voir le dimensionnement complet."
        )
        pump_prods = (
            get_dynamic_suggested_products("drives", 2)
            or get_dynamic_suggested_products("panels", 3)
        )
        return {
            "content": content,
            "products": pump_prods,
            "action": {
                "type": "open_pumping_calculator",
                "pump_power_cv": pump["cv"],
                "pump_power_kw": pump["kw"],
                "estimated_kwc": pump["solar_kwc"],
                "label": f"Lancer le dimensionnement pompage ({pump['solar_kwc']} kWc)",
                "button_text": f"Lancer le dimensionnement pompage ({pump['solar_kwc']} kWc)",
            },
        }

    cta = _detect_bill_and_build_cta(query)'''

assert old_get_comm in content, "old_get_comm not found in content"
content = content.replace(old_get_comm, new_get_comm, 1)

# 5. In Cas 3 of _get_commercial_direct_answer, prefer drives for suggested products
old_cas3_prods = '''        pump_prods = get_dynamic_suggested_products("inverters", 2) or get_dynamic_suggested_products("panels", 3)'''
new_cas3_prods = '''        pump_prods = get_dynamic_suggested_products("drives", 2) or get_dynamic_suggested_products("panels", 3)'''
assert old_cas3_prods in content, "old_cas3_prods not found in content"
content = content.replace(old_cas3_prods, new_cas3_prods, 1)

# 6. Pass messages in quick_assistant_response
old_quick_call = '''    # Fast-Path Commercial avec RAG, Darija et Action CTA
    _fast_res = _get_commercial_direct_answer(latest)'''
new_quick_call = '''    # Fast-Path Commercial avec RAG, Darija et Action CTA
    _fast_res = _get_commercial_direct_answer(latest, messages=messages)'''
assert old_quick_call in content, "old_quick_call not found in content"
content = content.replace(old_quick_call, new_quick_call, 1)

# 7. Pass messages in offline_fallback_response
old_offline_call = '''    direct = _get_commercial_direct_answer(latest)'''
new_offline_call = '''    direct = _get_commercial_direct_answer(latest, messages=messages)'''
assert old_offline_call in content, "old_offline_call not found in content"
content = content.replace(old_offline_call, new_offline_call, 1)

# 8. Add anti-battery guard for pumping and fix "watts-cr?te" typo in _guard_technical_content
old_guard = '''    domestic = project_branch(messages) == "domestic"
    text = _normalize_text(visible)
    invalid_domestic = domestic and re.search(
        r"\\b(?:pompes?|pompage|variateurs?|cv|ch|hp|chevaux|puits|forage|irrigation|hmt|debit)\\b",
        text,
    )
    invalid_panel = re.search(
        r"\\bpanneaux?\\s+(?:solaires?\\s+)?(?:(?:de|en|produit|fournit)\\s+)?"
        r"\\d+(?:[.,]\\d+)?\\s*(?:cv|ch|hp|v(?:olts?)?\\s*(?:ac|alternatifs?))\\b", text,
    )
    explicit_domestic = any(
        message.get("role") == "user" and _DOMESTIC_RE.search(_normalize_text(message.get("content", "")))
        for message in messages
    )
    quote_data = quote or {}
    quote_mode = str(
        quote_data.get("mode") or quote_data.get("project") or quote_data.get("type") or ""
    ).strip().lower()
    pumping_quote = quote_mode in {"pumping", "pompage", "pump"} or bool(
        _PUMPING_RE.search(_normalize_text(quote_data.get("system_summary", "")))
    )
    incompatible_quote = (
        domestic and explicit_domestic and pumping_quote
        or not domestic and quote_mode in {"ongrid", "on-grid", "photovoltaic", "hybrid", "hybride"}
    )
    if not (invalid_domestic or invalid_panel or incompatible_quote):
        user_count = sum(1 for m in messages if isinstance(m, dict) and m.get("role") == "user")
        return _sanitize_ai_response(content, user_count=user_count)
    correction = (
        "Pour dimensionner vos panneaux solaires et votre onduleur, quel est le montant moyen de votre facture d'électricité mensuelle (en DH) ?"
    ) if domestic else (
        "Les panneaux solaires s'expriment en Wc (watts-cr?te). "
        "Pour dimensionner le champ solaire et le variateur de pompage, quelle est la puissance de votre pompe (en CV ou kW) ?"
    )'''

new_guard = '''    branch = project_branch(messages)
    domestic = branch == "domestic"
    text = _normalize_text(visible)
    invalid_domestic = domestic and re.search(
        r"\\b(?:pompes?|pompage|variateurs?|cv|ch|hp|chevaux|puits|forage|irrigation|hmt|debit)\\b",
        text,
    )
    invalid_panel = re.search(
        r"\\bpanneaux?\\s+(?:solaires?\\s+)?(?:(?:de|en|produit|fournit)\\s+)?"
        r"\\d+(?:[.,]\\d+)?\\s*(?:cv|ch|hp|v(?:olts?)?\\s*(?:ac|alternatifs?))\\b", text,
    )

    # Garde-fou strict : Le pompage agricole au Maroc est au fil du soleil sans batteries
    user_asked_battery = any(
        re.search(r"\\b(?:batterie[s]?|stockage|lifepo4)\\b", _normalize_text(m.get("content", "")))
        for m in messages if isinstance(m, dict) and m.get("role") == "user"
    )
    invalid_pumping_battery = (not domestic) and (not user_asked_battery) and bool(re.search(
        r"\\b(?:onduleur\\s+hybride|batterie[s]?\\s+(?:de\\s+)?\\d+|avec\\s+batterie[s]?|stockage\\s+par\\s+batterie|lifepo4)\\b",
        text,
    ))
    if invalid_pumping_battery:
        return (
            "Le pompage solaire agricole fonctionne directement au fil du soleil via un variateur MPPT dédié, "
            "sans batterie ni onduleur hybride. "
            "Pour dimensionner votre champ solaire et le variateur, quelle est la puissance de votre pompe (en CV ou kW) ?"
        )

    explicit_domestic = any(
        message.get("role") == "user" and _DOMESTIC_RE.search(_normalize_text(message.get("content", "")))
        for message in messages
    )
    quote_data = quote or {}
    quote_mode = str(
        quote_data.get("mode") or quote_data.get("project") or quote_data.get("type") or ""
    ).strip().lower()
    pumping_quote = quote_mode in {"pumping", "pompage", "pump"} or bool(
        _PUMPING_RE.search(_normalize_text(quote_data.get("system_summary", "")))
    )
    incompatible_quote = (
        domestic and explicit_domestic and pumping_quote
        or not domestic and quote_mode in {"ongrid", "on-grid", "photovoltaic", "hybrid", "hybride"}
    )
    if not (invalid_domestic or invalid_panel or incompatible_quote):
        user_count = sum(1 for m in messages if isinstance(m, dict) and m.get("role") == "user")
        return _sanitize_ai_response(content, user_count=user_count)
    correction = (
        "Pour dimensionner vos panneaux solaires et votre onduleur, quel est le montant moyen de votre facture d'électricité mensuelle (en DH) ?"
    ) if domestic else (
        "Les panneaux solaires s'expriment en Wc (watts-crête). "
        "Pour dimensionner le champ solaire et le variateur de pompage, quelle est la puissance de votre pompe (en CV ou kW) ?"
    )'''

assert old_guard in content, "old_guard not found in content"
content = content.replace(old_guard, new_guard, 1)

file_path.write_text(content, encoding="utf-8")
print("SUCCESS: ai_service.py successfully patched.")
