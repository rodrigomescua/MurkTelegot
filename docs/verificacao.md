# Verificação

## Prova local reproduzível

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt httpx==0.28.1
.venv/bin/python -m unittest discover -s tests -v
bash -n run-dev.sh
node --check app/static/app.js
```

Execute diretamente com Python; não use Docker/Compose nos testes deste ambiente. Os testes criam bancos temporários e usam clientes simulados, sem abrir o banco ou a sessão pessoal. CI usa Python 3.12; o ambiente local inicial usa Python 3.14.4.

## Evidências de 2026-11-04

A suíte contém 18 testes: correspondência de palavras e acentos, seleção de fontes, transações e edições, autenticação, CSRF, escape HTML, busca, preservação de filtros, etapas de login/2FA e script de desenvolvimento. O script aceita senhas de 12 caracteres e rejeita 11; o limite do app também foi verificado em processo separado.

Uvicorn foi iniciado diretamente em uma verificação HTTP: health, painel autenticado e CSS responderam 200. Um teste manual automatizado com Chromium/Playwright verificou preservação dos campos em erros, telefone após recarregar, 2FA sem reenviar código, rascunho de regra durante o login, busca e seleção em 35 grupos simulados, layout com 390 px, ausência de erros JavaScript e ausência de segredos no armazenamento do navegador. Esse probe ficou fora do repositório e não faz parte do CI.

O usuário confirmou o login real no Telegram. Essa confirmação é distinta dos testes automatizados, que não enviaram credenciais reais ao Telegram.

## Limites

Não há benchmark de desempenho nem teste de carga. O build e a execução de containers não foram feitos neste ambiente. A publicação GHCR é verificada no workflow da release; esse resultado não substitui testar a imagem no servidor de destino. Consulte os resultados de cada push no GitHub Actions para confirmar a suíte em Python 3.12.
