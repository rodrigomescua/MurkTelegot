# MurkTelegot — contrato do projeto

## Propósito e propriedade

App pessoal para acompanhar ofertas em grupos e canais Telegram usando a conta do usuário. A raiz mantém código, testes, distribuição, documentação e o pacote visual em `assets/`. Não há contratos filhos; este arquivo é o índice e contrato operacional para todo o repositório.

## Orientações de trabalho

- Para exploração estrutural, use a skill instalada `codebase-memory`. Verifique cobertura e consulte diretamente fontes ausentes ou desatualizadas.
- Para tarefas recorrentes, use as skills em `.agents/skills/`: `murktelegot-release`, `murktelegot-interface`, `murktelegot-alertas` e `murktelegot-diagnostico` quando aplicáveis. Ao delegar, prefira `gpt-6-luna` quando disponível; se indisponível, use outro modelo disponível e informe a limitação.
- Leia o código responsável e seus chamadores antes de alterar comportamento. Faça a menor mudança completa e preserve validação, autenticação, dados e tratamento de erros.
- Sempre que uma alteração mudar interface ou layout, faça validação visual no Chromium antes de entregar, incluindo o viewport móvel quando pertinente; não considere testes automatizados substitutos dessa validação.
- Execute o app e os testes diretamente com Python neste ambiente. Não use Docker ou Docker Compose para testes locais.
- Produção usa imagem pré-buildada e todas as variáveis no próprio `docker-compose.yml`. Não introduza `build:`, `env_file:` ou dependência de `.env` em produção.
- Não versione credenciais, códigos, senhas reais, mensagens privadas, bancos, sessões Telegram, `.data/`, `.venv/` ou índices locais de ferramentas.
- Comunique em português: resposta ou próxima ação primeiro, progresso explícito, passos numerados e curtos, até cinco itens por lista e uma próxima ação de menos de dois minutos. Confirme ações destrutivas; após três correções sem sucesso, pare e identifique a premissa duvidosa.

## Estrutura e contratos

- `app/main.py`: FastAPI, autenticação por página de login e sessão em cookie, CSRF, rotas e respostas HTML/JSON. Senha própria com mínimo de 12 caracteres. `/health` mede o processo web, não o Telegram.
- `app/telegram.py`: cliente Telethon, login telefone → código → senha opcional, conexão e eventos; envia alertas novos e retroativos ao Gotify quando habilitado, sem duplicar notificações em reprocessamentos ou partes do mesmo álbum. Com `APP_PUBLIC_URL` HTTPS, Gotify recebe miniaturas não-spoiler por links HMAC temporários de 24h; link permite leitura sem login. Login em andamento pertence à memória de uma única instância; a sessão concluída pertence ao diretório de dados.
- `app/store.py`: SQLite, índice de ordenação de ofertas, configurações Gotify e IA, jobs de extração FIFO retomados após reinício, normalização, correspondências, backup antes da migração e transações. Dados extraídos são invalidados em edições ou novas partes do álbum; respostas em andamento verificam o texto antes de gravar para descartar resultados obsoletos. Criar regra recalcula hits nas ofertas existentes, inclusive ignoradas; mensagens futuras e edições também aplicam regras. Palavras ignoradas ficam em tabela própria e filtram somente a listagem principal, antes do limite; sugestões de termos ocultos ficam em tabela independente e não afetam ofertas ou alertas; a frequência considera apenas ofertas não ignoradas e exclui termos inteiros contidos nas sugestões ocultas; qualquer parte correspondente oculta o álbum inteiro. Alertas/hits e contagem não são filtrados. A página de alertas separa lidos e não lidos antes do limite, considerando todas as partes do álbum. Só armazene mensagens de grupos selecionados. Identidade de oferta: `(chat_id, message_id)`; edições atualizam a mesma oferta e recalculam correspondências atomicamente.
- Extração por IA é automática para novas ofertas não ignoradas recebidas do Telegram, incluindo álbuns após o evento completo; provedor deve estar configurado. Jobs manuais também processam até 100 cards do feed padrão, em ordem FIFO. Ordem, modelos e chaves são consultados antes de cada chamada; mudanças salvas valem na próxima tentativa. Jobs pendentes ou em andamento podem ser cancelados; cancelar interrompe a conexão HTTP local em voo e descarta a resposta. O provedor ainda pode concluir o processamento e cobrar. Extrações contêm somente título do produto, preços e cupom, têm prioridade nos cards da Home, Alertas e ofertas de termos, e não substituem a mensagem original no modal.
- Retenção: usa `offers.date`; ofertas sem alerta ignoradas por palavra são apagadas após 4 horas e demais ofertas sem alerta após 24 horas. Qualquer alerta protege álbum inteiro até exclusão lógica; exclusões ficam ocultas em todas as listagens e contagens, podem ser desfeitas na tela atual e são apagadas fisicamente após uma hora (limpeza a cada cinco minutos), incluindo hits. Links de mídia deixam de funcionar enquanto a oferta está excluída.
- `app/messages.py`: metadados originais e renderização segura das entidades UTF-16; valide URLs e escape texto antes de marcar HTML como seguro. Mídias privadas usam rota autenticada e cache no volume; miniaturas Gotify usam rota pública apenas com assinatura HMAC temporária.
- `app/templates/` e `app/static/`: interface em português, HTML escapado, JavaScript progressivo e CSS local; navegação, páginas próprias para regras de alerta, grupos, palavras ignoradas, termos frequentes e configurações e processamento de IA. Erros de login mantêm os campos no DOM; não grave segredos em armazenamento do navegador nem os reflita em respostas. Cards mostram capa e duas linhas não vazias, mantendo spoilers ocultos, leitura direta do alerta no card e conteúdo em modal acessível, com details como alternativa sem JavaScript. Ações por seleção não devem ler campos editáveis nem spoilers ocultos.
- `tests/`: testes `unittest`, dados temporários e Telegram simulado. Não use a sessão ou o banco pessoal em verificações automatizadas.

