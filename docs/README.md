# Documentação

Organização adaptada do RazorMiniflux: contrato operacional na raiz, decisões em ADRs e planos separados das evidências. Memória de tarefas no Obsidian; dados pessoais e sessões Telegram não fazem parte destes documentos.

| Documento | Responsabilidade |
|---|---|
| [README principal](../README.md) | Instalação, configuração e uso |
| [AGENTS.md](../AGENTS.md) | Contratos atuais, comandos e rotina de manutenção |
| [ADR-0001](architecture/ADR-0001-conta-telegram-sqlite-e-container.md) | Conta Telegram, persistência e distribuição |
| [Primeira entrega](plans/primeira-entrega.md) | Escopo, critérios de aceite e estado da entrega |
| [Operação](operacao.md) | Publicação, dados, atualização e recuperação |
| [Verificação](verificacao.md) | Como repetir testes e limites das evidências |
| [Identidade visual](../assets/README.md) | Logo, ícone, PNGs transparentes e pacote de download |

Crie novos ADRs quando mudar uma decisão de arquitetura. Planos não substituem contratos vigentes. Relatórios de desempenho devem incluir método, ambiente e limites; ainda não há medições para justificar uma pasta `performance/`.
