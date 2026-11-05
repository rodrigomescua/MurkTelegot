---
name: murktelegot-interface
description: Implemente ou ajuste interface, acessibilidade e experiência móvel do painel MurkTelegot, incluindo verificação no Chromium quando pertinente. Não use para mudanças exclusivas de backend ou publicação.
---

# Interface do MurkTelegot

Trabalhe somente no MurkTelegot e respeite `AGENTS.md`. Antes de delegar, identifique os arquivos afetados, chamadores, dados e a cobertura do grafo conforme a skill `codebase-memory`.

1. Delegue a implementação delimitada a um agente `worker` com `model="gpt-6-luna"` e `fork_turns="none"`, quando disponível. Forneça caminho absoluto, pedido e aceite, arquivos de responsabilidade, evidências de exploração, testes e restrições. Diga que há outras pessoas/agentes no repositório, que não deve reverter mudanças alheias nem alterar a memória do projeto, e que deve acomodar trabalho concorrente. Se a delegação ou Luna não estiver disponível, use o modelo disponível ou implemente diretamente e informe a limitação.
2. Preserve interface em português, CSS local, escape HTML, CSRF, autenticação, rascunhos, spoilers e segredos. JavaScript deve aprimorar os fluxos existentes sem quebrar formulários ou navegação sem ele. Não exponha implementação no fluxo do produto.
3. O responsável principal integra e verifica as mudanças; execute Python e `node --check` diretamente, sem Docker. Para mudanças de interação móvel, confira Chromium em viewport de 390 px e toque simulado quando disponível; use `tests/browser_selection.py` se o fluxo de seleção for afetado. Diferencie seleção simulada de gesto nativo em aparelho real.
4. Atualize somente documentos e memória afetados; relate provas, limitações reais e comportamento que passou a funcionar. Commit, push e release exigem solicitação correspondente.
