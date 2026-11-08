# ADR-0005: Retenção de ofertas e gerenciamento de alertas

- Status: aceita
- Data: 2026-11-05
- Gerenciamento de exclusão atualizado em 2026-11-06 por [ADR-0007](ADR-0007-exclusao-logica-alertas.md).

## Contexto

O volume SQLite acumulava mensagens sem limite. Ofertas ignoradas por palavra não precisam permanecer após uma janela curta; ofertas comuns também têm retenção limitada. Alertas devem continuar disponíveis até remoção explícita. Gerenciar regras na tela principal mistura configuração e acompanhamento de ofertas.

## Decisão

Usar data Telegram em `offers.date` para calcular retenção, sem adicionar coluna. Apagar ofertas sem alertas após 4 horas quando qualquer parte do álbum corresponde a palavra ignorada; apagar demais ofertas sem alertas após 24 horas. Qualquer parte do álbum com alerta protege o álbum inteiro da limpeza automática. A limpeza roda ao iniciar e a cada cinco minutos.

Permitir exclusão manual de uma oferta alertada com confirmação e CSRF; em álbuns, excluir todas as partes e correspondências associadas. Mover criação, listagem e remoção de regras de alerta para página dedicada. Ao criar regra, aplicar correspondências retroativamente às ofertas existentes, inclusive às ocultas por palavras ignoradas; notificar Gotify uma vez por oferta/álbum correspondente.

## Consequências

Ofertas com data antiga podem ser removidas na primeira limpeza; não há recuperação local após exclusão, então backups continuam importantes. Alertas podem crescer até exclusão manual. A cada cinco minutos, arquivos de mídia sem oferta correspondente são removidos do cache; o cache de ofertas logicamente excluídas é mantido até sua purga física. Não há migração de esquema.
