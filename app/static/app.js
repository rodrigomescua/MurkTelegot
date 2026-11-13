'use strict';

const primaryNavigation = document.querySelector('.primary-navigation');
if (primaryNavigation) {
  const toggle = document.querySelector('.nav-toggle');
  const menu = primaryNavigation.querySelector('#main-nav');
  const compactNavigation = window.matchMedia('(max-width: 850px)');
  const setNavigation = (expanded) => {
    toggle.setAttribute('aria-expanded', String(expanded));
    toggle.setAttribute('aria-label', expanded ? 'Fechar navegação' : 'Abrir navegação');
    menu.hidden = compactNavigation.matches && !expanded;
  };
  primaryNavigation.classList.add('nav-enhanced');
  document.querySelector('header').classList.add('navigation-enhanced');
  setNavigation(!compactNavigation.matches);
  toggle.addEventListener('click', () => setNavigation(toggle.getAttribute('aria-expanded') !== 'true'));
  menu.addEventListener('click', (event) => {
    if (compactNavigation.matches && event.target.closest('a')) setNavigation(false);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && compactNavigation.matches && toggle.getAttribute('aria-expanded') === 'true') {
      setNavigation(false);
      toggle.focus();
    }
  });
  compactNavigation.addEventListener('change', () => setNavigation(!compactNavigation.matches));
}

function updateUnreadCounter(value) {
  if (!Number.isFinite(value)) return;
  const counter = document.querySelector('#alert-counter strong');
  if (!counter) return;
  counter.textContent = value;
  counter.closest('a')?.setAttribute('aria-label', `${value} alertas não lidos`);
}

if (document.querySelector('#alert-counter strong')) {
  const refreshUnreadCount = async () => {
    try {
      const response = await fetch('/alerts/unread-count', {credentials: 'same-origin'});
      if (!response.ok) return;
      const result = await response.json();
      updateUnreadCounter(result.unread);
    } catch { /* Keep the last known count when offline. */ }
  };
  window.setInterval(refreshUnreadCount, 30000);
}

// Login failures keep the current DOM: secrets never need to be stored or echoed by the server.
document.addEventListener('submit', async (event) => {
  const form = event.target;
  if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
    event.preventDefault();
    return;
  }
  if (form.matches('[data-inactivate-coupon]')) {
    event.preventDefault();
    if (form.dataset.busy) return;
    form.dataset.busy = 'true';
    const button = event.submitter || form.querySelector('button');
    button.disabled = true;
    try {
      const response = await fetch(form.action, {
        method: 'POST', body: new FormData(form), headers: {Accept: 'application/json'}, credentials: 'same-origin',
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) throw new Error(result.message || 'Não foi possível inativar o cupom.');
      const status = form.closest('.coupon-card').querySelector('.coupon-status');
      status.textContent = 'Inativo';
      form.remove();
      status.focus();
      toast(result.message);
    } catch (error) {
      toast(error.message || 'Não foi possível confirmar a operação. Tente novamente.', true);
      button.disabled = false;
      delete form.dataset.busy;
      return;
    }
    delete form.dataset.busy;
    return;
  }
  if (!form.matches('[data-telegram]')) return;
  event.preventDefault();
  const panel = document.querySelector('#telegram-panel');
  if (panel.getAttribute('aria-busy') === 'true') return;
  const data = new FormData(form);
  const button = event.submitter || form.querySelector('button');
  const label = button.textContent;
  const buttons = [...panel.querySelectorAll('button')];
  buttons.forEach((item) => { item.disabled = true; });
  panel.setAttribute('aria-busy', 'true');
  button.textContent = 'Aguarde…';
  const status = document.querySelector('#action-status');
  status.hidden = false;
  status.classList.remove('error');
  status.textContent = 'Conectando ao Telegram. Aguarde…';
  try {
    const response = await fetch(form.action, {
      method: 'POST', body: data, headers: { Accept: 'application/json' }, credentials: 'same-origin',
    });
    const result = await response.json();
    if (response.ok && result.ok) {
      panel.outerHTML = result.html;
      const guidance = document.querySelector('#connect-guidance');
      if (result.connected && guidance) {
        guidance.innerHTML = '<h2>Conta conectada!</h2><p>Escolha os grupos e canais que deseja acompanhar para começar a receber ofertas.</p><a class="button" href="/groups">Selecionar grupos</a>';
      }
      const target = document.querySelector('#telegram-panel [data-autofocus]');
      if (target) target.focus();
    } else {
      status.classList.add('error');
      status.focus();
    }
    toast(result.message || (typeof result.detail === 'string' ? result.detail : 'Não foi possível concluir. Confira os dados e tente novamente.'), !response.ok || !result.ok);
  } catch {
    status.classList.add('error');
    status.textContent = 'Não foi possível confirmar a operação. Seus campos foram mantidos. Confira a conexão e tente novamente.';
    status.focus();
  } finally {
    buttons.forEach((item) => { item.disabled = false; });
    panel.removeAttribute('aria-busy');
    button.textContent = label;
  }
});

