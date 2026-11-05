'use strict';

// Login failures keep the current DOM: secrets never need to be stored or echoed by the server.
document.addEventListener('submit', async (event) => {
  const form = event.target;
  if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
    event.preventDefault();
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
    time.textContent = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' }).format(date);
    time.title = 'Horário local do seu navegador';
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
let modalSummary;
let termOffersDialog;
let termOffersReturn = false;
let termOffersFocus;
let refreshTermOffers = () => Promise.resolve(false);
function showOffer(detail) {
  if (offerModal.open) return;
  if (termOffersDialog?.open) {
    termOffersReturn = true;
    termOffersFocus = detail.querySelector('.offer-summary');
    termOffersDialog.close();
  }
  modalDetail = detail;
  modalSummary = detail.querySelector('.offer-summary');
  offerModal.querySelector('#offer-modal-title').textContent = detail.querySelector('.meta strong').textContent;
  offerModal.querySelector('.modal-content').append(detail.querySelector('.offer-expanded'));
  offerModal.showModal();
  offerModal.querySelector('.modal-close').focus();
}
offerModal.querySelector('.modal-close').addEventListener('click', () => offerModal.close());
offerModal.addEventListener('close', () => {
  const content = offerModal.querySelector('.offer-expanded');
  content.querySelectorAll('video, audio').forEach((media) => media.pause());
  modalDetail.append(content);
  if (termOffersReturn && termOffersDialog) {
    termOffersReturn = false;
    termOffersDialog.showModal();
    if (termOffersFocus?.isConnected) termOffersFocus.focus();
    termOffersFocus = null;
  } else if (modalSummary.isConnected) modalSummary.focus();
  const status = document.querySelector('#action-status');
  if (offerModal.contains(status)) document.querySelector('main').prepend(status);
});

const termsPage = document.querySelector('#terms-content');
if (termsPage) {
  termOffersDialog = document.createElement('dialog');
  termOffersDialog.className = 'offer-modal term-offers-modal';
  termOffersDialog.setAttribute('aria-labelledby', 'term-offers-title');
  termOffersDialog.innerHTML = '<div class="modal-heading"><h2 id="term-offers-title"></h2><button type="button" class="secondary modal-close term-offers-close">Fechar ✕</button></div><p class="term-offers-status" role="status" aria-live="polite" hidden></p><div class="term-offers-body"></div>';
  document.body.append(termOffersDialog);
  const termTitle = termOffersDialog.querySelector('#term-offers-title');
  const termBody = termOffersDialog.querySelector('.term-offers-body');
  const termStatus = termOffersDialog.querySelector('.term-offers-status');
  let termTrigger;
  let termRequest = 0;
  let termCurrentUrl;
  let termActionBusy = false;
  termOffersDialog.querySelector('.term-offers-close').addEventListener('click', () => termOffersDialog.close());
  termOffersDialog.addEventListener('close', () => {
    if (!termOffersReturn) {
      if (termTrigger?.isConnected) termTrigger.focus();
      else document.querySelector('#terms-title')?.focus();
    }
    const status = document.querySelector('#action-status');
    if (termOffersDialog.contains(status)) document.querySelector('main').prepend(status);
  });
  async function loadTermOffers(url, initial = false) {
    const request = ++termRequest;
    termCurrentUrl = url;
    termStatus.hidden = false;
    termStatus.textContent = 'Carregando ofertas…';
    if (initial) termBody.replaceChildren();
    try {
      const response = await fetch(url, {credentials: 'same-origin'});
      if (!response.ok || response.redirected) throw new Error();
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      const source = doc.querySelector('#term-offers-content');
      const heading = doc.querySelector('main h1');
      if (!source || !heading) throw new Error();
      if (request !== termRequest) return false;
      termBody.replaceChildren(...source.childNodes);
      termTitle.textContent = heading.textContent;
      termStatus.hidden = true;
      formatTimes(termBody);
      checkCovers(termBody);
      return true;
    } catch {
      if (request !== termRequest) return false;
      termStatus.hidden = false;
      termStatus.textContent = 'Não foi possível carregar as ofertas. Tente novamente.';
      if (initial) termBody.innerHTML = '<button type="button" class="secondary term-offers-retry">Tentar novamente</button>';
      return false;
    }
  }
  refreshTermOffers = () => termOffersDialog.open ? loadTermOffers(termCurrentUrl) : Promise.resolve(false);
  document.addEventListener('click', (event) => {
    const link = event.target.closest('[data-term-offers]');
    if (!link || !termsPage.contains(link)) return;
    if (!termOffersDialog.showModal) return;
    event.preventDefault();
    termTrigger = link;
    termTitle.textContent = link.closest('li')?.querySelector('.term-label strong')?.textContent || '';
    termOffersDialog.showModal();
    loadTermOffers(link.href, true);
  });
  termOffersDialog.addEventListener('click', (event) => {
    if (event.target.closest('.term-offers-retry')) {
      loadTermOffers(termTrigger.href, true);
      return;
    }
    const link = event.target.closest('.terms-pagination a');
    if (!link) return;
    event.preventDefault();
    loadTermOffers(link.href);
    termOffersDialog.querySelector('.modal-heading').scrollIntoView({block: 'nearest'});
  });
  termBody.addEventListener('submit', async (event) => {
    const form = event.target;
    if (!form.matches('[data-mark-seen]')) return;
    event.preventDefault();
    if (termActionBusy) return;
    termActionBusy = true;
    const button = event.submitter || form.querySelector('button');
    const cardId = form.closest('.offer-card').id;
    button.disabled = true;
    let saved = false;
    try {
      const response = await fetch(form.action, {method: 'POST', body: new FormData(form), headers: {Accept: 'application/json'}, credentials: 'same-origin'});
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) throw new Error(result.message || 'Não foi possível confirmar a leitura. Atualize a lista para conferir.');
      saved = true;
      const refreshed = await loadTermOffers(termCurrentUrl);
      termStatus.hidden = false;
      termStatus.textContent = refreshed ? (result.message || 'Alerta marcado como lido.') : 'Alerta marcado como lido, mas não foi possível atualizar a lista. Tente novamente.';
      termBody.querySelector(`#${CSS.escape(cardId)} .offer-summary`)?.focus();
    } catch (error) {
      termStatus.hidden = false;
      termStatus.textContent = saved ? 'Alerta marcado como lido, mas não foi possível atualizar a lista. Tente novamente.' : (error.message || 'Não foi possível confirmar a leitura. Atualize a lista para conferir.');
    } finally {
      button.disabled = false;
      termActionBusy = false;
    }
  });
}
document.addEventListener('click', (event) => {
  const summary = event.target.closest('.offer-summary');
  if (!summary) return;
  const selection = window.getSelection();
  if (selection && !selection.isCollapsed && summary.contains(selection.anchorNode)) return;
  event.preventDefault();
  showOffer(summary.closest('.offer-detail'));
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
  const status = document.querySelector('#new-offers');
  const refresh = document.querySelector('#refresh-feed');
  const query = new URLSearchParams({q: feed.dataset.q, alerts: feed.dataset.alerts});
  async function poll() {
    const current = generation;
    try {
      const response = await fetch(`/offers/new?${query}&after=${marker}`, {credentials: 'same-origin'});
      if (!response.ok) throw new Error();
      const {count} = await response.json();
      if (current !== generation) return;
      status.hidden = !count;
      status.textContent = count ? `${count} ${count === 1 ? 'nova oferta' : 'novas ofertas'} disponível${count === 1 ? '' : 'is'}. Use Atualizar lista para exibir.` : '';
    } catch {
      if (current !== generation) return;
      status.hidden = false;
      status.textContent = 'Não foi possível verificar novas ofertas. A próxima tentativa será automática.';
    }
  }
  function applyPage(doc) {
    const next = doc.querySelector('#feed');
    if (!next) throw new Error();
    feed.innerHTML = next.innerHTML;
    marker = Number(next.dataset.marker);
    generation++;
    document.querySelector('#alert-counter').innerHTML = doc.querySelector('#alert-counter').innerHTML;
    document.querySelector('#feed-nav').innerHTML = doc.querySelector('#feed-nav').innerHTML;
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
  document.querySelector('#feed-nav').addEventListener('click', async (event) => {
    if (!event.target.closest('#refresh-feed')) return;
    event.preventDefault();
    if (busy) return;
    busy = true;
    try {
      await loadPage(await fetch(`${feed.dataset.alerts === 'true' ? '/alerts' : '/'}?${query}`, {credentials: 'same-origin'}));
      await poll();
    } catch { toast('Não foi possível atualizar a lista. Tente novamente.', true); }
    finally { busy = false; }
  });
  feed.addEventListener('submit', async (event) => {
    const form = event.target;
    if (!form.matches('[data-mark-seen]')) return;
    event.preventDefault();
    if (busy) return;
    busy = true;
    const button = event.submitter || form.querySelector('button');
    const cardId = form.closest('.offer-card').id;
    button.disabled = true;
    let saved = false;
    try {
      const response = await fetch(form.action, {method: 'POST', body: new FormData(form), headers: {Accept: 'application/json'}, credentials: 'same-origin'});
      if (!response.ok || !(await response.json()).ok) throw new Error();
      saved = true;
      await loadPage(await fetch(`${feed.dataset.alerts === 'true' ? '/alerts' : '/'}?${query}`, {credentials: 'same-origin'}));
      document.getElementById(cardId)?.querySelector('.offer-summary')?.focus();
      toast('Alerta marcado como lido.');
      await poll();
    } catch {
      toast(saved ? 'Alerta marcado como lido, mas a lista não foi atualizada. Tente atualizar.' : 'Não foi possível confirmar a leitura. Atualize a lista para conferir.', true);
    } finally { button.disabled = false; busy = false; }
  });
  setInterval(poll, 30000);
}


const ignoredSettings = document.querySelector('#ignored-settings');
function filterIgnored() {
  const search = document.querySelector('#ignored-search');
  if (!search) return;
  const normalize = (text) => text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
  const rows = [...document.querySelectorAll('.ignored-list li')];
  const term = normalize(search.value.trim());
  rows.forEach((row) => { row.hidden = !normalize(row.querySelector('span').textContent).includes(term); });
  const visible = rows.filter((row) => !row.hidden).length;
  document.querySelector('#ignored-count').textContent = `${rows.length} palavras cadastradas · ${visible} visíveis`;
  document.querySelector('#ignored-no-results').hidden = !term || visible > 0;
}
ignoredSettings?.addEventListener('input', (event) => { if (event.target.id === 'ignored-search') filterIgnored(); });
async function updateIgnoredList() {
  if (!ignoredSettings) return;
  const search = document.querySelector('#ignored-search').value;
  const response = await fetch('/ignored', {credentials: 'same-origin'});
  if (!response.ok || response.redirected) throw new Error();
  const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
  const next = doc.querySelector('#ignored-management');
  if (!next) throw new Error();
  document.querySelector('#ignored-management').innerHTML = next.innerHTML;
  document.querySelector('#ignored-search').value = search;
  filterIgnored();
}
async function submitQuick(form, button) {
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
        await refreshTerms();
        document.querySelector('#refresh-feed')?.click();
      }
      if (form.action.endsWith('/rules') && document.querySelector('#rules-list')) {
        const page = await fetch('/rules-page', {credentials: 'same-origin'});
        if (!page.ok || page.redirected) throw new Error();
        const doc = new DOMParser().parseFromString(await page.text(), 'text/html');
        document.querySelector('#rules-list').innerHTML = doc.querySelector('#rules-list').innerHTML;
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
  event.preventDefault();
  submitQuick(event.target, event.submitter || event.target.querySelector('button'));
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
selectionBar.innerHTML = '<button type="button" data-selection-action="rule">Criar alerta</button><button type="button" data-selection-action="ignore">Ignorar ofertas</button><span class="selection-help" role="status" hidden></span>';
document.body.append(selectionBar);
let selectedText = '';
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
  (dialog || document.body).append(selectionBar);
  const rule = selectionBar.querySelector('[data-selection-action="rule"]');
  const ignored = selectionBar.querySelector('[data-selection-action="ignore"]');
  const help = selectionBar.querySelector('.selection-help');
  rule.hidden = location.pathname !== '/rules-page';
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
    event.preventDefault();
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
  if (action === 'rule') { data.set('name', text); data.set('keywords', text); }
  else data.set('word', text);
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
      await refreshTermOffers();
      document.querySelector('#refresh-feed')?.click();
    } else if (document.querySelector('#rules-list')) {
      const response = await fetch('/rules-page', {credentials: 'same-origin'});
      if (!response.ok || response.redirected) throw new Error();
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      document.querySelector('#rules-list').innerHTML = page.querySelector('#rules-list').innerHTML;
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
