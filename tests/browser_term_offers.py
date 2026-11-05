import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)

with tempfile.TemporaryDirectory() as directory:
    env = dict(os.environ, DATA_DIR=directory, APP_PASSWORD='test-password-long-enough', TELEGRAM_API_ID='', TELEGRAM_API_HASH='')
    setup = """import os
from app.store import Store
s = Store(os.path.join(os.environ['DATA_DIR'], 'offers.db'))
s.execute('INSERT INTO chats VALUES(?,?)', (1, 'Grupo teste'))
s.execute('INSERT INTO rules VALUES(1,?,?)', ('Alerta PS5', 'ps5'))
for number in range(1, 22):
    s.ingest(1, number, f'Cafeteira premium PS5 oferta sintética {number}', '2026-11-04T12:00:00', None)
"""
    subprocess.run([sys.executable, '-c', setup], env=env, check=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
            context = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{port}/login')
            page.locator('#username').fill('admin')
            page.locator('#panel-password').fill('test-password-long-enough')
            page.get_by_role('button', name='Entrar').tap()
            page.get_by_role('link', name='Termos frequentes').tap()
            page.wait_for_url('**/terms')
            term_box = page.locator('input[name="words"][value="cafeteira"]')
            term_box.check()
            trigger = page.get_by_role('link', name='Ver ofertas com cafeteira', exact=True)
            page.route('**/terms/offers?word=cafeteira&page=1', lambda route: route.fulfill(status=503, body='falha sintética'), times=1)
            trigger.tap()
            dialog = page.locator('.term-offers-modal')
            dialog.wait_for(state='visible')
            page.get_by_text('Não foi possível carregar as ofertas. Tente novamente.').wait_for()
            dialog.get_by_role('button', name='Tentar novamente').tap()
            dialog.get_by_text('Página 1 de 2').wait_for()
            assert dialog.get_by_role('heading', name='Ofertas com “cafeteira”').is_visible()
            assert dialog.locator('.offer-card').count() == 20
            assert dialog.locator('time[title="Horário local do seu navegador"]').count() == 20

            dialog.get_by_role('link', name='Próxima →').tap()
            dialog.get_by_text('Página 2 de 2').wait_for()
            assert dialog.locator('.offer-card').count() == 1
            dialog.get_by_role('link', name='← Anterior').tap()
            dialog.get_by_text('Página 1 de 2').wait_for()

            # Erro no POST mantém o card; sucesso atualiza a página sem navegar.
            page.route('**/offers/*/seen', lambda route: route.fulfill(status=500, json={'ok': False}), times=1)
            seen = dialog.locator('[data-mark-seen]').first.get_by_role('button')
            seen.tap()
            dialog.get_by_text('Não foi possível confirmar a leitura. Atualize a lista para conferir.').wait_for()
            assert dialog.locator('[data-mark-seen]').count() == 20
            dialog.locator('[data-mark-seen]').first.get_by_role('button').tap()
            dialog.get_by_text('Alerta marcado como lido.').wait_for()
            assert dialog.locator('[data-mark-seen]').count() == 19
            assert page.url.endswith('/terms')

            # A oferta individual fecha sobre o mesmo card; fechar restaura foco e seleção em lote.
            summary = dialog.locator('.offer-summary').first
            summary.tap()
            offer_dialog = page.locator('dialog.offer-modal:not(.term-offers-modal)')
            offer_dialog.wait_for(state='visible')
            offer_dialog.get_by_role('button', name='Fechar oferta').tap()
            dialog.wait_for(state='visible')
            assert page.evaluate('document.activeElement.classList.contains("offer-summary")')
            assert term_box.is_checked()
            dialog.get_by_role('button', name='Fechar').tap()
            assert not page.locator('.term-offers-modal').evaluate('(node) => node.open')
            assert trigger.evaluate('(node) => node === document.activeElement')

            # Sem JavaScript o link abre a página completa com seus cards e paginação.
            fallback_context = browser.new_context(viewport={'width': 390, 'height': 844}, java_script_enabled=False)
            nojs = fallback_context.new_page()
            nojs.goto(f'http://127.0.0.1:{port}/login')
            nojs.locator('#username').fill('admin')
            nojs.locator('#panel-password').fill('test-password-long-enough')
            with nojs.expect_navigation():
                nojs.locator('button').click()
            nojs.get_by_role('link', name='Termos frequentes').click()
            nojs.wait_for_url('**/terms')
            nojs.get_by_role('link', name='Ver ofertas com cafeteira', exact=True).click()
            nojs.wait_for_url('**/terms/offers?word=cafeteira&page=1')
            assert nojs.locator('#term-offers-content .offer-card').count() == 20
            # Ignorar texto selecionado dentro do dialog atualiza cards e termo sem abandonar a tela.
            trigger.tap()
            dialog = page.locator('.term-offers-modal')
            dialog.wait_for(state='visible')
            dialog.locator('.offer-preview').first.evaluate('''el => {
              const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
              let node;
              while ((node = walker.nextNode())) {
                const at = node.textContent.toLowerCase().indexOf('cafeteira');
                if (at >= 0) {
                  const range = document.createRange();
                  range.setStart(node, at); range.setEnd(node, at + 9);
                  const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range); return;
                }
              }
              throw Error('termo sintético não encontrado');
            }''')
            page.locator('.term-offers-modal .selection-actions').wait_for(state='visible')
            page.locator('.term-offers-modal .selection-actions [data-selection-action="ignore"]').tap()
            dialog.get_by_text('Nenhuma oferta encontrada para este termo.').wait_for()
            assert page.url.endswith('/terms')
            dialog.get_by_role('button', name='Fechar').tap()
            page.wait_for_timeout(100)
            assert page.evaluate('document.activeElement.id') == 'terms-title'
            assert page.locator('input[name="words"][value="cafeteira"]').count() == 0

            assert not errors, errors
            print('Chromium móvel: modal, retry, paginação, leitura, oferta aninhada, foco, lote, ignorar seleção e fallback completos')
            fallback_context.close()
            browser.close()
    finally:
        server.terminate()
        server.wait()