const groupsForm = document.querySelector('#groups-form');
if (groupsForm && groupsForm.querySelector('.check')) {
  const rows = [...groupsForm.querySelectorAll('.check')];
  const search = document.querySelector('#group-search');
  const normalize = (text) => text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
  const selection = () => rows.filter((row) => row.querySelector('input').checked).map((row) => row.querySelector('input').value).join(',');
  const initial = selection();
  const dirty = () => selection() !== initial;
  let submitting = false;
  function update() {
    const term = normalize(search.value.trim());
    rows.forEach((row) => { row.hidden = !normalize(row.textContent).includes(term); });
    const visible = rows.filter((row) => !row.hidden).length;
    const checked = rows.filter((row) => row.querySelector('input').checked).length;
    document.querySelector('#group-count').textContent = `${checked} de ${rows.length} selecionados · ${visible} visíveis`;
    document.querySelector('#no-groups').hidden = visible !== 0;
    document.querySelector('#selection-status').textContent = dirty() ? 'Alterações pendentes. Clique em Salvar seleção para aplicar.' : 'Seleção salva.';
  }
  document.querySelector('.group-tools').hidden = false;
  search.addEventListener('input', update);
  groupsForm.addEventListener('change', update);
  for (const [id, checked] of [['select-visible', true], ['clear-visible', false]]) {
    document.getElementById(id).addEventListener('click', () => {
      rows.filter((row) => !row.hidden).forEach((row) => { row.querySelector('input').checked = checked; });
      update();
    });
  }
  groupsForm.addEventListener('submit', () => {
    submitting = true;
    const button = groupsForm.querySelector('button:not([type="button"])');
    button.disabled = true;
    button.textContent = 'Salvando…';
  });
  window.addEventListener('beforeunload', (event) => {
    if (dirty() && !submitting) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
  update();
}

function formatTimes(root) {
for (const time of root.querySelectorAll('time[datetime]')) {
  const date = new Date(time.dateTime);
  if (!Number.isNaN(date.getTime())) {
    time.textContent = new Intl.DateTimeFormat('pt-BR', time.hasAttribute('data-date-only')
      ? { dateStyle: 'short' }
      : { dateStyle: 'short', timeStyle: 'short' }).format(date);
    if (!time.hasAttribute('data-date-only')) time.title = 'Horário local do seu navegador';
  }
}

}
formatTimes(document);

function toggleSpoiler(target) {
  const revealed = target.classList.toggle('revealed');
  target.setAttribute('aria-expanded', String(revealed));
  target.setAttribute('aria-label', revealed ? 'Ocultar spoiler' : 'Revelar spoiler');
}
document.addEventListener('click', (event) => {
  const spoiler = event.target.closest('.spoiler');
  if (spoiler) {
    event.preventDefault();
    toggleSpoiler(spoiler);
  }
});
document.addEventListener('keydown', (event) => {
  if (event.target.matches('.spoiler') && ['Enter', ' '].includes(event.key)) {
    event.preventDefault();
    toggleSpoiler(event.target);
  }
});
document.addEventListener('error', (event) => {
  if (event.target.matches?.('[data-message-media], .message-video, .message-video source, .message-audio')) {
    const help = event.target.closest('.message-part').querySelector('.media-help');
    if (help) help.hidden = false;
  }
}, true);

document.addEventListener('submit', (event) => {
  if (event.target.matches('form[action$="/refresh"]')) {
    const button = event.target.querySelector('button');
    button.disabled = true;
    button.textContent = 'Recuperando…';
  }
});

// Details remains usable without JavaScript; with JavaScript its content opens in a native modal.
const offerModal = document.createElement('dialog');
offerModal.className = 'offer-modal';
offerModal.setAttribute('aria-labelledby', 'offer-modal-title');
offerModal.innerHTML = '<div class="modal-heading"><h2 id="offer-modal-title"></h2><button type="button" class="secondary modal-close" aria-label="Fechar oferta">Fechar ✕</button></div><div class="modal-content"></div>';
document.body.append(offerModal);
let modalDetail;
let modalTrigger;
let extractionPoll;
function renderExtractionState(form, state) {
  const status = form.querySelector('[data-extraction-status]');
  const button = form.querySelector('button');
  const labels = {idle: 'Aguardando início.', queued: 'Na fila…', processing: 'Extraindo…', succeeded: 'Extração concluída.', failed: 'Falha na extração.'};
  status.textContent = state.message || labels[state.status] || 'Estado desconhecido.';
  button.disabled = state.status === 'queued' || state.status === 'processing';
  if (state.status === 'succeeded' && state.extraction) {
    let section = form.parentElement.querySelector('.ai-extraction-data');
    if (!section) {
      section = document.createElement('section');
      section.className = 'ai-extraction-data';
      section.innerHTML = '<h3>Dados retornados pela IA</h3><pre><code></code></pre>';
      form.after(section);
    }
    section.querySelector('pre code').textContent = JSON.stringify(state.extraction, null, 2);
  }
}
async function pollExtraction(form) {
  const url = `/offers/${encodeURIComponent(form.action.split('/').at(-2))}/extraction-status`;
  try {
    const response = await fetch(url, {credentials: 'same-origin', headers: {Accept: 'application/json'}});
    if (!response.ok) throw new Error();
    const state = await response.json();
    renderExtractionState(form, state);
    if (offerModal.open && (state.status === 'queued' || state.status === 'processing')) extractionPoll = setTimeout(() => pollExtraction(form), 1500);
  } catch { form.querySelector('[data-extraction-status]').textContent = 'Não foi possível consultar o estado da extração.'; }
}
offerModal.addEventListener('submit', async (event) => {
  const form = event.target.closest('[data-reextract]');
  if (!form) return;
  event.preventDefault();
  if (form.dataset.busy) return;
  form.dataset.busy = 'true';
  const button = form.querySelector('button');
  button.disabled = true;
  form.querySelector('[data-extraction-status]').textContent = 'Enviando…';
  try {
    const response = await fetch(form.action, {method: 'POST', body: new FormData(form), credentials: 'same-origin', headers: {Accept: 'application/json'}});
    const result = await response.json();
    if (!response.ok || result.ok === false) throw new Error(result.message || 'Não foi possível iniciar a extração.');
    await pollExtraction(form);
  } catch (error) {
    button.disabled = false;
    form.querySelector('[data-extraction-status]').textContent = error.message || 'Não foi possível iniciar a extração.';
  } finally { delete form.dataset.busy; }
});
function showOffer(detail, trigger) {
  if (offerModal.open) return;
  modalDetail = detail;
  modalTrigger = trigger || detail.closest('.offer-card').querySelector('.offer-open') || detail.querySelector('.offer-summary');
  offerModal.querySelector('#offer-modal-title').textContent = detail.querySelector('.meta strong').textContent;
  offerModal.querySelector('.modal-content').append(detail.querySelector('.offer-expanded'));
  offerModal.showModal();
  offerModal.querySelector('.modal-close').focus();
  const extractionForm = offerModal.querySelector('[data-reextract]');
  if (extractionForm) pollExtraction(extractionForm);
}
offerModal.querySelector('.modal-close').addEventListener('click', () => offerModal.close());
offerModal.addEventListener('click', (event) => {
  if (event.target === offerModal) {
    const rect = offerModal.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) offerModal.close();
  } else if (event.target.closest('.message-photo img')) {
    event.preventDefault();
  }
});
offerModal.addEventListener('close', () => {
  clearTimeout(extractionPoll);
  extractionPoll = null;
  const content = offerModal.querySelector('.offer-expanded');
  content.querySelectorAll('video, audio').forEach((media) => media.pause());
  modalDetail.append(content);
  if (modalTrigger.isConnected) modalTrigger.focus();
  const status = document.querySelector('#action-status');
  if (offerModal.contains(status)) document.querySelector('main').prepend(status);
});
function updateAlertSection(section, count) {
  section.querySelector('[data-alert-count]').textContent = count;
  let empty = section.querySelector('[data-alert-empty]');
  if (count === 0 && !empty) {
    empty = document.createElement('p');
    empty.className = 'muted';
    empty.dataset.alertEmpty = '';
    empty.textContent = section.dataset.alertSection === 'unread' ? 'Nenhum alerta não lido.' : 'Nenhum alerta lido.';
    section.querySelector('h2').after(empty);
  } else if (count > 0) empty?.remove();
}

async function handleOfferCardSubmit(event) {
  const form = event.target;
  const action = form.matches('[data-mark-seen]') ? 'seen' : form.matches('[data-delete-offer]') ? 'delete' : null;
  const undo = form.matches('[data-card-undo]');
  if (!action && !undo) return;
  let sequence = 0;
  const card = form.closest('.offer-card');
  if (!card) return;
  event.preventDefault();
  if (form.dataset.busy) return;
  if (action) sequence = ++cardActionSequence;
  form.dataset.busy = 'true';
  const button = event.submitter || form.querySelector('button');
  button.disabled = true;
  const overlay = card.querySelector('.offer-action-overlay');
  try {
    const response = await fetch(form.action, {method: 'POST', body: new FormData(form), headers: {Accept: 'application/json'}, credentials: 'same-origin'});
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.ok) throw new Error(result.message || 'Não foi possível atualizar o alerta. Tente novamente.');
    updateUnreadCounter(result.unread);
    const detail = card.querySelector('.offer-detail');
    const actions = card.querySelector('.offer-card-actions');
    if (undo) {
      card.classList.remove('offer-card-actioned');
      detail.inert = false;
      actions.inert = false;
      overlay.hidden = true;
      overlay.querySelector('strong').textContent = '';
      if (globalUndo?.dataset.card === `#${CSS.escape(card.id)}`) hideGlobalUndo();
      if (form.action.includes('/seen/undo') && document.querySelector('#feed[data-alerts="true"]')) {
        const unread = document.querySelector('[data-alert-section="unread"]');
        const read = document.querySelector('[data-alert-section="read"]');
        unread.querySelector('[data-alert-grid]').prepend(card);
        updateAlertSection(unread, Number(unread.querySelector('[data-alert-count]').textContent) + 1);
        updateAlertSection(read, Math.max(0, Number(read.querySelector('[data-alert-count]').textContent) - 1));
      }
      card.querySelector('.offer-open')?.focus({preventScroll: true});
    } else {
      const undoForm = overlay.querySelector('[data-card-undo]');
      undoForm.action = `${form.action}/undo`;
      detail.inert = true;
      actions.inert = true;
      card.classList.add('offer-card-actioned');
      overlay.querySelector('strong').textContent = action === 'seen' ? 'Alerta marcado como lido.' : 'Oferta excluída.';
      overlay.hidden = false;
      if (action === 'seen' && document.querySelector('#feed[data-alerts="true"]')) {
        const unread = document.querySelector('[data-alert-section="unread"]');
        const read = document.querySelector('[data-alert-section="read"]');
        read.querySelector('[data-alert-grid]').append(card);
        updateAlertSection(unread, Math.max(0, Number(unread.querySelector('[data-alert-count]').textContent) - 1));
        updateAlertSection(read, Number(read.querySelector('[data-alert-count]').textContent) + 1);
      }
      if (action === 'delete' && card.parentElement.matches('.offer-grid')) card.parentElement.append(card);
      if (sequence > globalUndoSequence) {
        globalUndoSequence = sequence;
        showGlobalUndo(card, action === 'seen' ? 'Alerta marcado como lido.' : 'Oferta excluída.');
        globalUndo?.focus({preventScroll: true});
      }
    }
  } catch (error) {
    const message = error.message || 'Não foi possível confirmar a operação. Tente novamente.';
    toast(message, true);
  } finally {
    delete form.dataset.busy;
    button.disabled = false;
  }
}
let cardActionSequence = 0;
let globalUndoSequence = 0;
const globalUndo = document.querySelector('[data-global-undo]');
function hideGlobalUndo() {
  if (!globalUndo) return;
  clearTimeout(globalUndo.undoTimer);
  globalUndo.hidden = true;
  globalUndo.removeAttribute('data-card');
}
function showGlobalUndo(card, message) {
  if (!globalUndo) return;
  clearTimeout(globalUndo.undoTimer);
  globalUndo.dataset.card = `#${CSS.escape(card.id)}`;
  globalUndo.querySelector('span').textContent = `${message} Desfazer`;
  globalUndo.hidden = false;
  globalUndo.undoTimer = setTimeout(hideGlobalUndo, 5000);
}
document.addEventListener('click', (event) => {
  if (!event.target.closest('[data-global-undo]')) return;
  const card = document.querySelector(globalUndo.dataset.card);
  const form = card?.querySelector('[data-card-undo]');
  if (form) form.requestSubmit();
});
document.addEventListener('click', (event) => {
  const summary = event.target.closest('.offer-summary');
  if (!summary) return;
  event.preventDefault();
});
document.querySelectorAll('.offer-open').forEach((button) => {
  button.hidden = false;
  const summary = button.closest('.offer-card').querySelector('.offer-summary');
  summary.tabIndex = -1;
  summary.classList.add('offer-summary-static');
});
document.addEventListener('click', (event) => {
  const button = event.target.closest('.offer-open');
  if (button) showOffer(button.closest('.offer-card').querySelector('.offer-detail'), button);
});

