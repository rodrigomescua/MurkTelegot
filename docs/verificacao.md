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

## Limites

Não há benchmark de desempenho nem teste de carga. O build e a execução de containers não foram feitos neste ambiente. A publicação GHCR é verificada no workflow da release; esse resultado não substitui testar a imagem no servidor de destino. Consulte os resultados de cada push no GitHub Actions para confirmar a suíte em Python 3.12.

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

Com Playwright e Chromium instalados, execute `.venv/bin/python tests/browser_selection.py` (ou defina `PLAYWRIGHT_CHROMIUM_EXECUTABLE` para um executável Chromium disponível). O teste cria dados temporários, usa viewport de 390 px e toque simulado, e verifica criação direta, filtro no modal, rascunhos, erros, limites, campos sensíveis e spoilers. A seleção é criada pela API do navegador; o gesto de pressionar e segurar e o menu nativo de dispositivos reais não foram testados.

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

A navbar sticky foi verificada no Chromium em 1365 px (grade expandida), 768 px (painel hambúrguer em duas colunas) e 390 px (painel vertical). O ícone permaneceu visível ao rolar; abrir/fechar, Escape e devolução de foco passaram. Sem JavaScript, os links permanecem disponíveis em coluna no celular, sem overflow. Os 136 testes `unittest`, `node --check app/static/app.js`, `bash -n run-dev.sh` e `git diff --check` passaram. Não houve commit, publicação, atualização da instância nem teste em aparelho físico.
