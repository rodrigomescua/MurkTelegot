# Operação e recuperação

A instalação e as variáveis estão no [README principal](../README.md#produção-imagem-pronta). Nenhum `.env` é necessário em produção; edite as variáveis no próprio Compose do servidor e mantenha esse arquivo com credenciais fora do Git.

## Publicação

O push em `main` executa testes. Para gerar uma imagem, publique uma release estável com tag semântica, como `v1.0.0`. O workflow usa `GITHUB_TOKEN` com `packages: write` para publicar tags `1.0.0`, `1.0` e `latest` no GHCR, com o proprietário e nome do repositório em minúsculas. Pre-releases não publicam imagens.

Em repositório/pacote privado, autentique o servidor no GHCR com permissão de leitura do pacote. O login local do painel e a autenticação do registry são credenciais distintas. Não altere a visibilidade do pacote como solução automática para falhas de autenticação.

## Persistência e backup

Em desenvolvimento, os dados ficam em `.data/`; no container, em `/data`, montado pelo volume `murktelegot_data`. Guarde o diretório completo, incluindo banco de ofertas, sessão Telegram e eventuais arquivos auxiliares do SQLite. Pare o app antes de copiar o diretório para obter um backup consistente. Proteja também o backup, pois ele contém acesso à conta e mensagens privadas.

Não execute duas instâncias/replicas sobre o mesmo conjunto de dados. Alterações de grupos interrompem somente a coleta futura; as ofertas já salvas permanecem.

## Atualização e rollback

1. Pare o app e faça backup completo do diretório de dados; registre a tag atual da imagem.
2. Troque a tag no Compose, execute `docker compose pull` e `docker compose up -d`.
3. Confira `/health`, autenticação no painel, conexão Telegram e grupos selecionados. `/health` não atesta conectividade Telegram.
4. Se precisar voltar, pare o app, restaure o backup e a tag anteriores e só então reinicie. A versão inicial não possui migrações de esquema.

Preserve o volume: `docker compose down -v` remove os dados. A base ainda não possui limpeza automática; acompanhe espaço disponível. Uma sessão comprometida pode ser revogada em Telegram → Configurações → Dispositivos.

## Aviso conhecido do Telethon

No Telethon 1.40.0, o aviso `Using async sessions support is an experimental feature` também é emitido durante o processamento assíncrono interno de atualizações, mesmo com sessão comum. Foi reproduzido sem rede; sozinho não indica falha de login. Não foi suprimido e a dependência não foi alterada. Verifique o estado no painel e eventuais erros adicionais.
