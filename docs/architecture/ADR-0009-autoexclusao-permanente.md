# ADR-0009: Autoexclusão permanente por palavra ignorada

- Status: aceita
- Data: 2026-11-10

## Contexto

Algumas ofertas devem ser descartadas assim que recebidas, sem permanecer no banco, gerar alertas ou passar por extração de IA. A ocultação existente precisa continuar disponível sem alterar seu comportamento padrão.

## Decisão

Adicionar `ignored_keywords.auto_delete`, coluna SQLite aditiva com default `0`. O usuário pode ativar ou desativar a opção no cadastro da regra, no atalho, na seleção de texto, nas ações individuais ou em lote de termos frequentes, e em regras já cadastradas. Ativar a opção remove ofertas correspondentes existentes e todos os itens de seus álbuns dentro da mesma transação.

Na ingestão do Telegram, regras ativas são avaliadas antes de salvar uma mensagem ou álbum, gerar hits/alertas ou enfileirar extração automática. Uma correspondência de alerta tem prioridade: a oferta/álbum é preservado, não é filtrado como ignorado e permanece elegível para IA. Se várias regras de alerta casam com uma oferta, remover uma delas mantém essa proteção; ao remover a última, regras `auto_delete` correspondentes são aplicadas imediatamente às ofertas existentes, na mesma transação. A exclusão também neutraliza itens pendentes de jobs manuais e interrompe localmente a chamada ativa quando o item em processamento corresponde; outros itens ainda não executados daquele job são cancelados. O provedor de IA ainda pode terminar uma requisição que já recebeu e cobrar por ela.

A tela de palavras ignoradas pagina no servidor e mantém a busca entre páginas. Alterar `auto_delete` na listagem salva imediatamente, sem botão dedicado.

Não gerar snapshot de banco adicional para esta coluna. A atualização da aplicação no Runtipi já mantém o backup do banco conforme a rotina operacional do usuário.

## Consequências

A exclusão física é irreversível no banco em execução e não aparece em “Excluídas recentemente”. Regras sem a opção continuam apenas ocultando ofertas e obedecendo à retenção existente. Bancos antigos migram automaticamente com a opção desativada.