// Reopen the relevant offer or settings menu when following its anchor.
function openAnchor() {
  if (!location.hash) return;
  const rawId = location.hash.slice(1);
  let id = rawId;
  try { id = decodeURIComponent(rawId); } catch {}
  const target = document.getElementById(id);
  if (target?.matches('#ignored-menu')) target.open = true;
  const detail = target?.matches('.offer-card') ? target.querySelector('.offer-detail') : target?.closest('.offer-detail');
  if (detail) {
    showOffer(detail);
    if (target !== detail.closest('.offer-card')) requestAnimationFrame(() => target.scrollIntoView({block: 'nearest'}));
  }
}
window.addEventListener('hashchange', openAnchor);
openAnchor();
document.addEventListener('error', (event) => {
  if (event.target.matches?.('[data-offer-cover]')) {
    event.target.hidden = true;
    event.target.parentElement.querySelector('.offer-placeholder').hidden = false;
  }
}, true);

// An image may fail before the deferred script attaches its error listener.
function checkCovers(root) {
for (const cover of root.querySelectorAll('[data-offer-cover]')) {
  if (cover.complete && !cover.naturalWidth) {
    cover.hidden = true;
    cover.parentElement.querySelector('.offer-placeholder').hidden = false;
  }
}

}
checkCovers(document);

function toast(message, error = false) {
  const item = document.querySelector('#action-status');
  item.textContent = message;
  item.hidden = false;
  item.classList.toggle('error', error);
  clearTimeout(item.toastTimer);
  item.toastTimer = setTimeout(() => { item.hidden = true; }, 5000);
}
const initialToast = document.querySelector('[data-toast]');
if (initialToast) setTimeout(() => initialToast.remove(), 5000);

