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

Testes com dados temporários verificam que ofertas ignoradas e álbuns com partes ignoradas não entram nas frequências; palavras e expressões inteiras contidas em sugestões ocultas deixam de aparecer, com restauração e alertas preservados.

## Notificações Gotify

Testes com dados temporários e servidor HTTP local simulado verificam configuração, autenticação, CSRF, sigilo do token na resposta, envio, recusa de redirecionamento, alertas ignorados, edições e falhas. Chromium em 390 px verificou a tela e o envio de teste simulado. Não foi testado um servidor Gotify real nem Docker.

## Formatação Gotify

Testes com dados temporários verificam metadados Markdown no protocolo Gotify, entidades UTF-16, links seguros, texto escapado, código, citações, spoilers ocultos e indicação de mídia. A exibição em clientes Gotify reais não foi testada.

## Diagnóstico Gotify

Testes simulam respostas HTTP, falhas de DNS, timeout, conexão recusada e TLS, verificam detalhes na tela e no log e ausência de token e texto privado. Chromium com servidor local simulado verificou erro HTTP persistente e sigilo. A falha relatada em produção não foi reproduzida nem identificada neste ambiente.
