# ADR-0001: Conta Telegram, SQLite local e container único

- Status: aceita
- Data: 2026-11-04

## Contexto

O usuário acompanha mais de 30 grupos de ofertas de terceiros e precisa de uma visão unificada com alertas por palavras-chave. Adicionar um bot a cada grupo depende de autorização dos responsáveis. A implantação deve consumir uma imagem pronta, publicada por GitHub Actions a partir de uma release.

## Decisão

Usar a conta Telegram do usuário por Telethon. O painel conduz telefone, código e verificação em duas etapas quando necessária. Eventos de novas mensagens e edições entram no SQLite somente quando o grupo está selecionado. Não há importação de histórico nem garantia de recuperar o intervalo offline.

Um único processo FastAPI serve HTML/Jinja, CSS e JavaScript locais e mantém a conexão Telegram. SQLite guarda grupos, regras, ofertas e correspondências. A identidade `(chat_id, message_id)` evita duplicatas; atualizar o texto e recalcular correspondências acontece na mesma transação. Alertas são exibidos no painel; entrega externa não faz parte desta versão.

Palavras-chave são alternativas separadas por vírgula, com limites de palavra e normalização de caixa/acentos. Regras novas se aplicam a mensagens futuras e futuras edições. Desselecionar grupos e remover regras preserva as ofertas existentes.

Proteger o painel com HTTP Basic (substituído pelo [ADR-0003](ADR-0003-login-painel.md)), senha própria de pelo menos 12 caracteres e CSRF nas mutações. Publicar a porta no loopback; acesso remoto passa por túnel SSH ou HTTPS. Códigos e senhas não são gravados no navegador; o estado temporário do login fica na instância, e a sessão concluída em arquivo persistente.

Distribuir um container sem privilégios com Python 3.12 e volume `/data`. O Compose usa apenas imagem pré-buildada e variáveis diretamente em `environment`, sem `.env` em produção. Testes e execução neste ambiente usam Python diretamente. Releases estáveis publicadas acionam testes e publicação GHCR para AMD64 (`linux/amd64`).

## Consequências

Não é necessário instalar um bot nos grupos nem operar um banco separado. A sessão salva permite reconectar após reinício, mas dá acesso à conta e deve ser protegida como uma credencial. Uma única instância/worker evita dividir o estado do login e compartilhar a sessão entre processos.

O painel mostra até 100 mensagens por consulta; a base não tem limpeza automática. A decisão de não baixar mídia foi substituída pela [ADR-0002](ADR-0002-conteudo-mensagens-telegram.md). Não há extração de preço, notificações externas nem sincronização de exclusões. Backup, monitoramento de disco e futuras migrações exigem cuidado operacional; veja [operação](../operacao.md).

## Revisão de 2026-11-04 — primeira release

A versão inicial é `0.0.1`. Por solicitação do usuário, publicar somente `linux/amd64` e remover QEMU para reduzir trabalho no build. ARM64 pode ser incluído quando houver demanda; não há suporte a ARM64 nesta release.