// Keep the rest of the dashboard, including unfinished forms, intact.
const feed = document.querySelector('#feed');
if (feed) {
  let marker = Number(feed.dataset.marker);
  let busy = false;
  let generation = 0;
  const status = document.querySelector('#new-offers-status');
  const updateButton = document.querySelector('#new-offers');
  const query = new URLSearchParams({q: feed.dataset.q, alerts: feed.dataset.alerts});
  async function poll() {
    const current = generation;
    try {
      const response = await fetch(`/offers/new?${query}&after=${marker}`, {credentials: 'same-origin'});
      if (!response.ok) throw new Error();
      const {count} = await response.json();
      if (current !== generation) return;
      status.hidden = !count;
      updateButton.disabled = false;
      status.classList.remove('error');
      updateButton.textContent = count ? `${count} ${count === 1 ? 'nova oferta disponível' : 'novas ofertas disponíveis'}. Clique aqui para atualizar.` : '';
    } catch {
      if (current !== generation) return;
      status.hidden = false;
      updateButton.disabled = true;
      status.classList.add('error');
      updateButton.textContent = 'Não foi possível verificar novas ofertas. A próxima tentativa será automática.';
    }
  }
  function applyPage(doc) {
    const next = doc.querySelector('#feed');
    if (!next) throw new Error();
    feed.innerHTML = next.innerHTML;
    marker = Number(next.dataset.marker);
    generation++;
    const counter = document.querySelector('#alert-counter');
    counter.innerHTML = doc.querySelector('#alert-counter').innerHTML;
    updateUnreadCounter(Number(counter.querySelector('strong').textContent));
    status.hidden = true;
    formatTimes(feed);
    checkCovers(feed);
  }
  async function loadPage(response) {
    if (!response.ok) throw new Error();
    const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
    applyPage(doc);
    return doc;
  }
  async function refreshFeed() {
    if (busy) return;
    busy = true;
    try {
      await loadPage(await fetch(`${feed.dataset.alerts === 'true' ? '/alerts' : '/'}?${query}`, {credentials: 'same-origin'}));
      await poll();
    } catch { toast('Não foi possível atualizar a lista. Tente novamente.', true); }
    finally { busy = false; }
  }
  updateButton.addEventListener('click', refreshFeed);
  setInterval(poll, 30000);
}
document.addEventListener('submit', handleOfferCardSubmit);


const ignoredSettings = document.querySelector('#ignored-settings');
const irrelevantDialog = document.querySelector('#irrelevant-dialog');
if (irrelevantDialog?.dataset.open === 'true') irrelevantDialog.showModal();
document.querySelector('#close-irrelevant')?.addEventListener('click', () => irrelevantDialog?.close());
function filterRules(ruleSearch) {
  if (!ruleSearch) return;
  const rows = [...document.querySelectorAll('.rule-item')];
  const noResults = document.querySelector('#rules-no-results');
  const normalize = (text) => text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
  const term = normalize(ruleSearch.value.trim());
  const visible = rows.filter((row) => {
    row.hidden = !normalize(row.dataset.term).includes(term);
    return !row.hidden;
  }).length;
  const count = document.querySelector('#rule-count');
  if (count) count.textContent = `${rows.length} regras cadastradas · ${visible} visíveis`;
  if (noResults) noResults.hidden = visible !== 0;
}
document.addEventListener('input', (event) => {
  if (event.target.id === 'rule-search') filterRules(event.target);
});
filterRules(document.querySelector('#rule-search'));
document.querySelectorAll('.ignored-auto-delete-form [data-ignored-save]').forEach((button) => { button.hidden = true; });
document.addEventListener('click', (event) => {
  const button = event.target.closest('.sortable-table [data-sort]');
  if (!button) return;
  const table = button.closest('.sortable-table');
  const column = button.closest('th').cellIndex;
  const direction = button.getAttribute('aria-sort') === 'ascending' ? 'desc' : 'asc';
  const multiplier = direction === 'asc' ? 1 : -1;
  const rows = [...table.tBodies[0].rows];
  rows.sort((a, b) => {
    const left = a.cells[column].dataset.value ?? a.cells[column].textContent.trim();
    const right = b.cells[column].dataset.value ?? b.cells[column].textContent.trim();
    return (button.dataset.sort === 'date' ? Date.parse(left) - Date.parse(right) : left.localeCompare(right, 'pt-BR', {sensitivity: 'base'})) * multiplier;
  });
  table.tBodies[0].append(...rows);
  table.querySelectorAll('[data-sort]').forEach((header) => {
    header.removeAttribute('aria-sort');
    header.querySelector('[aria-hidden="true"]').textContent = '↕';
  });
  button.setAttribute('aria-sort', direction === 'asc' ? 'ascending' : 'descending');
  button.querySelector('[aria-hidden="true"]').textContent = direction === 'asc' ? '↑' : '↓';
});
async function updateRulesList() {
  const list = document.querySelector('#rules-list');
  if (!list) return;
  const search = list.querySelector('#rule-search').value;
  const response = await fetch('/rules-page', {credentials: 'same-origin'});
  if (!response.ok || response.redirected) throw new Error();
  const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
  const next = doc.querySelector('#rules-list');
  if (!next) throw new Error();
  list.innerHTML = next.innerHTML;
  const searchInput = list.querySelector('#rule-search');
  searchInput.value = search;
  filterRules(searchInput);
}
async function updateIgnoredList() {
  if (!ignoredSettings) return;
  const search = document.querySelector('#ignored-search').value;
  const page = document.querySelector('.ignored-auto-delete-form [name="page"]')?.value || 1;
  const response = await fetch(`/ignored?q=${encodeURIComponent(search)}&page=${encodeURIComponent(page)}`, {credentials: 'same-origin'});
  if (!response.ok || response.redirected) throw new Error();
  const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
  const next = doc.querySelector('#ignored-management');
  if (!next) throw new Error();
  document.querySelector('#ignored-management').innerHTML = next.innerHTML;
  document.querySelector('#ignored-search').value = search;
  document.querySelectorAll('.ignored-auto-delete-form [data-ignored-save]').forEach((button) => { button.hidden = true; });
}
async function submitQuick(form, button) {
  const focusId = form.matches('.ignored-auto-delete-form')
    ? form.querySelector('input[type="checkbox"][name="enabled"]')?.id : null;
  button.disabled = true;
  try {
    const response = await fetch(form.action, {method: 'POST', body: new FormData(form), headers: {Accept: 'application/json'}, credentials: 'same-origin'});
    const result = await response.json();
    if (!response.ok || !result.ok) {
      const error = form.querySelector('.quick-error');
      if (error) { error.hidden = false; error.textContent = result.message || 'Não foi possível salvar.'; }
      else toast(result.message || 'Não foi possível salvar.', true);
      return;
    }
    const dialog = form.closest('dialog');
    if (dialog) dialog.close();
    if (form.matches('[action="/ignored"], [action="/rules"]')) form.reset();
    toast(result.message);
    try {
      if (form.action.endsWith('/ignored') || form.action.includes('/ignored/')) {
        await updateIgnoredList();
        if (focusId) document.getElementById(focusId)?.focus();
        await refreshTerms();
        document.querySelector('#refresh-feed')?.click();
      }
      if (form.action.endsWith('/rules') && document.querySelector('#rules-list')) {
        await updateRulesList();
      }
    } catch { toast('Alteração salva, mas não foi possível atualizar a tela. Recarregue para conferir.', true); }
  } catch { toast('Não foi possível confirmar a operação. Confira a conexão e o resultado antes de tentar novamente.', true); }
  finally { button.disabled = false; }
}
document.querySelectorAll('[data-quick]').forEach((link) => {
  link.addEventListener('click', (event) => {
    const dialog = document.getElementById(link.dataset.quick);
    if (!dialog?.showModal) return;
    event.preventDefault();
    dialog.querySelector('.quick-error').hidden = true;
    dialog.showModal();
    dialog.querySelector('input:not([type="hidden"])').focus();
  });
});
document.querySelectorAll('.quick-close').forEach((button) => button.addEventListener('click', () => button.closest('dialog').close()));
document.querySelectorAll('[data-quick-form]').forEach((form) => form.addEventListener('submit', (event) => {
  event.preventDefault();
  submitQuick(form, event.submitter || form.querySelector('button'));
}));
ignoredSettings?.addEventListener('submit', (event) => {
  if (event.target.method === 'get') return;
  event.preventDefault();
  submitQuick(event.target, event.submitter || event.target.querySelector('button'));
});
ignoredSettings?.addEventListener('change', (event) => {
  if (!event.target.matches('.ignored-auto-delete-form input[name="enabled"][type="checkbox"]')) return;
  const form = event.target.form;
  submitQuick(form, form.querySelector('[data-ignored-save]'));
});

