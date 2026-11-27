# Latência ao excluir uma oferta

## Evidência do código

O navegador envia o POST com `fetch`, desabilita o botão e só mostra “Oferta excluída” quando recebe o JSON. A rota `/offers/{id}/delete` chama `Store.delete_offer()` e `Store.unread()` sincronamente dentro de uma função `async`; ambos podem atrasar a resposta.

`Store.connect()` configura `timeout=30`, isto é, SQLite pode esperar até 30 segundos por outro escritor. WAL permite leitura durante uma escrita, mas não permite duas transações escritoras ao mesmo tempo. A chamada de exclusão atualiza `deleted_at`; a exclusão física ocorre depois, na rotina de retenção.

No snapshot local consultado estritamente em `mode=ro`, havia 194 ofertas, 5.530 palavras ignoradas, 5.307 com autoexclusão e 9 regras de alerta. A consulta SQL de `unread()` levou 0,0007 s. A seleção de candidatos da limpeza, sem mutações, levou 0,1598 s e retornou 17 linhas; havia 12 exclusões lógicas com mais de uma hora. Esses números descrevem apenas esse snapshot local.

Além disso, o handler assíncrono de novas mensagens chamava `store.ingest()` sem `asyncio.to_thread`, bloqueando o event loop. O matcher também recompilava padrões sobre as milhares de palavras ignoradas. Uma sequência de mensagens podia atrasar respostas HTTP e cliques, mesmo sem espera por lock.

## Reprodução sintética

Execute na raiz do repositório:

```bash
.venv/bin/python docs/performance/reproduce_delete_latency.py
```

O script usa apenas diretórios SQLite temporários. Mede três ingestões com zero filtros e com 5.530 filtros (5.307 autoexclusões), e chama a rota diretamente enquanto outra conexão sintética mantém um lock por 1,5 s. Após a correção, uma execução local produziu:

| Cenário | Rota/exclusão | `unread()` |
|---|---:|---:|
| Ingestão com zero filtros, mediana de 3 ofertas | 0,0005 s por ingestão | — |
| Ingestão com 5.530 filtros, mediana de 3 ofertas | 0,0109 s por ingestão | — |
| Escritor SQLite mantém lock por 1,5 s | 1,534 s | 0,000 s |

O handler agora executa as operações SQLite de exclusão em threads; a ingestão Telegram também ocorre fora do event loop e usa um lock assíncrono para serializar mensagens, edições, álbuns e refreshes. Padrões de autoexclusão e de marcação ficam em cache LRU limitado e são reutilizados enquanto o conjunto exato de regras não muda. Logs registram somente duração de operações lentas, sem IDs ou texto das mensagens.

É uma prova reproduzível do bloqueio potencial e do custo sintético do matcher, não uma medição de latência de produção nem identificação do escritor que segurou o lock em um clique real. A rota ainda pode aguardar até 30 s se outro escritor mantiver o lock; a diferença é que essa espera não bloqueia o event loop web.
