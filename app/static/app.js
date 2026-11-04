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
    detail.open = true;
    requestAnimationFrame(() => target.scrollIntoView());
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
    const opened = [...document.querySelectorAll('.offer-card .offer-detail[open]')].map((item) => item.closest('.offer-card').id);
    feed.innerHTML = next.innerHTML;
    marker = Number(next.dataset.marker);
    generation++;
    opened.forEach((id) => { const detail = document.getElementById(id)?.querySelector('.offer-detail'); if (detail) detail.open = true; });
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
      await loadPage(await fetch(`/?${query}`, {credentials: 'same-origin'}));
      await poll();
    } catch { toast('Não foi possível atualizar a lista. Tente novamente.', true); }
    finally { busy = false; }
  });
  document.querySelector('#ignored-settings').addEventListener('submit', async (event) => {
    const form = event.target;
    event.preventDefault();
    if (busy) return;
    busy = true;
    const button = event.submitter || form.querySelector('button');
    const draft = document.querySelector('#ignored-word').value;
    button.disabled = true;
    try {
      const response = await fetch(form.action, {method: 'POST', body: new FormData(form), credentials: 'same-origin'});
      const doc = await loadPage(response);
      const nextMenu = doc.querySelector('#ignored-settings');
      if (!nextMenu) throw new Error();
      document.querySelector('#ignored-settings').innerHTML = nextMenu.innerHTML;
      document.querySelector('#ignored-menu').open = true;
      const message = doc.querySelector('[data-toast]')?.textContent || 'Filtro atualizado.';
      if (!form.action.endsWith('/ignored') || message !== 'Palavra adicionada ao filtro.') document.querySelector('#ignored-word').value = draft;
      toast(message);
      await poll();
    } catch { toast('Não foi possível confirmar o filtro. Atualize a página e confira antes de tentar novamente.', true); }
    finally { busy = false; button.disabled = false; }
  });
  setInterval(poll, 30000);
}