Identidade visual: os arquivos canônicos em `assets/murktelegot-logo/` são servidos por `/brand/` e copiados pelo Dockerfile. Não duplique os vetores em `app/static/`. Cabeçalho/favicon usam esses SVGs; a paleta do painel tem destaque `#2AABEE`, branco e fundos escuros azulados.

## Execução e verificação

```bash
./run-dev.sh
.venv/bin/python -m unittest discover -s tests -v
bash -n run-dev.sh
node --check app/static/app.js
```

`run-dev.sh` cria o ambiente quando necessário, solicita credenciais e inicia Uvicorn no loopback. Dados locais em `.data/`. Produção usa Python 3.12, usuário sem privilégios, um processo/replica e volume `/data`. Comandos de instalação e operação estão em `README.md`.

## Distribuição

O workflow `.github/workflows/release.yml` testa pushes em `main`/`master` e pull requests. Uma release estável publicada dispara, após testes, a publicação GHCR para AMD64 (`linux/amd64`) com tags semânticas e `latest`. Push inicial não publica imagem. Não crie release nem altere visibilidade sem solicitação. Preserve o volume em atualizações; rollback restaura imagem e backup compatíveis.

## Documentação e decisões

- `README.md`: entrada para uso, instalação e limitações.
- `docs/README.md`: navegação; `docs/architecture/`: ADRs; `docs/plans/`: planos e aceite; `docs/operacao.md`: operação e recuperação; `docs/verificacao.md`: evidências e limites dos testes.
- Durante a implementação, não mantenha documentação sincronizada. Ao concluir código e verificações, revise este contrato e atualize de uma vez somente documentos responsáveis por fatos alterados. Registre decisões arquiteturais em ADRs com contexto, decisão e consequências; correções rotineiras não exigem ADR.
- Não invente medições de desempenho nem apresente testes simulados como integração real. Crie `docs/performance/` quando houver uma medição reproduzível.

## Memória persistente no Obsidian

Use somente `/home/rodrigo/Obsidian/Personal/Dev/Projetos/MurkTelegot`. Padrão compartilhado: `/home/rodrigo/Obsidian/Personal/Dev/Projetos/Projetos.md`. Diretrizes da memória: `AGENTS.md` dessa pasta. Não altere a vault Work ou outros projetos.

1. Antes da tarefa, leia `MurkTelegot.md`, `AGENTS.md`, `Contexto.md`, `Decisões.md`, `Bugs e TODOs.md`, `Sessões.md` e a sessão mais recente. Confirme fatos técnicos no repositório.
2. Crie uma nota `Sessões/AAAA-MM-DD-slug.md` antes das alterações, com pedido, estado observado, aceite, plano e limites. Atualize nos marcos e ao concluir; `Sessões.md` guarda somente o índice.
3. Atualize contexto, decisões e pendências quando o estado mudar. Preserve notas do usuário e histórico concluído. Revise links e registre apenas verificações executadas. Se a memória estiver indisponível, continue trabalho independente e informe a atualização pendente.

## Índice de contratos filhos

Nenhum. A raiz é responsável por `app/`, `tests/`, `docs/`, `assets/`, scripts e configuração de entrega.
