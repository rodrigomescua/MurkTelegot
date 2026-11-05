---
name: murktelegot-alertas
description: Altere alertas, palavras ignoradas, termos frequentes ou notificações do MurkTelegot preservando dados, agrupamento e regras de correspondência. Não use para tarefas somente visuais ou de release.
---

# Alertas e filtros do MurkTelegot

Use somente no repositório MurkTelegot; siga `AGENTS.md` e confirme o comportamento atual no código. Antes da delegação, use `codebase-memory` para localizar responsáveis e chamadores e conferir cobertura, com leitura direta das lacunas.

1. Delegue um escopo coerente de implementação a um agente `worker`, preferindo `model="gpt-6-luna"` e `fork_turns="none"`. Informe caminho absoluto, pedido, aceite, arquivos de responsabilidade, evidências já verificadas e restrições. Diga que não está sozinho, que não deve reverter edições alheias ou alterar a memória do projeto e que deve acomodar alterações concorrentes. Se Luna ou delegação não estiver disponível, use o modelo disponível ou implemente diretamente e informe a limitação.
2. Preserve identidade `(chat_id, message_id)`, edições e recálculo atômico; palavras ignoradas filtram a lista principal antes do limite, não os alertas. O agrupamento deve considerar todas as partes e manter estado de leitura coerente. Não processe dados pessoais, sessões Telegram ou bancos reais em testes.
3. Para Gotify, mantenha token fora de logs e respostas, alertas mesmo em ofertas ignoradas e proteção contra notificações duplicadas. Mudanças em esquema devem ser aditivas ou seguir uma migração com preservação e rollback comprovados.
4. O responsável principal integra e executa os testes focados e a suíte pertinente diretamente com Python, sem Docker. Atualize a documentação e memória relativas ao comportamento alterado; não publique sem pedido.
