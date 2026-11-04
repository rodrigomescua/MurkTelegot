#!/usr/bin/env bash
set -euo pipefail
# Never trace credentials, even when invoked with bash -x.
set +x
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import fastapi, uvicorn, telethon, jinja2, multipart' 2>/dev/null; then
    .venv/bin/python -m pip install -r requirements.txt
fi

read -r -p 'Telegram API ID: ' TELEGRAM_API_ID
read -r -s -p 'Telegram API hash (oculto): ' TELEGRAM_API_HASH
printf '\n'
read -r -s -p 'Senha do painel, mínimo 12 caracteres (oculta): ' APP_PASSWORD
printf '\n'

if [[ ! "$TELEGRAM_API_ID" =~ ^[1-9][0-9]*$ ]]; then
    printf 'API ID inválido: informe um número inteiro positivo.\n' >&2
    exit 1
fi
if [[ ! "$TELEGRAM_API_HASH" =~ ^[[:xdigit:]]{32}$ ]]; then
    printf 'API hash inválido: informe os 32 caracteres hexadecimais do Telegram.\n' >&2
    exit 1
fi
if [[ ${#APP_PASSWORD} -lt 12 || "$APP_PASSWORD" == 'SUBSTITUA-POR-UMA-SENHA-ALEATORIA-LONGA' ]]; then
    printf 'Senha inválida: escolha uma senha própria com pelo menos 12 caracteres.\n' >&2
    exit 1
fi

export TELEGRAM_API_ID TELEGRAM_API_HASH APP_PASSWORD
export APP_USER="${APP_USER:-admin}"
export DATA_DIR="$PWD/.data"
printf 'Painel: http://127.0.0.1:8000 | Usuário: %s | Ctrl+C para parar.\n' "$APP_USER"
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
