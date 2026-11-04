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
    status.textContent = result.message || (typeof result.detail === 'string' ? result.detail : 'Não foi possível concluir. Confira os dados e tente novamente.');
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

for (const time of document.querySelectorAll('time[datetime]')) {
  const date = new Date(time.dateTime);
  if (!Number.isNaN(date.getTime())) {
    time.textContent = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' }).format(date);
    time.title = 'Horário local do seu navegador';
  }
}