const termsContent = document.querySelector('#terms-content');
function updateTermSelection() {
  if (!termsContent) return;
  const boxes = [...termsContent.querySelectorAll('input[name="words"]')];
  const count = boxes.filter((box) => box.checked).length;
  const selectAll = termsContent.querySelector('#terms-select-all');
  if (!selectAll) return;
  selectAll.parentElement.hidden = false;
  selectAll.checked = count === boxes.length && count > 0;
  selectAll.indeterminate = count > 0 && count < boxes.length;
  document.querySelector('#terms-selected-count').textContent = `${count} ${count === 1 ? 'termo selecionado' : 'termos selecionados'} nesta página`;
}
termsContent?.addEventListener('change', (event) => {
  if (event.target.id === 'terms-select-all') {
    termsContent.querySelectorAll('input[name="words"]').forEach((box) => { box.checked = event.target.checked; });
  }
  if (event.target.id === 'terms-select-all' || event.target.name === 'words') updateTermSelection();
});
updateTermSelection();
async function refreshTerms() {
  if (!termsContent) return;
  const selected = new Set([...termsContent.querySelectorAll('input[name="words"]:checked')].map((box) => box.value));
  const opened = document.querySelector('#hidden-terms').open;
  const response = await fetch(`/terms?page=${encodeURIComponent(termsContent.dataset.page)}`, {credentials: 'same-origin'});
  if (!response.ok || response.redirected) throw new Error();
  const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
  const next = doc.querySelector('#terms-content');
  if (!next) throw new Error();
  termsContent.innerHTML = next.innerHTML;
  termsContent.dataset.page = next.dataset.page;
  document.querySelector('#hidden-terms').open = opened;
  termsContent.querySelectorAll('input[name="words"]').forEach((box) => { box.checked = selected.has(box.value); });
  updateTermSelection();
}
termsContent?.addEventListener('submit', async (event) => {
  const form = event.target;
  if (!form.matches('[data-term-action]')) return;
  event.preventDefault();
  const button = event.submitter || form.querySelector('button');
  const data = new FormData(form, button);
  if (form.matches('[data-term-batch]') && !data.getAll('words').length) {
    toast('Selecione pelo menos um termo desta página.', true);
    return;
  }
  const controls = [...termsContent.querySelectorAll('button, input[type="checkbox"]')];
  controls.forEach((item) => { item.disabled = true; });
  let saved = false;
  try {
    const response = await fetch(form.getAttribute('action'), {method: 'POST', body: data, headers: {Accept: 'application/json'}, credentials: 'same-origin'});
    const result = await response.json();
    if (!response.ok || !result.ok) { toast(result.message || 'Não foi possível salvar.', true); return; }
    saved = true;
    if (form.matches('[data-term-batch]')) form.reset();
    await refreshTerms();
    toast(result.message);
  } catch {
    toast(saved ? 'Alteração salva, mas não foi possível atualizar a lista. Recarregue a página.' : 'Não foi possível confirmar a operação. Atualize a página para conferir.', true);
  } finally { controls.forEach((item) => { item.disabled = false; }); }
});

