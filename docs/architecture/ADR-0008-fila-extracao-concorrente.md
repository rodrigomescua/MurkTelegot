# ADR-0008: Concorrência e repetição da fila de extração IA

- Status: aceita
- Data: 2026-11-07

## Contexto

A fila persistente processava um job por vez e chamadas ao provedor não tinham timeout explícito. Falhas de todos os modelos encerravam o item, mesmo quando poderiam ser transitórias. Uma repetição precisa liberar a vaga concorrente e respeitar a ordem dos jobs já enfileirados.

## Decisão

Persistir em `settings` um limite de 1 a 8 jobs simultâneos, padrão 1. O processo mantém até oito loops leves de worker; cada claim `BEGIN IMMEDIATE` lê a configuração atual e conta jobs `running` e `cancelling`, evitando exceder o limite inclusive durante cancelamentos em voo. Mudanças passam a valer sem reiniciar o app.

Limitar cada chamada HTTP ao provedor a 60 segundos. Os modelos configurados seguem em fallback na mesma rodada. Se todos falharem, reenfileirar o job uma vez, colocando-o atrás dos jobs que já aguardavam. Um segundo esgotamento termina com falha. Cancelamentos solicitados pelo usuário, erros de configuração sem uma chamada malsucedida e resultados obsoletos não geram repetição.

Adicionar `ai_jobs.queue_at` de forma aditiva, com snapshot antes da migração, para ordenar jobs que retornam à fila sem alterar `created_at` exibido. Reenfileirar também move o item ao fim da lista dentro do job. Os registros de tentativas identificam o reenvio.

## Consequências

A concorrência pode elevar o consumo simultâneo e não transforma o app em implantação multi-instância; o contrato continua sendo uma instância por banco. Um timeout ou reenvio pode ocorrer depois de o provedor ter iniciado trabalho e ainda gerar cobrança. O padrão 1 preserva a carga anterior. O snapshot protege os dados anteriores à migração de fila.
