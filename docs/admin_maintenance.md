# Maintenance de l’administration

La page `/admin/maintenance` rassemble quatre sections ouvertes dans des dialogues,
sans navigation ni rechargement. Les indicateurs relisent les derniers contrôles
enregistrés ; les connexions et l’analyse métier sont vérifiées uniquement à la demande.
Les heures affichées permettent de distinguer un résultat ancien d’un état actuel.

## Configuration

Les contrôles HTTP sont exécutés par Flask, sur la machine qui l’héberge.
`127.0.0.1` désigne donc le serveur en production, et le PC en développement.
`MOBILE_API_BASE_URL` désigne l’adresse interne du backend mobile, sans `/health`.
Vide ou absent : API sur ce même serveur au port 8011. Pour un autre port,
un conteneur ou un service séparé, renseigner l’URL interne du déploiement.
Aucune URL fournie par le navigateur n’est interrogée.
Ollama utilise `OLLAMA_HOST` et `OLLAMA_MODEL` existants. WhatsApp utilise
la passerelle déjà configurée dans les paramètres de l’application.
Le nom du serveur apparaît dans la page. Les diagnostics enregistrés sont liés
au serveur, à la base et aux adresses des services : après déplacement de la base
ou changement de configuration, ils doivent être relancés. Le mode maintenance
reste une décision explicite enregistrée en base.

## Périmètre des actions

- Les diagnostics ne réparent ni les fiches produits ni les devis.
- Le cache ciblé est le contexte de calcul existant, avec son invalidation Redis
  si Redis est disponible. Les caches du backend mobile indépendant ne sont pas vidés.
- Le nettoyage traite au plus 500 fichiers directs de `instance/tmp`, uniquement
  `.tmp`, `.part` et `.temp`, âgés de plus de 24 heures. Pas de parcours récursif,
  de liens suivis, de suppression de PDF, de bases ou de sauvegardes.
  Les PDF de devis actuellement générés en mémoire ne produisent pas de fichiers à nettoyer.
- Le mode maintenance protège les pages publiques et API Flask avec HTTP 503.
  Les navigateurs reçoivent une page dédiée ; les API reçoivent `maintenance: true`.
  L’administration, ses ressources et `/health` restent disponibles. Une session
  administrateur signée correspondant à un compte actif permet de tester le site.
  Le statut public `/api/maintenance/status` reste accessible, sans cache, sans
  exposer l’auteur de l’action ni les diagnostics internes.
- L’API mobile lit ce même statut avant chaque requête métier, via
  `FLASK_INTERNAL_URL` dans son propre environnement. Elle refuse l’opération avant
  tout appel PrestaShop si la maintenance est active ou si le statut est inconnu.
  Ses webhooks signés de notification et sa santé restent disponibles.
- Flutter surveille `/v1/maintenance/status` par requête longue (25 s maximum).
  Le serveur renvoie un changement dès sa détection, normalement sous une seconde
  plus le temps réseau. Les vérifications anonymes sont mutualisées par worker.
  Pas de rechargement : écran dédié, WhatsApp, retour automatique, panier et
  formulaires conservés. Surveillance suspendue en arrière-plan, contrôle au retour.
- Les services Flask, FastAPI et le build Flutter doivent tous être déployés pour
  ce comportement. PrestaShop n’est pas mis en maintenance et n’est pas modifié.
  Le mode ne s’active jamais automatiquement au déploiement.
- Les actions sont réservées aux comptes actifs `Direction`, protégées par CSRF,
  confirmées dans l’interface et journalisées avec l’auteur et la date.

## Persistance et observations IA

Deux tables SQLite additionnelles (`maintenance_state`, `maintenance_events`) sont
créées par l’initialisation habituelle du schéma. Aucun historique métier n’est réécrit.
Le mode et les derniers résultats survivent aux redémarrages. Les appels Ollama
enregistrent leur durée et un état de réussite ; aucun prompt, réponse client, token
ou détail d’exception n’est stocké. Le dernier incident est celui observé depuis
l’installation de cette supervision. Le test explicite conserve `keep_alive: -1`.

Les opérations concurrentes sont refusées dans un même processus. Avec plusieurs
workers, les consultations et les opérations idempotentes peuvent se chevaucher ;
les résultats et le mode restent persistés dans la même base SQLite.

## Validation

`python -m pytest tests/test_admin_maintenance.py -v`

La suite couvre l’accès, le CSRF, le mode persistant, les services indisponibles,
l’observation IA, les anomalies métier et le nettoyage restreint.