// Selection actions are progressive: native text selection and the existing forms remain available.
const selectionBar = document.createElement('div');
selectionBar.className = 'selection-actions';
selectionBar.setAttribute('role', 'toolbar');
selectionBar.setAttribute('aria-label', 'Ações para o texto selecionado');
selectionBar.hidden = true;
selectionBar.innerHTML = '<button type="button" data-selection-action="rule">Criar alerta</button><button type="button" data-selection-action="ignore">Ignorar ofertas</button><label class="check"><input type="checkbox" data-selection-auto-delete> Excluir permanentemente correspondentes, inclusive ofertas existentes</label><span class="selection-help" role="status" hidden></span>';
document.body.append(selectionBar);
let selectedText = '';
let lastRenderedSelection = '';
let selectionTimer;
let selectingAction = false;
let selectionBusy = false;
function selectionToast(message, error = false) {
  const status = document.querySelector('#action-status');
  const dialog = document.querySelector('dialog.offer-modal[open]');
  if (dialog) dialog.append(status);
  toast(message, error);
}
function updateSelectionActions() {
  if (selectingAction || selectionBar.contains(document.activeElement)) return;
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || !selection.rangeCount) { selectionBar.hidden = true; return; }
  const range = selection.getRangeAt(0);
  const element = range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE ? range.commonAncestorContainer : range.commonAncestorContainer.parentElement;
  const dialog = element?.closest('dialog');
  const allowed = element && (element.closest('main') || dialog?.matches('.offer-modal'));
  if (!allowed || (dialog && !dialog.matches('.offer-modal')) || element.closest('input, textarea, select, button, [contenteditable]') || element.isContentEditable ||
      [...document.querySelectorAll('.spoiler:not(.revealed)')].some((spoiler) => range.intersectsNode(spoiler))) {
    selectionBar.hidden = true;
    return;
  }
  selectedText = selection.toString().replace(/\s+/g, ' ').trim();
  if (!selectedText) { selectionBar.hidden = true; return; }
  if (selectedText !== lastRenderedSelection) selectionBar.querySelector('[data-selection-auto-delete]').checked = false;
  lastRenderedSelection = selectedText;
  (dialog || document.body).append(selectionBar);
  const rule = selectionBar.querySelector('[data-selection-action="rule"]');
  const ignored = selectionBar.querySelector('[data-selection-action="ignore"]');
  const help = selectionBar.querySelector('.selection-help');
  rule.disabled = selectedText.length > 100 || selectedText.includes(',');
  ignored.disabled = selectedText.length > 100;
  help.textContent = selectedText.length > 100 ? 'Selecione até 100 caracteres.' :
    (selectedText.includes(',') ? 'Para criar alerta, selecione um trecho sem vírgula.' : '');
  help.hidden = !help.textContent;
  selectionBar.hidden = false;
  const visible = [...range.getClientRects()].filter((rect) => rect.width && rect.height && rect.bottom > 0 && rect.top < innerHeight);
  const rect = visible[visible.length - 1] || range.getBoundingClientRect();
  const box = selectionBar.getBoundingClientRect();
  const left = Math.max(8, Math.min(innerWidth - box.width - 8, (rect.left + rect.right - box.width) / 2));
  const below = rect.bottom + 10;
  const top = below + box.height <= innerHeight - 8 ? below : Math.max(8, rect.top - box.height - 10);
  selectionBar.style.left = `${left}px`;
  selectionBar.style.top = `${top}px`;
}
document.addEventListener('selectionchange', () => {
  if (!selectingAction && !selectionBar.contains(document.activeElement)) {
    selectedText = '';
    selectionBar.hidden = true;
  }
  clearTimeout(selectionTimer);
  selectionTimer = setTimeout(updateSelectionActions, 150);
});
document.addEventListener('pointerdown', (event) => {
  if (selectionBar.contains(event.target)) {
    selectingAction = true;
    if (event.target.closest('button')) event.preventDefault();
  } else {
    selectingAction = false;
    selectionBar.hidden = true;
  }
}, true);
document.addEventListener('pointercancel', () => { selectingAction = false; });
selectionBar.addEventListener('focusout', () => setTimeout(() => {
  if (!selectionBar.contains(document.activeElement) && window.getSelection()?.isCollapsed) selectionBar.hidden = true;
}, 0));
selectionBar.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-selection-action]');
  if (!button || selectionBusy) return;
  const text = selectedText;
  const action = button.dataset.selectionAction;
  const csrf = document.querySelector('form[action="/logout"] input[name="csrf"]')?.value;
  if (!csrf || !text || text.length > 100 || (action === 'rule' && text.includes(','))) return;
  selectionBusy = true;
  selectionBar.querySelectorAll('button').forEach((item) => { item.disabled = true; });
  const data = new FormData();
  data.set('csrf', csrf);
  if (action === 'rule') data.set('keyword', text);
  else {
    data.set('word', text);
    if (selectionBar.querySelector('[data-selection-auto-delete]').checked) data.set('auto_delete', 'true');
  }
  let saved = false;
  try {
    const response = await fetch(action === 'rule' ? '/rules' : '/ignored', {
      method: 'POST', body: data, headers: {Accept: 'application/json'}, credentials: 'same-origin',
    });
    const result = await response.json();
    if (!response.ok || !result.ok) { selectionToast(result.message || (typeof result.detail === 'string' ? result.detail : 'Não foi possível salvar.'), true); return; }
    saved = true;
    selectionBar.hidden = true;
    window.getSelection()?.removeAllRanges();
    selectionToast(result.message);
    if (action === 'ignore') {
      await updateIgnoredList();
      await refreshTerms();
      document.querySelector('#refresh-feed')?.click();
    } else if (document.querySelector('#rules-list')) {
      await updateRulesList();
    }
  } catch {
    selectionToast(saved ? 'Alteração salva, mas não foi possível atualizar a tela. Recarregue para conferir.' :
      'Não foi possível confirmar a operação. Atualize a página para conferir.', true);
  } finally {
    selectionBusy = false;
    selectingAction = false;
    if (!selectionBar.hidden) updateSelectionActions();
  }
});
window.addEventListener('scroll', () => { if (!selectionBar.hidden && !selectingAction) updateSelectionActions(); }, true);
window.addEventListener('resize', () => { if (!selectionBar.hidden) updateSelectionActions(); });

