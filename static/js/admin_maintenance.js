(() => {
  'use strict';
  const root = document.getElementById('maintenance-workspace');
  if (!root) return;
  let snapshot = null;
  let pending = false;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const $ = id => document.getElementById(id);
  const date = value => value ? new Date(value).toLocaleString('fr-MA') : 'Aucune observation';
  const duration = ms => ms == null ? '—' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
  const text = (id, value) => { $(id).textContent = value; };
  function node(tag, className, value) {
    const el = document.createElement(tag);
    el.className = className;
    if (value != null) el.textContent = value;
    return el;
  }
  function empty(target, message) { target.replaceChildren(node('p', 'mt-empty', message)); }
  function result(title, detail, state = '', label = '') {
    const article = node('article', 'mt-result');
    const head = node('div', 'mt-result-head');
    head.append(node('h3', '', title));
    if (label) head.append(node('span', `mt-state ${state}`, label));
    article.append(head, node('p', '', detail));
    return article;
  }
  function feedback(message, error = false) {
    text('mt-feedback', message);
    const dialog = document.querySelector('.mt-dialog[open]');
    if (dialog) dialog.querySelector('[data-dialog-feedback]').textContent = message;
    window.showAdminToast?.(message, error ? 'error' : 'info', 'Maintenance');
  }
  function render(data) {
    snapshot = data;
    text('mt-server', `Serveur : ${data.deployment.host}`);
    const services = data.services;
    text('mt-count-services', services ? `${services.items.filter(s => s.status === 'ok').length} / 5` : '— / 5');
    text('mt-services-time', services ? date(services.checked_at) : 'Pas encore vérifiés');
    text('mt-count-issues', data.integrity ? String(data.integrity.count) : '—');
    text('mt-integrity-time', data.integrity ? date(data.integrity.checked_at) : 'Analyse non effectuée');
    const run = data.ai.last_run;
    text('mt-ai-latency', run?.success ? duration(run.duration_ms) : run ? 'À vérifier' : '—');
    text('mt-ai-time', run ? `${run.source === 'test' ? 'Test' : 'Conversation'} · ${date(run.at)}` : 'Aucune mesure disponible');
    const enabled = data.mode.enabled === true;
    text('mt-mode-label', enabled ? 'En pause' : 'En service');
    text('mt-mode-time', enabled ? 'Mode maintenance activé' : 'Demandes publiques autorisées');
    $('mt-mode-dot').classList.toggle('amber', enabled);
    text('mt-mode-detail', data.mode.updated_at ? `Dernier changement : ${date(data.mode.updated_at)}` : 'Mode maintenance désactivé.');
    text('mt-mode-button', enabled ? 'Remettre en service' : 'Activer la maintenance');
    $('mt-mode-button').setAttribute('aria-pressed', String(enabled));
    renderServices(services);
    renderAI(data.ai);
    renderIntegrity(data.integrity);
    const history = $('mt-operation-history');
    history.replaceChildren();
    if (!data.events.length) empty(history, 'Aucune intervention enregistrée.');
    for (const item of data.events) {
      const row = result(item.message, `${item.actor} · ${date(item.created_at)}`);
      history.append(row);
    }
  }
  function renderServices(data) {
    const target = $('mt-results-services');
    if (!data) return empty(target, 'Connexions à vérifier.');
    target.replaceChildren(node('small', 'muted', `Dernier contrôle : ${date(data.checked_at)}`));
    const labels = {ok: 'Disponible', warning: 'À vérifier', error: 'Indisponible', unknown: 'Non configuré'};
    for (const service of data.items) {
      const row = result(service.label, service.detail, service.status, labels[service.status]);
      if (service.duration_ms != null) row.append(node('small', '', `Temps de réponse : ${duration(service.duration_ms)}`));
      target.append(row);
    }
  }
  function renderAI(data) {
    const target = $('mt-results-ai');
    target.replaceChildren(result('Modèle configuré', data.model));
    const run = data.last_run;
    target.append(result('Dernière sollicitation', run ? `${date(run.at)} · ${duration(run.duration_ms)} · ${run.source === 'test' ? 'Test' : 'Conversation'}` : 'Aucune mesure sur ce serveur.',
      run?.success ? 'ok' : run ? 'warning' : '', run ? run.success ? 'Réponse reçue' : 'Sans réponse' : 'Non testé'));
    target.append(result('Dernier incident', data.last_incident ? `${date(data.last_incident.at)} — ${data.last_incident.message}` : 'Aucun incident enregistré.'));
  }
  function renderIntegrity(data) {
    const target = $('mt-results-integrity');
    if (!data) return empty(target, 'Analyse à lancer.');
    target.replaceChildren(node('small', 'muted', `${data.products_checked} produits et ${data.quotes_checked} devis analysés · ${date(data.checked_at)}`));
    for (const group of data.groups) {
      const row = result(group.title, group.count ? `${group.count} point(s) à vérifier.` : 'Aucune anomalie détectée.', group.count ? 'warning' : 'ok', String(group.count));
      if (group.items.length) {
        const list = node('ul', 'mt-issue-list');
        for (const item of group.items) {
          const li = node('li', '');
          li.append(node('strong', '', item.label), document.createTextNode(` — ${item.detail}`));
          list.append(li);
        }
        row.append(list);
        if (group.count > group.items.length) row.append(node('small', '', 'Les 20 premiers résultats sont affichés.'));
      }
      target.append(row);
    }
  }
  async function request(url, body) {
    const response = await fetch(url, {method: body === undefined ? 'GET' : 'POST', cache: 'no-store',
      headers: {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': csrf, ...(body === undefined ? {} : {'Content-Type': 'application/json'})},
      ...(body === undefined ? {} : {body: JSON.stringify(body)})});
    if (response.redirected || response.status === 401) throw new Error('Votre session a expiré. Reconnectez-vous à l’administration.');
    const data = await response.json().catch(() => null);
    if (!response.ok || !data?.success) throw new Error(data?.message || 'Le serveur ne peut pas terminer cette opération pour le moment.');
    return data;
  }
  function setBusy(busy) {
    pending = busy;
    document.querySelectorAll('[data-maintenance-check], [data-maintenance-action], #mt-refresh').forEach(button => {
      button.disabled = busy || (!!button.dataset.maintenanceAction && root.dataset.canManage !== 'true');
    });
    document.querySelectorAll('.mt-dialog').forEach(dialog => dialog.setAttribute('aria-busy', String(busy)));
  }
  async function execute(url, body, message) {
    if (pending) return;
    setBusy(true);
    text('mt-feedback', message);
    const dialog = document.querySelector('.mt-dialog[open]');
    if (dialog) dialog.querySelector('[data-dialog-feedback]').textContent = message;
    try {
      const data = await request(url, body);
      if (data.snapshot) render(data.snapshot);
      if (data.message) feedback(data.message);
      else text('mt-feedback', 'État actualisé.');
    } catch (error) { feedback(error.message || 'Connexion momentanément indisponible.', true); }
    finally { setBusy(false); }
  }
  async function inventory() {
    text('mt-temporary-count', 'Vérification des fichiers…');
    try {
      const data = await request(root.dataset.temporaryUrl);
      text('mt-temporary-count', `${data.count} fichier(s) éligible(s) · ${(data.bytes / 1024).toFixed(1)} Ko (maximum ${data.limit} par nettoyage).`);
    } catch (error) { text('mt-temporary-count', error.message || 'Inventaire indisponible.'); }
  }
  document.querySelectorAll('[data-open-maintenance]').forEach(button => button.addEventListener('click', () => {
    $(`mt-dialog-${button.dataset.openMaintenance}`).showModal();
    if (button.dataset.openMaintenance === 'operations') void inventory();
  }));
  document.querySelectorAll('[data-close-maintenance]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
  document.querySelectorAll('[data-maintenance-check]').forEach(button => button.addEventListener('click', () => {
    void execute(button.dataset.url, {}, button.dataset.maintenanceCheck === 'ai' ? 'Test du modèle en cours…' : 'Vérification en cours…');
  }));
  document.querySelectorAll('[data-maintenance-action]').forEach(button => button.addEventListener('click', async () => {
    if (pending || !snapshot) return;
    const action = button.dataset.maintenanceAction;
    const enabled = !snapshot.mode.enabled;
    const messages = {
      cache: 'Recharger les données du catalogue et des barèmes lors des prochains calculs ?',
      cleanup: 'Supprimer les fichiers temporaires éligibles de plus de 24 heures ? Les documents et sauvegardes sont conservés.',
      mode: enabled ? 'Mettre le site et l’application en maintenance pour les clients ? Les administrateurs garderont leur accès.' : 'Rouvrir le site et l’application aux clients ?',
    };
    const confirmed = await window.confirmAdminAction({title: 'Confirmer l’intervention', message: messages[action], confirmText: 'Confirmer', danger: action === 'cleanup' || (action === 'mode' && enabled)});
    if (!confirmed) return;
    await execute(button.dataset.url, {confirmed: true, ...(action === 'mode' ? {enabled} : {})}, 'Intervention en cours…');
    if (action === 'cleanup') void inventory();
  }));
  $('mt-refresh').addEventListener('click', () => void execute(root.dataset.snapshotUrl, undefined, 'Actualisation…'));
  void execute(root.dataset.snapshotUrl, undefined, 'Lecture des indicateurs…');
})();
