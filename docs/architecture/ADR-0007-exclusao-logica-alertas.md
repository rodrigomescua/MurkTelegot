# ADR-0007: Exclusão lógica e desfazer ações nos cards de alerta

- Status: aceita
- Data: 2026-11-06
- Atualiza: [ADR-0005](ADR-0005-retencao-e-gerenciamento-alertas.md), somente quanto à exclusão manual.

## Contexto

Os cards de alerta aparecem na Home, na página de Alertas e nas ofertas de termos frequentes. Ações que recarregavam essas telas removiam o card de sua posição antes de a pessoa confirmar visualmente o resultado. A exclusão física imediata também impedia desfazer uma ação acidental.

## Decisão

Persistir `offers.deleted_at` para exclusão lógica. Marcar como lido e excluir atualizam o card no lugar sem recarregar; a tela oferece desfazer enquanto permanecer aberta. Leitura só muda o card para a seção de lidos após recarregar.

Excluir oculta imediatamente a oferta ou álbum em todas as listas, contagens e links de mídia. O desfazer limpa `deleted_at` no álbum. A limpeza já executada ao iniciar e a cada cinco minutos remove ofertas excluídas há pelo menos uma hora, junto com seus hits. A migração é aditiva e cria índice parcial para localizar exclusões pendentes.

## Consequências

Uma exclusão pode ser desfeita na tela atual; depois de recarregar, continua oculta e não há tela de recuperação. A remoção física pode ocorrer até cinco minutos após completar uma hora. Bancos existentes recebem uma coluna e um índice sem reescrita dos registros.