// AI model catalog and priority controls progressively enhance the server-rendered form.
const aiForm = document.querySelector('#ai-settings-form');
const aiSettingsState = {dirty: false};
if (aiForm) {
  const orderField = aiForm.querySelector('#model-order');
  const priority = aiForm.querySelector('#model-priority-list');
  const priorityStatus = aiForm.querySelector('#priority-status');
  const providerNames = {openai: 'OpenAI', openrouter: 'OpenRouter'};
  const selectedModels = () => [...aiForm.querySelectorAll('[data-model-option] input:checked')];
  const updateModelPickerSummary = (provider) => {
    const count = aiForm.querySelectorAll(`input[name="models_${provider}"]:checked`).length;
    const summary = aiForm.querySelector(`[data-model-picker-summary="${provider}"]`);
    if (summary) summary.textContent = `${count} modelo${count === 1 ? '' : 's'} selecionado${count === 1 ? '' : 's'} · Abrir seletor`;
  };
  function syncPriority() {
    const selected = selectedModels();
    const keys = new Set(selected.map((input) => `${input.name.slice(7)}\0${input.value}`));
    [...priority.children].forEach((item) => {
      if (!keys.has(`${item.dataset.provider}\0${item.dataset.model}`)) item.remove();
    });
    selected.forEach((input) => {
      const provider = input.name.slice(7);
      const exists = [...priority.children].some((item) => item.dataset.provider === provider && item.dataset.model === input.value);
      if (exists) return;
      const item = document.createElement('li');
      item.dataset.priorityItem = '';
      item.dataset.provider = provider;
      item.dataset.model = input.value;
      const label = document.createElement('span');
      label.textContent = `${providerNames[provider]} · ${input.value}`;
      item.append(label);
      for (const [direction, text] of [['up', '↑'], ['down', '↓']]) {
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'secondary'; button.dataset.move = direction;
        button.setAttribute('aria-label', `Mover ${input.value} ${direction === 'up' ? 'para cima' : 'para baixo'}`);
        button.textContent = text; item.append(button);
      }
      priority.append(item);
    });
    orderField.value = JSON.stringify([...priority.children].map((item) => ({provider: item.dataset.provider, id: item.dataset.model})));
    [...priority.children].forEach((item, index, rows) => {
      item.querySelector('[data-move="up"]').disabled = index === 0;
      item.querySelector('[data-move="down"]').disabled = index === rows.length - 1;
    });
    priorityStatus.textContent = selected.length ? `${selected.length} modelo${selected.length === 1 ? '' : 's'} na ordem de uso.` : 'Selecione ao menos um modelo.';
    updateModelPickerSummary('openai'); updateModelPickerSummary('openrouter');
  }
  aiForm.addEventListener('change', (event) => {
    const checkbox = event.target.closest('[data-model-option] input');
    if (!checkbox) return;
    syncPriority();
  });
  priority.addEventListener('click', (event) => {
    const button = event.target.closest('[data-move]');
    if (!button) return;
    const item = button.closest('li');
    const neighbor = button.dataset.move === 'up' ? item.previousElementSibling : item.nextElementSibling;
    if (!neighbor) return;
    if (button.dataset.move === 'up') priority.insertBefore(item, neighbor);
    else priority.insertBefore(neighbor, item);
    orderField.value = JSON.stringify([...priority.children].map((row) => ({provider: row.dataset.provider, id: row.dataset.model})));
    [...priority.children].forEach((row, index, rows) => {
      row.querySelector('[data-move="up"]').disabled = index === 0;
      row.querySelector('[data-move="down"]').disabled = index === rows.length - 1;
    });
    priorityStatus.textContent = `${item.querySelector('span').textContent} movido ${button.dataset.move === 'up' ? 'para cima' : 'para baixo'}.`;
    aiForm.dispatchEvent(new Event('ai-order-change'));
    button.focus();
  });
  document.querySelectorAll('[data-model-filter]').forEach((filter) => filter.addEventListener('input', () => {
    const provider = filter.dataset.modelFilter;
    const term = filter.value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
    const rows = [...document.querySelectorAll(`[data-model-option][data-provider="${provider}"]`)];
    rows.forEach((row) => {
      row.hidden = !row.textContent.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR').includes(term);
    });
    const visible = rows.filter((row) => !row.hidden).length;
    const status = document.querySelector(`[data-model-status="${provider}"]`);
    if (filter.value && status) status.textContent = `${visible} modelo${visible === 1 ? '' : 's'} encontrado${visible === 1 ? '' : 's'}; ${aiForm.querySelectorAll(`input[name="models_${provider}"]:checked`).length} selecionados.`;
  }));
  document.querySelectorAll('[data-load-models]').forEach((button) => button.addEventListener('click', async () => {
    const provider = button.dataset.loadModels;
    const status = document.querySelector(`[data-model-status="${provider}"]`);
    const keyField = document.querySelector(`#${provider}-key`);
    const label = button.textContent;
    button.disabled = true; button.textContent = 'Carregando…';
    status.textContent = 'Consultando catálogo…';
    const data = new FormData();
    data.set('csrf', aiForm.querySelector('[name=csrf]').value);
    data.set('provider', provider);
    data.set('api_key', keyField.value);
    try {
      const response = await fetch('/settings/ai/models', {method: 'POST', body: data, headers: {Accept: 'application/json'}, credentials: 'same-origin'});
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.message || 'Não foi possível carregar os modelos.');
      const list = document.querySelector(`.ai-provider[data-provider="${provider}"] .model-list`);
      document.querySelector(`[data-model-picker="${provider}"]`).open = true;
      const existing = new Map([...list.querySelectorAll('[data-model-option] input')].map((input) => [input.value, input.checked]));
      list.querySelectorAll('[data-model-option], [data-model-empty]').forEach((item) => item.remove());
      result.models.forEach((model) => {
        const row = document.createElement('label'); row.className = 'check model-option'; row.dataset.modelOption = ''; row.dataset.provider = provider;
        const input = document.createElement('input'); input.type = 'checkbox'; input.name = `models_${provider}`; input.value = model.id; input.checked = existing.get(model.id) || false;
        const name = document.createElement('span'); name.textContent = model.name && model.name !== model.id ? `${model.name} (${model.id})` : model.id;
        row.append(input, name); list.append(row);
      });
      if (!result.models.length) {
        const empty = document.createElement('p'); empty.className = 'field-help'; empty.dataset.modelEmpty = '';
        empty.textContent = 'Nenhum modelo disponível para esta chave.'; list.append(empty);
      }
      document.querySelector(`#${provider}-filter`).dispatchEvent(new Event('input'));
      syncPriority(); status.textContent = `${result.models.length} modelos carregados.`;
    } catch (error) { status.textContent = error.message || 'Não foi possível carregar os modelos. Tente novamente.'; }
    finally { button.disabled = false; button.textContent = label; }
  }));
  syncPriority();
  const serializeSettings = () => JSON.stringify([...new FormData(aiForm).entries()].filter(([name]) => name !== 'csrf'));
  const savedSettings = serializeSettings();
  const updateDirty = () => {
    aiSettingsState.dirty = serializeSettings() !== savedSettings;
    document.dispatchEvent(new Event('ai-settings-dirty'));
  };
  aiForm.addEventListener('input', updateDirty);
  aiForm.addEventListener('change', updateDirty);
  aiForm.addEventListener('ai-order-change', updateDirty);
}

