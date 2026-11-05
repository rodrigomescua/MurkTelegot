# Operação e recuperação

A instalação e as variáveis estão no [README principal](../README.md#produção-imagem-pronta). Nenhum `.env` é necessário em produção; edite as variáveis no próprio Compose do servidor e mantenha esse arquivo com credenciais fora do Git.

## Publicação

O push em `main` executa testes. Para gerar uma imagem, publique uma release estável com tag semântica, como `v0.0.1`. O workflow usa `GITHUB_TOKEN` com `packages: write` para publicar tags `0.0.1`, `0.0` e `latest` no GHCR, com o proprietário e nome do repositório em minúsculas. Pre-releases não publicam imagens.

Em repositório/pacote privado, autentique o servidor no GHCR com permissão de leitura do pacote. O login local do painel e a autenticação do registry são credenciais distintas. Não altere a visibilidade do pacote como solução automática para falhas de autenticação.

## Persistência e backup

Em desenvolvimento, os dados ficam em `.data/`; no container, em `/data`, montado pelo volume `murktelegot_data`. Guarde o diretório completo, incluindo banco de ofertas, sessão Telegram e eventuais arquivos auxiliares do SQLite. Pare o app antes de copiar o diretório para obter um backup consistente. Proteja também o backup, pois ele contém acesso à conta e mensagens privadas.

Não execute duas instâncias/replicas sobre o mesmo conjunto de dados. Alterações de grupos interrompem somente a coleta futura; as ofertas já salvas permanecem. Palavras ignoradas ficam no banco e só ocultam ofertas da listagem principal; não excluem ofertas ou alertas. As tabelas do filtro e das sugestões ocultas são criadas de forma aditiva; versões anteriores ignoram a tabela de sugestões, sem apagá-la nem alterar os dados existentes.

## Atualização e rollback

1. Pare o app e faça backup completo do diretório de dados; registre a tag atual da imagem.
2. Troque a tag no Compose, execute `docker compose pull` e `docker compose up -d`.
3. Confira `/health`, autenticação no painel, conexão Telegram e grupos selecionados. `/health` não atesta conectividade Telegram.
4. Se precisar voltar, pare o app, restaure o backup e a tag anteriores e só então reinicie. A migração de mensagens cria um snapshot SQLite em `offers.db.before-rich-messages.db` antes de adicionar colunas; restaure o backup completo anterior junto com a imagem antiga. Dados recebidos após o backup não estarão nele: preserve também uma cópia do volume atual antes de voltar.

Preserve o volume: `docker compose down -v` remove os dados. A base ainda não possui limpeza automática; acompanhe espaço disponível. Uma sessão comprometida pode ser revogada em Telegram → Configurações → Dispositivos.

## Aviso conhecido do Telethon

No Telethon 1.40.0, o aviso `Using async sessions support is an experimental feature` também é emitido durante o processamento assíncrono interno de atualizações, mesmo com sessão comum. Foi reproduzido sem rede; sozinho não indica falha de login. Não foi suprimido e a dependência não foi alterada. Verifique o estado no painel e eventuais erros adicionais.

## Mídias e mensagens antigas

Conteúdo original e metadados ficam no SQLite; mídia é obtida do Telegram no primeiro acesso e guardada em `/data/media`, acessível apenas mediante autenticação. O servidor mantém ao menos 64 MiB livres e interrompe downloads que excedam 120 segundos. Se o original tiver sido removido ou alterado antes do primeiro acesso, use o link do Telegram ou atualize a mensagem. Não há limpeza automática de mídia.

Em mensagens coletadas antes desta versão, use **Recuperar original** para buscar individualmente o conteúdo atual e os itens do mesmo álbum, quando disponíveis no Telegram. O grupo deve estar selecionado; não há importação geral automática.

## Gotify

A configuração do Gotify é feita no painel e fica no banco do volume, incluindo o token em texto legível para o processo; proteja o diretório e os backups. A URL precisa ser acessível a partir do processo/container. A tabela de configurações é aditiva; versões anteriores ignoram seus registros. Envios usam uma tentativa por novo alerta e um timeout de cinco segundos; falhas são registradas sem o token e não removem alertas nem são reenviadas automaticamente. O teste em Configurações mostra um diagnóstico persistente (código HTTP ou categoria de rede/TLS); o log também informa a categoria, sem incluir URL, token, corpo da resposta ou conteúdo da oferta.
