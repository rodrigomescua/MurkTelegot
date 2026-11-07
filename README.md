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
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

Para executar localmente:

```bash
./run-dev.sh
```

O script cria `.venv` e instala as dependências se necessário, solicita API ID, API hash e senha do painel e inicia o servidor em <http://127.0.0.1:8000>. O hash e a senha ficam ocultos durante a digitação. As credenciais são passadas somente pelo ambiente do processo, sem gravar `.env`. Os dados e a sessão Telegram ficam em `.data/`. Pare com `Ctrl+C`. A primeira execução precisa de acesso à internet para instalar dependências.

`APP_USER` é opcional e vale `admin`. Sem credenciais Telegram, o painel e as regras funcionam, mas a conexão fica indisponível. Use um único processo/replica: a sessão Telegram e o estado de login pertencem a esta instância.

`APP_PUBLIC_URL` opcional define a origem HTTPS pública do app. Quando configurada, notificações Gotify incluem miniatura de imagens não ocultas por spoiler, em link assinado que expira após 24 horas. Quem possuir link pode ver imagem sem login até expirar; configure somente se aceitar esse acesso temporário.

## Comportamento

- Captura mensagens e edições dos grupos selecionados, inclusive fotos sem legenda. Preserva texto, entidades e metadados originais; álbuns aparecem agrupados. Não importa histórico automaticamente nem garante recuperar o intervalo em que ficou desligado.
- Na página **Regras de alerta**, selecione texto para criar uma regra com um toque. Em qualquer página, selecione texto para ignorar ofertas. A seleção aceita até 100 caracteres; regra não aceita vírgula. Em celulares, toque e segure para selecionar o texto.
- O atalho flutuante permite adicionar palavras ignoradas. Gerencie regras que geram alertas na página **Regras de alerta**; o menu **Grupos** abre a seleção de fontes.
- Regras usam alternativas separadas por vírgula, sem distinguir maiúsculas e acentos, com limite de palavra. `café, cafeteira` encontra qualquer uma; `rtx 4060` procura essa expressão. Não há regex. Ao criar uma regra, ofertas salvas que correspondem recebem alertas retroativamente, inclusive as ocultas por palavras ignoradas; mensagens futuras e edições também são verificadas.
- Na página **Palavras ignoradas**, que possui busca para listas extensas, cadastre termos ou expressões para ocultar ofertas da listagem principal. A comparação ignora caixa e acentos e exige limites de palavra: `PS5`, `(PS5)` e `PS5!` correspondem; `PS5pro` e `PS55` não. A regra se aplica a ofertas existentes e novas, incluindo o álbum inteiro quando alguma parte corresponde. Ofertas ignoradas sem alerta são apagadas 4 horas após a data Telegram em `offers.date`; alertas são preservados.
- A página **Termos frequentes** identifica palavras e expressões de até três palavras em ofertas salvas, contando cada oferta ou álbum uma vez. Mostra termos presentes em pelo menos duas ofertas, desconsiderando maiúsculas, acentos, URLs, termos compostos só por números e palavras comuns. O mínimo de caracteres é configurável em **Configurações** (padrão e mínimo permitidos: 4). Cada termo permite abrir as ofertas correspondentes em uma lista paginada; também é possível ignorar ofertas pelo termo ou apenas ocultar e restaurar a sugestão; selecione vários termos da página para aplicar essas ações em lote (até 50 por vez); termos inteiros contidos em sugestões ocultas também ficam fora da lista. A análise desconsidera ofertas e álbuns ocultos por palavras ignoradas; os alertas são preservados. Na inicialização, palavras ignoradas numéricas ou com menos de quatro caracteres são removidas do banco.
- A página **Alertas** separa ofertas em não lidas e lidas; cards com alerta na Home e nas ofertas de termos usam as mesmas ações. Marque como lida ou exclua a oferta, inclusive um álbum inteiro. As ações atualizam o card sem recarregar, com opção de desfazer até sair ou atualizar a tela. A Home oculta alertas lidos e mantém os não lidos; álbuns só são ocultados quando todos os alertas do grupo foram lidos. A leitura só muda de seção após recarregar. Exclusões ficam ocultas em todas as telas e são apagadas fisicamente após uma hora (a limpeza periódica pode atrasar até cinco minutos). Cada seção considera até 100 mensagens recentes, após o filtro por estado e busca; o contador geral inclui todos os alertas não lidos. Alertas permanecem no banco até exclusão manual. Em **Configurações**, é possível ativar notificações Gotify; o envio inclui texto formatado em Markdown e o link da oferta, inclusive quando ela está oculta por palavras ignoradas. Regras novas também notificam correspondências retroativas, uma vez por oferta/álbum. Com `APP_PUBLIC_URL` HTTPS, imagens não-spoiler usam link HMAC temporário de 24 horas. Qualquer pessoa com link pode ver imagem até expirar, exceto enquanto a oferta estiver excluída logicamente. Sem URL pública válida ou imagem compatível, notificação mantém texto e link Telegram. O painel verifica novas ofertas a cada 30 segundos e informa a quantidade; use **Atualizar lista** para exibi-las sem recarregar a página. Alterações nas palavras ignoradas atualizam a lista automaticamente quando o JavaScript está ativo. A busca é mantida ao alternar abas e ao marcar ofertas como lidas. Horários são exibidos no fuso do navegador.
- Ofertas aparecem em grid de cards com imagem inteira na capa, proporção preservada e até duas primeiras linhas não vazias. Abra uma oferta para consultar a mensagem completa e ações em um modal; spoilers continuam ocultos. A consulta inicial considera até 100 mensagens; partes adicionais dos álbuns encontrados também são mostradas. Mensagens duplicadas são consolidadas por grupo e ID. Desmarcar grupos ou remover regras preserva as ofertas já salvas. Ofertas sem alerta e sem palavra ignorada são apagadas 24 horas após a data Telegram em `offers.date`. Mensagens apagadas no Telegram não são removidas localmente.
- Formatação, links, fotos, vídeos, áudio, anexos, prévias, enquetes, respostas e encaminhamentos são exibidos conforme os dados disponíveis. Mídias são baixadas sob demanda e armazenadas no volume; ações interativas e tipos não suportados permanecem no Telegram. Em **Configurações → Inteligência artificial**, é possível configurar OpenAI e/ou OpenRouter e escolher/ordenar modelos como fallback. Novas ofertas não ignoradas são extraídas automaticamente, inclusive álbuns completos; a extração manual continua disponível para até 100 ofertas do feed padrão da Home. É possível limitar entre 1 e 8 jobs simultâneos (padrão 1). Cada chamada tem timeout de 1 minuto; após falha de todos os modelos, a oferta volta uma vez ao fim da fila. Cancelamentos e resultados obsoletos não são repetidos. Cada tentativa consulta a ordem, modelos e chaves salvos; alterações valem na próxima chamada. O texto completo das mensagens do álbum é enviado ao provedor; isso pode consumir créditos. Os cards da Home, Alertas e ofertas de termos mostram somente título do produto, preços e cupom quando extraídos; termos frequentes usam somente o nome do produto extraído em ofertas extraídas, sem contar o texto original quando o nome está vazio; a mensagem original continua disponível ao abrir o card. Na página de jobs, é possível cancelar jobs ativos (o provedor ainda pode continuar processando e cobrar após o cancelamento local), limpar os jobs concluídos ou cancelar e limpar todo o histórico.

