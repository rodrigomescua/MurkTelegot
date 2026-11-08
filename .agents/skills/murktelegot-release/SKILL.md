---
name: murktelegot-release
description: Prepare e publique releases do MurkTelegot quando o usuário solicitar uma release, incluindo validação, commit, push e acompanhamento da imagem GHCR. Não use para simples alterações locais.
---

# Release do MurkTelegot

Use somente no repositório MurkTelegot e publique apenas com solicitação do usuário. Siga `AGENTS.md`, inclusive a memória do projeto. A versão deve ser a pedida ou a próxima versão estável compatível com as tags existentes.

1. Delegue a um agente de verificação somente leitura o inventário do diff, testes e riscos de entrega. Prefira `collaboration.spawn_agent` com `model="gpt-6-luna"` e `fork_turns="none"`; forneça o caminho absoluto do repositório, o pedido, a versão, o escopo e as restrições. Se Luna ou delegação estiver indisponível, use o modelo disponível ou faça a verificação diretamente e informe a limitação.
2. O agente não altera arquivos, memória, Git ou serviços externos. O responsável principal revisa o resultado, preserva alterações alheias e conclui a documentação e a nota de sessão.
3. Confira branch, status, tags, versão publicada e `.github/workflows/release.yml`. Ajuste o `docker-compose.yml` de exemplo para a versão solicitada, mantendo imagem pré-buildada, variáveis no próprio Compose e AMD64. Valide diretamente com Python e verificações pertinentes, sem Docker local nem dados pessoais.
4. Revise e adicione somente arquivos autorizados; crie o commit e envie a branch. Publique a release estável para o commit enviado, com notas que descrevam as mudanças reais. Não altere visibilidade de repositório ou pacote. Para atualização do catálogo Runtipi, siga a preferência explícita do usuário: commit e push diretamente para `main`, sem PR. Confira a proteção; nunca a contorne. Se o push direto for bloqueado, pare e informe, sem abrir PR até nova instrução do usuário.
5. Acompanhe o workflow da release até confirmar testes e publicação GHCR, ou relate precisamente o estágio que falhou. Registre somente provas executadas. Informe a tag da imagem, como atualizar o Compose de produção e riscos materiais; preserve o volume.
