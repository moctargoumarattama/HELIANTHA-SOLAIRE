# HeliAntha Smart Quote

Application Flask de pré-dimensionnement solaire et de gestion de pré-devis HeliAntha.

## Lancer le projet

```powershell
python -m pip install -r requirements.txt
python run.py
```

Site public : `http://127.0.0.1:5000`

Administration : `http://127.0.0.1:5000/admin/`

Mot de passe admin de développement : `heliantha2026`

Pour le changer :

```powershell
$env:HELIANTHA_ADMIN_PASSWORD="mot-de-passe-solide"
python run.py
```

## Architecture actuelle

- `app/routes.py` : routes publiques, API de calcul et espace admin.
- `app/db.py` : migrations SQLite sûres, snapshots devis, catalogue, paramètres, tarification.
- `app/defaults.py` : paramètres, catalogue et référentiel provisoires de départ.
- `app/calculators/engine.py` : moteurs de calcul structurés et `PricingEngine`.
- `templates/index.html` et `static/js/app.js` : parcours client public.
- `templates/admin/` et `static/css/admin.css` : administration HeliAntha.
- `tests/test_engine.py` : tests moteur, API, snapshots, admin et migrations.

## Ce qui est inclus

- parcours public pour pompage, Off-Grid, On-Grid, hybride, thermique et borne EV ;
- IoT conservé dans le code mais masqué temporairement côté public ;
- résultats structurés : inputs, hypothèses, paramètres, résultats intermédiaires, avertissements, équipements et versions ;
- décomposition financière : matériel, accessoires, protections, câblage, structure, installation, main-d'oeuvre, déplacement, marge, TVA ;
- snapshots de devis pour conserver les anciens prix, paramètres et équipements ;
- catalogue centralisé avec activation/désactivation des produits ;
- paramètres de calcul et tarification modifiables depuis l'admin ;
- dashboard, prospects, liste des devis, détail de devis, référentiel, paramètres généraux et utilisateurs ;
- version imprimable/PDF navigateur basée sur le snapshot du devis ;
- tests automatisés.

## Important

Les formules, coefficients, équipements et prix restent provisoires. Ils sont isolés dans `app/defaults.py`, stockés en SQLite après migration, puis lus côté serveur par `app/calculators/engine.py`.

Les anciennes demandes sont conservées dans `instance/heliantha.db`. Les nouveaux devis gardent leur propre snapshot pour ne jamais changer rétroactivement quand le catalogue ou les paramètres évoluent.