## Notificações Gotify

1. No Gotify, crie uma aplicação e copie o token dela.
2. No painel, acesse **Configurações**, informe a URL acessível pelo app e o token, ative as notificações e salve.
3. Use **Enviar teste com configuração salva** para verificar a integração. O teste também funciona enquanto as notificações estão desativadas.

O token é salvo no banco dentro do volume de dados; proteja o volume e seus backups. Alertas novos, inclusive criados por edições ou recuperação manual, geram uma tentativa por oferta; mensagens repetidas não geram novos envios enquanto a oferta já tiver um alerta. Regras novas também notificam via Gotify correspondências retroativas, uma vez por oferta/álbum. Falhas de envio são registradas sem o token e não são repetidas automaticamente; o alerta permanece no painel. Use HTTPS quando a conexão Gotify atravessar redes não confiáveis.

## Dados, atualização e recuperação

Mensagens antigas têm apenas texto salvo: use **Recuperar original** para buscar novamente o conteúdo disponível no Telegram (o grupo deve estar selecionado). O volume `murktelegot_data` guarda `offers.db`, `telegram.session` e o cache de mídias `media/`. A sessão permite acesso à sua conta Telegram: proteja o volume e os backups como uma senha. O app apaga automaticamente ofertas sem alerta 4 horas após a data Telegram em `offers.date` quando ignoradas por palavra e 24 horas após essa data nos demais casos; alertas permanecem até exclusão manual, que os oculta imediatamente e os apaga após uma hora. A sessão é reutilizada após reiniciar o container. Um login ainda em andamento (telefone e etapa) fica apenas na memória do servidor; se reiniciar antes de concluir, solicite um novo código. Códigos e senhas não são gravados no armazenamento do navegador; em caso de erro ficam apenas nos campos da página atual. É possível revogar a sessão pelo Telegram em **Configurações → Dispositivos**.

Para atualizar, escolha a tag no Compose e execute `docker compose pull` e `docker compose up -d`. Preserve o volume. Faça backup do volume com o app parado antes da atualização. Na primeira inicialização, a migração cria `offers.db.before-rich-messages.db` antes de adicionar colunas, preservando os dados existentes. Para voltar de versão, restaure a imagem e o backup correspondente. Não execute `docker compose down -v`: isso apaga o volume.

O endpoint `/health` verifica o processo web, não a conexão com o Telegram. Credenciais, códigos e senhas não são enviados aos logs HTTP; a página de login usa uma sessão com cookie HttpOnly e SameSite estrito, válida por até 12 horas ou até sair/reiniciar o app. O acesso deve passar por HTTPS ou pelo túnel quando remoto.

## Documentação do projeto

Consulte o [índice de documentação](docs/README.md) para arquitetura, escopo da primeira entrega, operação e evidências de testes. O [AGENTS.md](AGENTS.md) reúne contratos de desenvolvimento e manutenção.