const aiJobForm = document.querySelector('[data-job-create]');
if (aiJobForm) {
  const countLabel = aiJobForm.querySelector('[data-job-count]');
  const button = aiJobForm.querySelector('button[type="submit"], button:not([type])');
  const help = aiJobForm.querySelector('[data-unsaved-help]');
  const updateJobChoice = () => {
    const replace = aiJobForm.querySelector('[name="replace_existing"]:checked')?.value === 'true';
    const count = Number(replace ? aiJobForm.dataset.countAll : aiJobForm.dataset.countMissing);
    countLabel.textContent = replace
      ? `${count} ofertas no feed padrão serão processadas; resultados existentes serão substituídos.`
      : `${count} ofertas sem extração entre as ${aiJobForm.dataset.countAll} exibidas no feed padrão da Home.`;
    aiJobForm.dataset.confirm = `Criar job para ${count} ofertas? O texto será enviado aos provedores selecionados e pode consumir créditos.`;
    if (button) button.disabled = count === 0 || aiJobForm.dataset.ready !== 'true' || aiSettingsState.dirty;
    if (help) help.textContent = aiSettingsState.dirty
      ? 'Há alterações de IA não salvas. Salve a configuração antes de enfileirar para usar os modelos selecionados.'
      : 'O job usa a configuração de IA salva. Salve qualquer alteração antes de enfileirar.';
  };
  aiJobForm.addEventListener('change', updateJobChoice);
  document.addEventListener('ai-settings-dirty', updateJobChoice);
  updateJobChoice();
}

const activeJobPanel = document.querySelector('[data-active-job]');
if (activeJobPanel) {
  let refreshingJobs = false;
  const jobStatusLabels = {queued: 'Na fila', running: 'Em andamento', cancelling: 'Cancelamento solicitado', cancelled: 'Cancelado', completed: 'Concluído', completed_with_errors: 'Concluído com falhas', failed: 'Com falhas'};
  const failureLabels = {authentication: 'autenticação/acesso', rate_limit: 'limite de uso', provider_http: 'HTTP do provedor', provider_timeout: 'timeout do provedor', provider_request: 'requisição recusada', model_not_found: 'modelo inexistente', network_tls: 'TLS', network_timeout: 'timeout de rede', network: 'rede', request_timeout: 'timeout da chamada', invalid_response: 'resposta inválida', internal: 'falha interna', legacy: 'histórica'};
  const renderModelMetrics = metrics => {
    const container = document.querySelector('[data-model-metrics]');
    if (!container) return;
    let grid = container.querySelector('.model-metric-grid');
    if (!metrics?.length) {
      grid?.remove();
      if (!container.querySelector('[data-metrics-empty]')) {
        const empty = document.createElement('p'); empty.className = 'field-help'; empty.dataset.metricsEmpty = '';
        empty.textContent = 'Ainda não há chamadas concluídas para medir.'; container.append(empty);
      }
      return;
    }
    container.querySelector('[data-metrics-empty]')?.remove();
    if (!grid) { grid = document.createElement('div'); grid.className = 'model-metric-grid'; container.append(grid); }
    grid.replaceChildren(...metrics.map(metric => {
      const card = document.createElement('article'); card.className = 'model-metric';
      const title = document.createElement('h3');
      title.textContent = `${metric.provider === 'openai' ? 'OpenAI' : metric.provider === 'openrouter' ? 'OpenRouter' : metric.provider} · ${metric.model}`;
      const total = Number(metric.total) || 0, succeeded = Number(metric.succeeded) || 0, failed = Number(metric.failed) || 0;
      const summary = document.createElement('p');
      summary.textContent = `${succeeded} sucessos (${(succeeded * 100 / total).toFixed(1)}%) · ${failed} falhas (${(failed * 100 / total).toFixed(1)}%)`;
      const duration = document.createElement('p');
      duration.textContent = `Tempo médio: ${(Number(metric.average_ms) / 1000).toFixed(1)} s · ${total} chamadas`;
      const failures = document.createElement('p');
      const kinds = Object.entries(metric.failures_by_type || {});
      failures.textContent = kinds.length ? `Falhas: ${kinds.map(([kind, count]) => `${failureLabels[kind] || kind} ${count} (${(count * 100 / total).toFixed(1)}%)`).join(' · ')}` : 'Falhas por tipo: nenhuma';
      card.append(title, summary, duration, failures);
      return card;
    }));
  };
  const updateJobProgress = async () => {
    if (refreshingJobs || document.visibilityState !== 'visible') return;
    refreshingJobs = true;
    try {
      const response = await fetch('/ai-jobs/status', {headers: {Accept: 'application/json'}, credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) throw new Error();
      const result = await response.json();
      const job = result.active_job;
      if (!job || String(job.id) !== activeJobPanel.dataset.activeJob) {
        window.location.reload();
        return;
      }
      const total = Number(job.total) || 0;
      const processed = Number(job.processed) || 0;
      const progress = activeJobPanel.querySelector('[data-active-progress]');
      const percent = total ? Math.round(processed / total * 100) : 0;
      progress.max = Math.max(total, 1); progress.value = processed;
      progress.setAttribute('aria-label', `Progresso do job: ${processed} de ${total} ofertas`);
      activeJobPanel.querySelector('[data-active-status]').textContent = jobStatusLabels[job.status] || 'Status atualizado';
      activeJobPanel.querySelector('[data-active-summary]').textContent = `${processed} de ${total} ofertas processadas · ${job.succeeded} concluídas · ${job.skipped} puladas · ${job.failed} com erro · ${job.cancelled} canceladas`;
      activeJobPanel.querySelector('[data-active-percent]').textContent = `${processed} de ${total} (${percent}%)`;
      const item = job.active_item;
      if (item) {
        const updated = Date.parse(item.stage_updated_at);
        const seconds = Number.isFinite(updated) ? Math.max(0, Math.floor((Date.now() - updated) / 1000)) : 0;
        const age = seconds < 60 ? `${seconds} s` : `${Math.floor(seconds / 60)} min`;
        activeJobPanel.querySelector('[data-active-stage]').textContent = `Oferta #${item.message_id} · ${item.stage || 'Preparando'} · nesta etapa há ${age}`;
      } else activeJobPanel.querySelector('[data-active-stage]').textContent = 'Aguardando próxima oferta';
      renderModelMetrics(result.model_metrics);
      const cancelForm = activeJobPanel.querySelector('[data-job-cancel]');
      if (cancelForm) cancelForm.hidden = !['queued', 'running'].includes(job.status);
      let cancelNotice = activeJobPanel.querySelector('[data-cancel-notice]');
      if (job.status === 'cancelling' && !cancelNotice) {
        cancelNotice = document.createElement('p'); cancelNotice.className = 'field-help'; cancelNotice.dataset.cancelNotice = ''; cancelNotice.setAttribute('role', 'status');
        cancelNotice.textContent = 'Conexão local interrompida. O provedor ainda pode continuar o processamento ou cobrar.';
        activeJobPanel.insertBefore(cancelNotice, activeJobPanel.querySelector('[data-active-progress]'));
      }
    } catch {
      activeJobPanel.querySelector('[data-active-summary]').textContent = 'Não foi possível atualizar agora. Tentando novamente…';
    } finally { refreshingJobs = false; }
  };
  window.setInterval(updateJobProgress, 2000);
}
