---
name: murktelegot-diagnostico
description: Investigue lentidão, erros de produção ou falhas de integração do MurkTelegot com evidência reproduzível e diagnóstico sem segredos. Não use para criação de recursos sem problema relatado.
---

# Diagnóstico do MurkTelegot

Siga `AGENTS.md` e investigue a causa antes de editar. Distingua evidência local da situação de produção; não infira causa específica de um código HTTP ou de uma medição simulada.

1. Use `codebase-memory` para localizar responsáveis e chamadores, rastrear comportamento e conferir cobertura. Delegue uma investigação delimitada e somente leitura a um agente `explorer` com `model="gpt-6-luna"` e `fork_turns="none"`, se disponível. Inclua caminho absoluto, sintomas, escopo, achados do grafo e lacunas; peça hipótese, evidência e prova reproduzível. Se Luna ou delegação estiver indisponível, use o modelo disponível ou investigue diretamente e informe a limitação.
2. Reproduza com dados temporários e serviços simulados; nunca use banco, sessão ou mensagens pessoais em testes automatizados. No ambiente local, execute Python diretamente, sem Docker. Se houver medição, registre método, amostra, ambiente e limitações em `docs/performance/`.
3. Corrija a causa no ponto responsável quando o pedido autorizar correção; preserve dados, validação, tratamento de erros e confidencialidade de tokens. Um teste real em serviço externo exige autorização e não deve registrar credenciais ou conteúdo privado.
4. O responsável principal verifica a correção e atualiza documentação/memória. Se faltar evidência de produção, forneça a menor verificação segura e peça apenas o resultado necessário; não afirme resolução sem prova.
