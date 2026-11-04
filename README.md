# MurkTelegot

Radar pessoal de ofertas do Telegram com painel web em português. Usa sua conta para acompanhar os grupos e canais selecionados, reúne as mensagens e destaca ofertas por palavras-chave.

## Produção: imagem pronta

1. Publique o projeto no GitHub e crie uma release com tag semântica, por exemplo `v0.0.1`. O workflow testa o app e publica `ghcr.io/PROPRIETARIO/REPOSITORIO:0.0.1` e `:latest` para AMD64 (`linux/amd64`). Pre-releases não são publicadas. A publicação só acontece após os testes passarem.
2. Copie apenas `docker-compose.yml` para o servidor. Edite `image` com o proprietário/repositório em minúsculas e a versão desejada. Se o pacote GHCR for privado, execute `docker login ghcr.io`; para distribuição sem login, configure a visibilidade pública do pacote no GitHub.
3. No próprio Compose, substitua `APP_PASSWORD` por uma senha aleatória com pelo menos 12 caracteres e preencha `TELEGRAM_API_ID` e `TELEGRAM_API_HASH`, obtidos em <https://my.telegram.org/apps>. Mantenha as credenciais reais somente no servidor, fora do Git. Nenhum `.env` é usado em produção.
4. Execute `docker compose pull` e `docker compose up -d`. Acesse <http://localhost:8000> com o usuário e a senha do Compose. Para servidor remoto, use um túnel SSH (`ssh -L 8000:127.0.0.1:8000 usuario@servidor`) ou proxy HTTPS com controle de acesso. A porta fica vinculada ao loopback por padrão.
5. No painel, informe o telefone com DDI e solicite o código. O telefone fica preenchido e o painel avança para o código; se houver verificação em duas etapas, a senha é solicitada somente depois de aceitar o código. Erros preservam os campos sem recarregar a página. Selecione os grupos/canais (com busca e seleção dos visíveis) e crie suas regras.

O exemplo Compose usa somente imagem pré-buildada: não existe `build:` nem `env_file:`. A senha de exemplo é recusada pelo app. Não é necessário adicionar bots aos grupos.

## Desenvolvimento e testes: Python direto

Requer Python 3.12 ou superior. Não é necessário Docker.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt httpx==0.28.1
.venv/bin/python -m unittest discover -s tests -v
```

Para executar localmente:

```bash
./run-dev.sh
```

O script cria `.venv` e instala as dependências se necessário, solicita API ID, API hash e senha do painel e inicia o servidor em <http://127.0.0.1:8000>. O hash e a senha ficam ocultos durante a digitação. As credenciais são passadas somente pelo ambiente do processo, sem gravar `.env`. Os dados e a sessão Telegram ficam em `.data/`. Pare com `Ctrl+C`. A primeira execução precisa de acesso à internet para instalar dependências.

`APP_USER` é opcional e vale `admin`. Sem credenciais Telegram, o painel e as regras funcionam, mas a conexão fica indisponível. Use um único processo/replica: a sessão Telegram e o estado de login pertencem a esta instância.

## Comportamento

- Captura novas mensagens com texto/legenda e suas edições nos grupos selecionados. Não importa histórico nem oferece recuperação garantida do intervalo em que o app ficou desligado.
- Regras usam alternativas separadas por vírgula, sem distinguir maiúsculas e acentos, com limite de palavra. `café, cafeteira` encontra qualquer uma; `rtx 4060` procura essa expressão. Não há regex. Regras novas valem para mensagens futuras e futuras edições, sem reprocessar histórico.
- Alertas aparecem na aba **Meus alertas**, com contador de não lidos e ação para marcar como lido. Não há envio de notificações externas nesta versão. Use **Atualizar** para buscar novidades no painel. A busca é mantida ao alternar abas e ao marcar ofertas como lidas. Horários são exibidos no fuso do navegador.
- O painel mostra até 100 mensagens por consulta. Mensagens duplicadas são consolidadas por grupo e ID. Desmarcar grupos ou remover regras preserva as ofertas já salvas. Mensagens apagadas no Telegram não são removidas localmente.
- Links diretos estão disponíveis para canais e supergrupos; grupos básicos não têm link individual compatível. Mídias não são baixadas e preços não são extraídos automaticamente.

## Dados, atualização e recuperação

O volume `murktelegot_data` guarda `offers.db` e `telegram.session`. A sessão permite acesso à sua conta Telegram: proteja o volume e os backups como uma senha. As mensagens permanecem até uma limpeza manual; monitore espaço em disco. A sessão é reutilizada após reiniciar o container. Um login ainda em andamento (telefone e etapa) fica apenas na memória do servidor; se reiniciar antes de concluir, solicite um novo código. Códigos e senhas não são gravados no armazenamento do navegador; em caso de erro ficam apenas nos campos da página atual. É possível revogar a sessão pelo Telegram em **Configurações → Dispositivos**.

Para atualizar, escolha a tag no Compose e execute `docker compose pull` e `docker compose up -d`. Preserve o volume. Faça backup do volume com o app parado antes da atualização; a versão inicial não possui migrações de esquema. Para voltar de versão, restaure a imagem e o backup correspondente. Não execute `docker compose down -v`: isso apaga o volume.

O endpoint `/health` verifica o processo web, não a conexão com o Telegram. Credenciais, códigos e senhas não são enviados aos logs HTTP; o acesso usa HTTP Basic e deve passar por HTTPS ou pelo túnel quando remoto.

## Documentação do projeto

Consulte o [índice de documentação](docs/README.md) para arquitetura, escopo da primeira entrega, operação e evidências de testes. O [AGENTS.md](AGENTS.md) reúne contratos de desenvolvimento e manutenção.
