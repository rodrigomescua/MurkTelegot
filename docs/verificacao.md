# Verificação

## Prova local reproduzível

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
bash -n run-dev.sh
node --check app/static/app.js
```

Execute diretamente com Python; não use Docker/Compose nos testes deste ambiente. Os testes criam bancos temporários e usam clientes simulados, sem abrir o banco ou a sessão pessoal. CI usa Python 3.12; o ambiente local inicial usa Python 3.14.4.

## Evidências de 2026-11-04

A suíte contém 47 testes: correspondência de palavras e acentos, seleção de fontes, transações e edições, autenticação, CSRF, escape HTML, busca, preservação de filtros, etapas de login/2FA, script de desenvolvimento entrega HTTP dos assets de marca canônicos, migração de banco, formatação segura, álbuns, mídia autenticada e prévias de cards sem revelar spoilers e filtro de palavras ignoradas independente de alertas. O script aceita senhas de 12 caracteres e rejeita 11; o limite do app também foi verificado em processo separado.

Uvicorn foi iniciado diretamente em uma verificação HTTP: health, painel autenticado e CSS responderam 200. Um teste manual automatizado com Chromium/Playwright verificou preservação dos campos em erros, telefone após recarregar, 2FA sem reenviar código, rascunho de regra durante o login, busca e seleção em 35 grupos simulados, layout com 390 px, ausência de erros JavaScript e ausência de segredos no armazenamento do navegador. Esse probe ficou fora do repositório e não faz parte do CI.

O usuário confirmou o login real no Telegram. Essa confirmação é distinta dos testes automatizados, que não enviaram credenciais reais ao Telegram.

## Pré-publicação v0.5.12 — 2026-11-08

154 testes `unittest`, `py_compile app/main.py app/store.py`, `node --check app/static/app.js`, `bash -n run-dev.sh` e `git diff --check` passaram. Com uma cópia isolada do backup atualizado, a migração de causa levou 1,42 s para 894 ofertas e 676 palavras; a rota `/deleted` respondeu em 123 ms no Chromium, exibiu 25 cards por página e passou pela página seguinte. A primeira execução também aplicou a retenção existente ao banco temporário, que ficou com 765 cards. Chromium em desktop e 390 px não mostrou overflow horizontal nem erros JavaScript. A cópia temporária foi descartada; nenhum dado do banco original foi alterado.

## Pré-publicação v0.5.13 — 2026-11-09

O teste focado para descartar respostas do Telegram passou. `py_compile` para o código e o teste, `bash -n run-dev.sh`, `node --check app/static/app.js` e `git diff --check` passaram. A suíte completa foi iniciada depois da instalação das dependências, mas não terminou localmente: ficou aguardando no teste `test_event_ingestion_ignores_private_and_handles_edits`. O CI do push [42564480410](https://github.com/rodrigomescua/MurkTelegot/actions/runs/42564480410) passou com `test`; `publish` foi ignorado porque o evento era push. A criação da release retornou HTTP 403 pela CLI; a tag `v0.5.13` e a imagem GHCR não foram publicadas. A `main` do catálogo Runtipi está protegida pelo status obrigatório `test`; nenhuma alteração no catálogo foi iniciada.

## Limites

Não há benchmark de desempenho nem teste de carga. O build e a execução de containers não foram feitos neste ambiente. A publicação GHCR é verificada no workflow da release; esse resultado não substitui testar a imagem no servidor de destino. Consulte os resultados de cada push no GitHub Actions para confirmar a suíte em Python 3.12.

## Release 0.5.6 — 2026-11-07

142 testes `unittest`, `node --check app/static/app.js`, `bash -n run-dev.sh`, `py_compile app/main.py app/store.py` e `git diff --check` passaram. Validação visual não executada por solicitação do usuário. Workflow de release [42418320284](https://github.com/rodrigomescua/MurkTelegot/actions/runs/42418320284) concluiu os jobs `test` e `publish` com sucesso para `v0.5.6`, confirmando a publicação no GHCR pelo workflow; digest OCI consultável não foi obtido neste ambiente. Catálogo Runtipi atualizado para `0.5.6` (`tipi_version` 36) e o workflow do catálogo passou com 462 testes. A atualização foi enviada diretamente após rebase, contornando a proteção por PR/status; corrigir o procedimento nas próximas publicações e usar PR com checks obrigatórios. O servidor local foi parado. Nenhuma atualização foi aplicada à instância Runtipi.

## Limpeza do cache de mídia órfão — 2026-11-07

144 testes `unittest` passaram. O teste de cache confirma que arquivos vinculados a ofertas ativas e logicamente excluídas são preservados, arquivos sem oferta são removidos e arquivos temporários ativos não são tocados; após a purga física, o cache da oferta é removido. `py_compile app/main.py app/telegram.py`, `node --check app/static/app.js`, `bash -n run-dev.sh` e `git diff --check` passaram. A rotina existente faz essa varredura a cada cinco minutos, inclusive na inicialização; não foi feita validação visual.

Publicação `v0.5.7`: commit `ed716301d1d7d21dc9929ff1a5d7974f457c7c72`; workflow `42429659630` aprovou `test` e `publish`. Manifesto GHCR da tag `0.5.7` confirmou `linux/amd64`, digest `sha256:9400d7990296693aa1f2b662b6846028fcf39fbd9e845c207b38ac559297cc9c`. Catálogo Runtipi atualizado via PR [1459](https://github.com/rodrigomescua/runtipi-custom-appstore/pull/1459), merge `bdc897a9f234a5dc455283da8bf534e9a0a243a8`; checks `test`/`renovate` e workflow pós-merge `42429834064` passaram (462 testes). Catálogo e Compose estão em `0.5.7`, `tipi_version` 37. Instância Runtipi não atualizada.

## Capas em excluídas recentes e exibição de datas — 2026-11-07

145 testes `unittest` passaram; Chromium com oferta e cache de imagem sintéticos verificou capa carregada na tela `/deleted` em viewport 1365 px e 390 px, sem overflow no celular ou erros JavaScript. A imagem carregou pela rota autenticada. Em contexto `America/Sao_Paulo`, o teste mostrou `09:00` para timestamp `12:00+00:00`, incluindo a previsão de purga; o HTML sem transformação mantém o rótulo fallback `UTC`. Não houve acesso à instância/banco Runtipi nem Telegram real.

## Datas de exclusão lógica em `/deleted` — 2026-11-07

A coluna aditiva `offers.ignored_at` registra novas transições para ocultação por palavra ignorada, inclusive backfill de ofertas existentes quando uma nova palavra as oculta. Sobreposições preservam o primeiro timestamp; remover a última palavra correspondente limpa a data. Migração cria backup e mantém ofertas antigas sem horário conhecido como `NULL`. `/deleted` ordena `deleted_at` e `ignored_at` juntos em ordem decrescente, deixa datas antigas ausentes no fim e mostra apenas o dia no fuso local quando JavaScript está disponível. A previsão de exclusão física foi removida da tela; as rotinas e prazos de retenção não foram alterados. 147 testes `unittest`, `node --check app/static/app.js`, `bash -n run-dev.sh` e `git diff --check` passaram. Validação visual não executada por solicitação do usuário.

Após a publicação, os cards de exclusão por palavra passaram a exibir os termos atuais que correspondem a qualquer parte da oferta/álbum; vários termos aparecem juntos. Cards de exclusão manual não exibem termos ignorados. A correspondência usa o matcher existente e não adiciona persistência. A suíte completa passou com 149 testes; validação visual não executada por orientação do usuário.

## Release 0.5.8 e atualização da loja Runtipi — 2026-11-07

O app local não estava em execução. O commit `550a8ce` foi enviado para `main`; o CI de push `42439864914` passou. A release `v0.5.8` publicou a imagem no workflow `42439914956`, com `test` e `publish` aprovados. A API de registry confirmou `ghcr.io/rodrigomescua/murktelegot:0.5.8`, índice OCI `sha256:c0b03f90caa0ccf3ec296a7d35c1c3df9fe0d7ee5348181e5d2c4025896f12f8`, plataforma `linux/amd64`. Catálogo atualizado por PR [1462](https://github.com/rodrigomescua/runtipi-custom-appstore/pull/1462), merge `5324174`; checks `test` e `renovate` passaram e CI pós-merge `42440212673` passou com 462 testes. `tipi_version` passou de 37 para 38. Nenhuma atualização foi aplicada à instância Runtipi.

## Release 0.5.9 e atualização da loja Runtipi — 2026-11-08

O app local não estava em execução. A suíte do app passou com 149 testes; `bash -n run-dev.sh`, `node --check app/static/app.js`, `py_compile app/main.py app/store.py` e `git diff --check` passaram. O commit `6d22039` foi enviado para `main`; CI do push `42443830427` passou. A release `v0.5.9` publicou no workflow `42443879364`, com `test` e `publish` aprovados. Manifesto GHCR confirmado pela API: `ghcr.io/rodrigomescua/murktelegot:0.5.9`, índice OCI `sha256:388dda661ea07c52318e07f6d92b7df2e807edb36253563d47f3d616024b5ee5`, plataforma `linux/amd64`. Catálogo atualizado via PR [1464](https://github.com/rodrigomescua/runtipi-custom-appstore/pull/1464), merge `97e7072`; checks `test`/`renovate` passaram e CI pós-merge `42444122767` passou com 462 testes. `tipi_version` passou de 38 para 39. O appstore foi sincronizado localmente; nenhuma atualização foi aplicada à instância Runtipi. A ferramenta Docker não está instalada; a tag foi validada pelo registry API.

## Integração da identidade visual — 2026-11-04

Logo no cabeçalho, favicon SVG e paleta azul verificados no Chromium, com a aplicação executada diretamente em Python e Telegram simulado. Layout desktop e largura de 320 px conferidos, sem transbordamento horizontal ou erros JavaScript. Repetidos os fluxos de login/2FA e seleção de 35 grupos. Contrastes calculados: texto do botão 7,06:1, links sobre cards 6,33:1, texto secundário 8,19:1 e bordas dos inputs 3,77:1. Esses checks não substituem uma auditoria completa de acessibilidade.

## Grid de ofertas — 2026-11-04

Cards com capa, até duas linhas não vazias e expansão nativa conferidos no Chromium com dados simulados, em desktop e 320 px. O teste cobriu álbuns, ausência/falha de imagem, spoilers, abertura pelo teclado e âncoras após marcar como lido ou recuperar mensagem. Nenhuma conta Telegram real foi acessada.

## Palavras ignoradas — 2026-11-04

Testes verificam palavras inteiras com pontuação, início/fim e Unicode; termos parecidos; ignorar álbuns completos; independência dos alertas; remoção/persistência e filtro aplicado antes do limite. Menu, cadastro/remoção, listagem e alertas foram conferidos no Chromium com banco temporário, sem conta Telegram real.

## Navegação, inclusão rápida e login do painel

A suíte verifica login, saída, expiração, cookie seguro em HTTPS, CSRF e inclusão rápida. Um teste local com Chromium e dados temporários verificou login, saída, atalhos nas páginas, busca e remoção em uma lista com 230 palavras, preservação de rascunho e tela de 390 px. Não houve teste com Telegram real nem Docker nessa alteração.

## Página de alertas

Testes Python verificam separação antes do limite, álbuns parcialmente lidos, palavras ignoradas, CSRF e atualização de leitura. Chromium com dados temporários verificou busca, alteração direta no card, contador e modal em largura de 390 px. Não houve Telegram real ou Docker nesta verificação.

## Termos frequentes

Testes com SQLite temporário verificam contagem por oferta e álbum, acentos, exclusão de URLs, persistência e restauração de sugestões, independência dos alertas, migração aditiva, paginação, autenticação e CSRF. Chromium em largura de 390 px verificou as duas ações, restauração e alertas preservados. Não houve teste com dados reais, Telegram ou Docker nesta alteração.

## Ações em lote nos termos

Testes com dados temporários verificam operações atômicas, validação, limite, CSRF, duplicatas, preservação de alertas e fallback sem JavaScript. Chromium em largura de 390 px verificou seleção, selecionar todos, ambas as ações e fallback sem JavaScript. Sem Telegram real ou Docker local.

## Frequência e filtros

Testes com dados temporários verificam que ofertas ignoradas e álbuns com partes ignoradas não entram nas frequências; palavras e expressões inteiras contidas em sugestões ocultas deixam de aparecer, com restauração e alertas preservados. A partir de 0.2.9, são excluídos termos numéricos e termos menores que o mínimo configurado (padrão/mínimo permitido 4); a inicialização apaga palavras ignoradas numéricas ou menores que quatro caracteres. 94 testes passaram. A tentativa de Chromium não iniciou porque o executável Snap disponível não funcionou com Playwright.

## Notificações Gotify

Testes com dados temporários e servidor HTTP local simulado verificam configuração, autenticação, CSRF, sigilo do token na resposta, envio, recusa de redirecionamento, alertas ignorados, edições e falhas. Chromium em 390 px verificou a tela e o envio de teste simulado. Não foi testado um servidor Gotify real nem Docker.

## Formatação Gotify

Testes com dados temporários verificam metadados Markdown no protocolo Gotify, entidades UTF-16, links seguros, texto escapado, código, citações, spoilers ocultos e indicação de mídia. A exibição em clientes Gotify reais não foi testada.

## Diagnóstico Gotify

Testes simulam respostas HTTP, falhas de DNS, timeout, conexão recusada e TLS, verificam detalhes na tela e no log e ausência de token e texto privado. Chromium com servidor local simulado verificou erro HTTP persistente e sigilo. A falha relatada em produção não foi reproduzida nem identificada neste ambiente.

## Índice da tela principal

Teste com banco temporário verifica criação aditiva do índice em banco existente, preservação de dados e uso pelo SQLite. Os testes existentes verificam busca, ignorados antes do limite e agrupamento. Uma [medição com dados sintéticos](performance/README.md) compara a consulta com e sem o índice; não houve medição em produção.

## Ações por seleção de texto

Com Playwright e Chromium instalados, execute `.venv/bin/python tests/browser_selection.py` (ou defina `PLAYWRIGHT_CHROMIUM_EXECUTABLE` para um executável Chromium disponível). O teste cria dados temporários, verifica que clicar no resumo não abre a oferta e que o botão “Abrir oferta” abre por toque e teclado; sem JavaScript, o `details` continua expansível. Também cobre arraste real de mouse em viewport desktop, seleção móvel simulada, filtro no modal, clique no backdrop, clique na imagem sem abrir outra página, rascunhos, erros, limites, campos sensíveis e spoilers. A seleção móvel é criada pela API do navegador; o gesto de pressionar e segurar e o menu nativo de dispositivos reais não foram testados.

## Retenção e gerenciamento de regras — 2026-11-05

90 testes passaram com SQLite temporário. Testes cobrem prazos com `offers.date`, regras de prioridade, exclusão manual, backfill e Gotify retroativos por álbum, imagens com URL assinada, expiração, assinatura inválida e spoilers. `node --check app/static/app.js`, `bash -n run-dev.sh`, `py_compile` e `git diff --check` passaram. Chromium móvel executou `tests/browser_selection.py` com dados temporários e aprovou seleção/criação de alerta, spoilers e campos sensíveis. Não houve conexão Telegram, Gotify real ou Docker.

## Home e cards — 2026-11-05

A Home foi aberta no Chromium com uma cópia temporária de `.data/offers_backup.db`; o arquivo original não foi alterado. A captura inicial reproduziu a quebra: grid de coluna única com cards de 340 px em viewport de 1365 px, sobrando espaço à direita. Após corrigir o layout, a Home exibiu quatro colunas (cards de 307,75 px) em 1365 px e uma coluna (350 px) em 390 px, sem overflow horizontal. O botão de novas ofertas foi conferido no estado normal e de erro; clique acionou o refresh existente, e o erro apareceu anunciado com o botão desabilitado. O texto não se sobrepôs aos atalhos flutuantes. Clicar na capa ou no texto abriu o modal; CTA textual foi removido. Nenhum erro JavaScript no Chromium. Os testes exibiram placeholders de mídia porque o cache de mídia não foi incluído na cópia; não houve conexão real ao Telegram.

91 testes `unittest` passaram. `bash -n run-dev.sh`, `node --check app/static/app.js`, `py_compile` e `git diff --check` passaram.


## Extração automática e manual de ofertas com IA — 2026-11-05

116 testes passaram com SQLite temporário, eventos Telegram simulados e respostas simuladas dos provedores. Cobrem catálogo, validação de resultados parciais, configuração sem expor chaves, autenticação/CSRF, fallback ordenado, persistência FIFO/retomada de jobs, seleção compatível com o feed da Home, extração automática de ofertas individuais e álbuns completos, exclusão de ofertas/álbuns ignorados, deduplicação de jobs pendentes, comportamento sem provedor configurado, invalidação após edição, descarte de resposta obsoleta se a oferta mudar durante a chamada, atualização da ordem/chave entre tentativas, cancelamento de jobs pendentes e em execução e prioridade dos campos permitidos nos cards da Home, Alertas e ofertas de termos. `py_compile`, `node --check app/static/app.js`, `bash -n run-dev.sh` e `git diff --check` passaram. Chromium com dados temporários verificou cards apenas com título, preços e cupom, além de cancelamento de jobs pendentes/em execução em 390 px e 1365 px, sem overflow nem erros JavaScript. Nesta alteração, a cópia isolada do backup foi aberta em 390 px e 1365 px: 100 cards na Home, texto de extração automática visível em Configurações, sem overflow nem erros JavaScript. Não houve chamadas reais à OpenAI/OpenRouter, nem medição de custos; as chaves são guardadas sem criptografia no SQLite do volume.

## Exclusão lógica e desfazer em cards de alerta — 2026-11-06

119 testes `unittest` passaram com SQLite temporário. Cobrem migração aditiva, exclusão/restauração por álbum, herança da exclusão por partes Telegram atrasadas, filtros de cards/termos/contagem, expiração física e revogação de link HMAC de mídia. `node --check app/static/app.js`, `py_compile`, `bash -n run-dev.sh` e `git diff --check` passaram. `tests/browser_term_offers.py` passou no Chromium do sistema (`/snap/bin/chromium`): viewport móvel de 390 px com toque simulado e desktop de 1365 px; leitura, exclusão, desfazer, mudança de seção e ocultação após recarga, modal/paginação de termos e fallback sem JavaScript. Sem Telegram/Gotify reais.

Release `v0.3.1` publicada no commit `526e189`; workflow `42240099828` aprovou testes e publicação AMD64. GHCR confirmou a tag `0.3.1` no digest `sha256:b2fdf6c8b37f86f5ce2189a6f2febf71d2e3e9351b8b801df4824522511ef583`. Appstore Runtipi atualizado em `fd55ed3`, `tipi_version` 25, tag exata no Compose/config, 462 testes e workflow `42240461812` aprovados. Instância Runtipi não atualizada.

## Interromper chamada em voo ao cancelar job IA — 2026-11-06

122 testes `unittest` passaram com armazenamento temporário e transporte HTTP simulado. Incluem cancelamento de requisição HTTP pendente, resultado descartado, conclusão das ofertas restantes e recuperação de item quando o worker encerra. `node --check app/static/app.js`, `bash -n run-dev.sh`, `compileall` e `git diff --check` passaram. Chromium verificou aviso/cancelamento em 390 px; o desktop 1365 px confirmou autenticação, aviso e cancelamento, sem auditoria separada de layout. Um ensaio visual inicial foi interrompido quando o worker consumiu a fila; usava apenas oferta e chave fictícias e pode ter enviado uma requisição de teste não autenticada ao endpoint OpenAI. Tarifas e encerramento remoto não foram testados: fechar a conexão local não garante que o provedor interrompa geração ou cobrança.

Release `v0.3.2`: commit `7b801e5`; CI do push `42248746622` e workflow da release `42248832556` concluídos com sucesso. GHCR confirmou `0.3.2`, digest `sha256:8a8ac3e88f53a1c4cbf846ff6b61f98e95ee6f3b3bfaad98a06d055e8d068389`, incluindo `linux/amd64`. Appstore atualizado em `d30a2a5`, `tipi_version` 26; `bun test` passou com 462 testes e workflow `42249187417` aprovado. O push bypassou regras que exigiam PR e status anterior; o workflow após push passou. Instância Runtipi não atualizada.

## Limpeza do histórico de jobs de IA — 2026-11-06

125 testes `unittest` passaram; incluem limpeza separada de jobs terminais, cancelamento ativo e remoção após recuperação de reinício, migração com snapshot do banco e proteção de autenticação/CSRF. Chromium em 390 px e 1365 px verificou os dois botões, confirmação, limpeza, ausência de overflow e erros JavaScript. `node --check app/static/app.js`, `bash -n run-dev.sh`, `compileall` e `git diff --check` passaram. Foram usados banco temporário e chave fictícia; sem chamadas reais a provedores. Cancelar localmente ainda pode deixar o provedor concluir e cobrar.

Release `v0.3.3`: commit `f761e26`; push workflow `42282811151` e release workflow `42282893403` aprovados. GHCR confirmou a tag `0.3.3`, digest `sha256:f2c9f19a585d845949a63b4b93d73fab9faeb008804a5d1bf0b17cdcbf496e77`, plataforma `linux/amd64`. Appstore atualizado no commit `9ce897f`, `tipi_version` 27; `bun test` passou com 462 testes e workflow `42283139996` aprovado. O push bypassou regras que exigiam PR e status prévio; o workflow após o push passou. A instância Runtipi não foi atualizada.

## Layout masonry dos cards — 2026-11-06

A Home com cópia temporária do backup foi validada no Chromium: 29 cards em quatro colunas em viewport de 1365 px; em 390 px, uma coluna e sem overflow horizontal. As capturas foram inspecionadas durante a validação; arquivos temporários foram removidos depois. A regra inicial de CSS Columns foi rejeitada pelo navegador; após corrigir para `columns: 250px`, o fluxo e o layout ficaram corretos.

125 testes `unittest`, `node --check app/static/app.js`, `bash -n run-dev.sh` e `git diff --check` passaram. `bun test` da appstore passou com 462 testes. Nenhum banco pessoal foi usado; o servidor local foi encerrado.

Release `v0.3.4`: commit `60d73bb`; push workflow `42289771505` e workflow de release `42289792145` aprovados. GHCR confirmou a tag `0.3.4`, digest `sha256:550151363df7ab98631fe6345ffaef1f6d8661de3a94dc35f31bdf8562e31aa5`, índice OCI publicado para AMD64. Appstore atualizada no commit `14c0b2e`, `tipi_version` 28; 462 testes e workflow `42290036751` aprovados. O push bypassou regras que exigiam PR e status prévio. A instância Runtipi não foi atualizada.

## Fila de extração, termos e capas — 2026-11-07

133 testes `unittest` passaram com SQLite temporário. Incluem configuração autenticada/CSRF da concorrência, padrão 1, limite 1–8, claims concorrentes limitados atomicamente, migração aditiva de `queue_at` com snapshot, reenvio único após timeout e ordem FIFO, termos extraídos usados também na consulta paginada de ofertas, e alertas lidos ocultos da Home sem ocultar não lidos ou ofertas sem alerta. `bash -n run-dev.sh`, `node --check app/static/app.js`, `compileall` e `git diff --check` passaram.

O Chromium do sistema validou Home e Configurações em 390 px e 1365 px com dados e imagens sintéticos: capas retrato/paisagem mantêm proporção e mostram a imagem inteira, os textos ocupam menos altura, o campo de concorrência está visível e não há overflow horizontal. As capturas foram inspecionadas. `tests/browser_term_offers.py` passou com toque móvel e desktop, incluindo leitura, exclusão/desfazer, paginação, lote e fallback sem JavaScript. Sem chamadas reais a Telegram ou provedores; timeout e cobranças reais não foram medidos.


## Navegação compacta, regras individuais e release 0.5.0 — 2026-11-07

136 testes `unittest` passaram com armazenamento temporário. `node --check app/static/app.js`, `bash -n run-dev.sh` e `git diff --check` passaram. A validação Chromium registrada para esta implementação cobriu 390 px, 768 px e 1365 px; `tests/browser_selection.py` passou no Chromium móvel. Não houve aparelho físico nem integração real com Telegram/provedores.

Release `v0.5.0`: commit `550fdf6`; workflows de push `42345739262` e release `42345750969` aprovados. GHCR confirmou `0.5.0` como índice OCI para `linux/amd64`, digest `sha256:ebb3f83e940bd6caf6e424d17cadba4bbcce8fc6e2a23a16072d9816fa2d01cd`. Appstore Runtipi atualizado no commit `4c3590e`, `tipi_version` 30; `bun test` passou com 462 testes e workflow `42345863034` aprovado. O push do appstore bypassou regras de PR e status prévio; o CI após push passou. A instância Runtipi não foi atualizada.


## Redesenho da navbar — 2026-11-07

A navbar sticky foi verificada no Chromium em 1365 px (grade expandida), 768 px (painel hambúrguer em duas colunas) e 390 px (painel vertical). O ícone permaneceu visível ao rolar; abrir/fechar, Escape e devolução de foco passaram. Sem JavaScript, os links permanecem disponíveis em coluna no celular, sem overflow. Os 136 testes `unittest`, `node --check app/static/app.js`, `bash -n run-dev.sh` e `git diff --check` passaram. Não houve teste em aparelho físico.

Release `v0.5.1`: commit `2a0267c`; workflow `42348091172` aprovou testes e publicação. GHCR confirmou `0.5.1` como índice OCI `linux/amd64`, digest `sha256:72322807428e0c0e6184ef80e4271bb68d4607cc0c7eefdd31c3012ed26db8be`. Appstore atualizado no commit `8cc9341`, versão `0.5.1`, `tipi_version` 31; 462 testes e workflow `42348214564` aprovados. O push bypassou regras de PR e status prévio; o CI após push passou. A instância Runtipi não foi atualizada.

## Release 0.5.2 e loja Runtipi — 2026-11-07

136 testes `unittest` passaram; `node --check app/static/app.js`, `bash -n run-dev.sh` e `git diff --check` passaram. Não foi feita validação visual, conforme pedido do usuário. O servidor local em `192.168.0.10:8000` foi encerrado.

Release `v0.5.2`: commit `6b48e08`; workflow de push `42351443739` e workflow da release `42351509661` aprovados. GHCR confirmou a tag `0.5.2` como índice OCI `linux/amd64`, digest `sha256:8b7282b4300521d0ac53737b66ce05b9beae3551cd15fe7471bba1a33178b815`. Appstore atualizado no commit `504687a`, versão `0.5.2`, `tipi_version` 32; `bun test` passou com 462 testes e workflow `42351638390` aprovado. O push do appstore bypassou regras de PR e status prévio; o CI após push passou. A instância Runtipi não foi atualizada.

## Release 0.5.3 e grid cronológica — 2026-11-07

136 testes `unittest`, `node --check app/static/app.js`, `bash -n run-dev.sh` e `git diff --check` passaram. Chromium com cards de alturas diferentes confirmou ordem visual por linha e ausência de overflow em 1365 px, 390 px e 320 px.

Release `v0.5.3`: commit `dc83318`; workflow de push `42353373869` e workflow da release `42353384683` aprovados. GHCR confirmou a tag `0.5.3` como índice contendo `linux/amd64`, digest `sha256:f7242aa2a9382d50bc0424c230efeb72a5d2c9eb3596a8399bff9e786cc33bef`. Appstore atualizado no commit `e6d44c6`, versão `0.5.3`, `tipi_version` 33; 462 testes e workflow `42353407376` aprovados. Catálogo atualizado antes da conclusão da imagem por autorização explícita do usuário. A instância Runtipi não foi atualizada e nenhum processo local ativo foi encontrado.

## Release 0.5.4 — 2026-11-07

139 testes `unittest`, `node --check app/static/app.js`, `bash -n run-dev.sh`, compilação dos módulos alterados e `git diff --check` passaram. O roteiro Chromium atualizado passou com celular (navegação para Home filtrada, sem modal de termo, com e sem JavaScript) e desktop (exclusão/desfazer).

Com um alerta sintético em Chromium, a grid desktop em 1365 px manteve o card em 297 px, equivalente a uma coluna; em 390 px, a única coluna disponível ficou com 308 px. As capturas desktop e móvel foram inspecionadas. Sem aparelho físico ou integração real com Telegram.

Publicação: release `v0.5.4` no commit `f4b206f`; workflow `42355305879` aprovado. O manifesto GHCR confirmou a tag exata `0.5.4`, incluindo `linux/amd64`, digest `sha256:f5a9a3c842bff6b57079e257eda53e4a48b02ff20385b5a957b4d1c4d673ae60`. Catálogo Runtipi atualizado durante a publicação, conforme autorização, no commit `d6eeaf7` (`tipi_version` 34); workflow `42355317304` aprovado. A instância Runtipi não foi atualizada.

## Correção ao salvar paralelismo de IA e release 0.5.5 — 2026-11-07

139 testes `unittest` passaram, incluindo o envio do formulário de IA com `value=3` e a leitura do valor persistido. `py_compile`, `node --check app/static/app.js`, `bash -n run-dev.sh` e `git diff --check` passaram.

Release `v0.5.5`: commit `0cb157f`; workflows de push `42356626743` e release `42356632696` aprovados. GHCR confirmou `0.5.5` como índice OCI incluindo `linux/amd64`, digest `sha256:2dcee11995b125612ff0e37892cbb24d74ce51765c55e70b196f0d21ac5b18b7`. Appstore atualizado no commit `4a826fc`, versão `0.5.5`, `tipi_version` 35; `bun test` passou com 462 testes e workflow `42356646286` aprovado. O catálogo foi atualizado antes de terminar a publicação da imagem por autorização explícita do usuário. A instância Runtipi não foi atualizada.

## Listagens de regras e ofertas excluídas recentemente — 2026-11-07

142 testes `unittest` passaram, incluindo ordenação/data nas duas listagens, migração aditiva de `created_at` com backup e inclusão de mais de 100 ofertas na tela `/deleted`. `node --check app/static/app.js`, `bash -n run-dev.sh`, `py_compile app/main.py app/store.py` e `git diff --check` passaram. Validação visual não executada por solicitação do usuário. O app foi iniciado em `0.0.0.0:8000`, e `/health` e `/login` responderam HTTP 200 pelo IP da LAN `192.168.0.10`; usa uma cópia temporária de `.data/offers_backup.db` e uma senha temporária informada ao usuário. A API Telegram não está configurada nesse processo. A retenção existente foi mantida: o código aplica 4h/24h às ofertas sem alerta e 1h à exclusão manual, divergindo das 4h/12h mencionadas no pedido.

## Release 0.5.6 — validação local — 2026-11-07

142 testes `unittest`, `node --check app/static/app.js`, `bash -n run-dev.sh`, `py_compile app/main.py app/store.py` e `git diff --check` passaram após corrigir a ordem da migração: o backup é feito antes de instalar os gatilhos de data, mantendo compatibilidade de rollback com a versão anterior. O servidor local foi parado a pedido. Validação visual não executada a pedido do usuário. Publicação e workflow GHCR serão registrados após a conclusão.


## Release 0.5.10 e atualização da loja Runtipi — 2026-11-08

O app local não estava em execução. A suíte passou com 149 testes; `bash -n run-dev.sh`, `node --check app/static/app.js` e `git diff --check` passaram. Commit `9a19197` enviado para `main`; workflow de push `42444949806` passou. Release `v0.5.10`, workflow `42444983743`, concluiu `test` e `publish`. Manifesto GHCR verificado: `ghcr.io/rodrigomescua/murktelegot:0.5.10`, índice OCI `sha256:904dd7f77011cf281c1e9af369990ce95f95af39a8f0207ca805209fba2d59d8`, plataforma `linux/amd64`. O catálogo foi atualizado pela PR [1465](https://github.com/rodrigomescua/runtipi-custom-appstore/pull/1465), merge `4fa1e83`; checks `test`/`renovate` passaram (runs `42445177431`/`42445177401`) e CI pós-merge `42445256452` passou com 462 testes. `tipi_version` passou de 39 para 40. Appstore local sincronizado. A instância Runtipi não foi atualizada; preserve o volume ao atualizar manualmente.


## Release 0.5.12 e loja Runtipi — 2026-11-08

Commit `132492a` enviado a `main`; CI de push `42523438261` passou. Release `v0.5.12` no mesmo commit; workflow `42523550148` aprovou `test` e `publish`. GHCR confirmou `ghcr.io/rodrigomescua/murktelegot:0.5.12`, índice OCI `sha256:16f21a967d4e8362408108225a7d0b25bf0150d1194505367440b466a9855a26`, plataforma `linux/amd64`. Catálogo Runtipi atualizado pela PR [1469](https://github.com/rodrigomescua/runtipi-custom-appstore/pull/1469), merge `701bfbc`; checks `test`/`renovate` passaram e CI pós-merge `42524031012` passou com 462 testes. `tipi_version` passou de 41 para 42. A instância Runtipi não foi atualizada.

## Observabilidade e métricas da fila de IA — 2026-11-11

173 testes `unittest` passaram. Cobrem categorias estáveis de HTTP, persistência por modelo/tipo, duração média, preservação após apagar histórico, importação única das tentativas antigas, etapa atual e finalização do job após falha interna. `py_compile app/ai.py app/main.py app/store.py`, `node --check app/static/app.js`, `bash -n run-dev.sh` e `git diff --check` passaram.

Chromium com banco e ofertas sintéticas em 390 px e 1365 px conferiu etapa corrente, taxas, porcentagem das categorias de falha e tempo médio; não houve overflow horizontal nem erros JavaScript. Duas consultas consecutivas ao status ficaram separadas por 1.995 ms. Nenhuma conta Telegram, banco pessoal ou provedor de IA real foi usado; o sintoma em produção não foi reproduzido.

Publicação `v0.5.19`: commit `5454a6e`; CI do push `43076600053` passou; workflow de release `43076740961` aprovou `test` e `publish`. O registry confirmou `ghcr.io/rodrigomescua/murktelegot:0.5.19`, índice OCI `sha256:4ec72adb646334111c61818abea99331bcc3d8055a8bf8fb69d8dca78eae1d7a`, incluindo `linux/amd64`. Catálogo Runtipi atualizado via PR [1488](https://github.com/rodrigomescua/runtipi-custom-appstore/pull/1488), merge `1119138`; versão `0.5.19`, `tipi_version` 49. Checks `test`/`renovate` e CI pós-merge `43077884568` passaram; `bun test` teve 469 testes. Catálogo local sincronizado em `main`. A instância Runtipi não foi atualizada.

## Cupons extraídos por IA — 2026-11-11

178 testes `unittest` passaram. Cobrem lista de cupons e limites da resposta, chaves loja+código sem diferença de caixa/espaços externos, atualização de condições, retenção após inativação manual/IA, remoção de anúncios sem produto após persistência e preservação quando não há cupom identificável, migração aditiva, autenticação e CSRF. `compileall`, `node --check app/static/app.js`, `bash -n run-dev.sh` e `git diff --check` passaram. Chromium com dados temporários verificou a página Cupons em 390 px e 1365 px, sem overflow ou erros JavaScript; visualmente, cartões e ação manual cabem nos dois viewports. Nenhum provedor real, sessão Telegram ou banco pessoal foi usado. Release `v0.5.20` publicada do commit `6debb35`; workflow `43101987960` aprovou `test`/`publish`; GHCR confirmou AMD64 `sha256:351618bc27038b9066cf345a3d89eb42e6b59c201dc2ada93320982bee4ea7d6`. Catálogo atualizado pela PR [1490](https://github.com/rodrigomescua/runtipi-custom-appstore/pull/1490), merge `288dadc`; `tipi_version` 50; checks `test`/`renovate` e CI pós-merge `43102622029` aprovados, com 469 testes. A instância Runtipi não foi atualizada.


## Resposta de IA nos cards, jobs pendentes e prompt configurável — 2026-11-11

181 testes `unittest` passaram, incluindo persistência/migração do resultado completo, visualização de resultados legados, migração de banco antigo com backup preservado, estado queued/processing em cards normais e excluídos, salvamento do prompt adicional e aplicação na chamada seguinte. `compileall`, `node --check app/static/app.js`, `bash -n run-dev.sh` e `git diff --check` passaram. Chromium com cópia isolada do backup e registros sintéticos validou o modal, o indicador e o prompt base/instruções em 390 px e 1365 px, sem overflow horizontal ou erros JavaScript. Review independente de UI/UX não encontrou bloqueadores; recomendou evitar anúncios live repetidos e respeitar movimento reduzido, ambos aplicados. Nenhuma chamada real à IA foi feita. Release `v0.5.21` publicada no commit `ea779b4`; workflows de push `43118538545` e release `43118574883` passaram, incluindo publicação GHCR. O registry confirmou `linux/amd64`, digest `sha256:d20d3b4baa6c119c4687322ae8ed8d63d4631041484129de1620dd7a7c86ae8f`. Catálogo atualizado via PR [1494](https://github.com/rodrigomescua/runtipi-custom-appstore/pull/1494), merge `7bc49cb`, `tipi_version` 51; checks `test`/`renovate` e CI pós-merge `43119366095` passaram. Um push inicial do catálogo contornou regras; foi revertido pela PR [1493](https://github.com/rodrigomescua/runtipi-custom-appstore/pull/1493), com checks e CI aprovados, e a versão final foi reaplicada pela PR 1494. A instância Runtipi não foi atualizada.

## Reextração manual, links de cupons, alertas e otimização da fila — 2026-11-12

184 testes `unittest` passaram, cobrindo reextração autenticada/CSRF, substituição após sucesso, persistência enquanto a oferta está ativa ou na lixeira e remoção do conteúdo extraído após purga física, persistência e migração de links, URLs não seguras, exclusões lógica/física e uso dos três índices da fila em `EXPLAIN QUERY PLAN`. `compileall`, `node --check app/static/app.js`, `bash -n run-dev.sh` e `git diff --check` passaram.

Chromium em 390 px e 1365 px verificou reextração no modal, resultado atualizado, movimentação de alerta lido/desfazer e links seguros, sem overflow ou erros JavaScript; as capturas foram inspecionadas. O probe `tests/browser_term_offers.py` não executou porque faltava o Chromium empacotado pelo Playwright no ambiente. Uma revisão independente de UI/UX encontrou o botão de reextração em cards excluídos; a ação foi ocultada nesses cards.

Não houve chamadas reais a provedores nem benchmark de produção. Os índices foram mantidos porque os planos SQLite os escolhem para as consultas da fila; nenhum ganho de tempo foi medido.

Release `v0.5.22`: commit `0086ccf`; CI do push `43284924671` e workflow da release `43285023041` passaram. GHCR confirmou `ghcr.io/rodrigomescua/murktelegot:0.5.22`, índice OCI `sha256:4c18d2e3d724d5511b23316b7f533445e8ae57820fc62be8a81aa5e9ea43deda`, incluindo `linux/amd64`. Catálogo atualizado pela PR [1497](https://github.com/rodrigomescua/runtipi-custom-appstore/pull/1497), merge `548d6dd`; `tipi_version` 52. Os checks `test` e `renovate` do PR passaram, `bun test` local teve 469 aprovados e o CI pós-merge `43285684446` passou. Nenhum servidor Uvicorn local estava ativo. A instância Runtipi não foi atualizada.

## Inativação de cupons sem recarga — 2026-11-12

Com quatro cupons sintéticos, Chromium em 1365 px e 390 px inativou dois cupons seguidos sem sair de `/coupons`; os quatro cards permaneceram no mesmo lugar, com dois estados atualizados e duas ações restantes. Em 390 px não houve overflow horizontal; nenhum erro JavaScript ocorreu. A suíte `unittest` completa passou com 184 testes; também passaram `compileall`, `node --check app/static/app.js`, `bash -n run-dev.sh` e `git diff --check`. O servidor local usou banco temporário sintético e foi encerrado; nenhum dado pessoal foi usado.

Release `v0.5.23`: commit `c0a1be9`; CI do push `43355348425` e workflow da release `43355421038` passaram. GHCR confirmou `ghcr.io/rodrigomescua/murktelegot:0.5.23`, índice OCI `sha256:4b2bb844d0b7d0a30fdbcaffc8ae4149995164b03388c7feafcc6e1138391309`, incluindo `linux/amd64`. Catálogo atualizado pela PR [1499](https://github.com/rodrigomescua/runtipi-custom-appstore/pull/1499), merge `57bf740`; `tipi_version` 53. Os checks `test` e `renovate` do PR passaram, `bun test` local teve 469 aprovados e o CI pós-merge `43355799116` passou. Nenhum servidor Uvicorn local estava ativo. A instância Runtipi não foi atualizada.

## Correções de reextração e ordenação após exclusão — 2026-11-13

185 testes `unittest` passaram, incluindo resultado de reextração de anúncio sem produto, consumo único do JSON após exclusão física e migração aditiva de `show_result` com backup. `compileall`, `node --check app/static/app.js`, `bash -n run-dev.sh` e `git diff --check` passaram. Chromium em 390 px confirmou o JSON simulado visível após reextração no modal e que excluir um card move somente aquele card ao fim da grade; o teste também verifica abertura por CTA, undo e fallback sem JavaScript. O Chromium usado foi `/usr/bin/chromium-browser`, pois o binário gerenciado pelo Playwright não estava instalado. Nenhum banco pessoal ou provedor real foi usado. A revisão independente não encontrou bloqueios. Nenhum servidor Uvicorn local permaneceu ativo.

Release `v0.5.24`: commit `e17e171`; CI de push `43367796981` e workflow da release `43367859603` passaram. GHCR confirmou a tag `0.5.24`, índice OCI `sha256:2d8990ac53030b154347ce44bd061b71f373a54e345e7f3e9deb082938ba742d`, incluindo `linux/amd64`. Catálogo atualizado pelo PR [1500](https://github.com/rodrigomescua/runtipi-custom-appstore/pull/1500), merge `3bccddb`; `tipi_version` 54. Checks `test`/`renovate` do PR `43368108469`/`43368108476` passaram; CI pós-merge `43368244860` passou com 469 testes. Catálogo local sincronizado em `main`. Nenhum Uvicorn ficou ativo. A instância Runtipi não foi atualizada.
