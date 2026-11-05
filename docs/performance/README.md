# Consulta da tela principal

Execute na raiz do repositório, sem Docker e sem dados pessoais:

```bash
PYTHONPATH=. .venv/bin/python docs/performance/benchmark_feed.py
```

O script cria uma base SQLite temporária com 5.000 mensagens sintéticas, 220 palavras ignoradas, parte das mensagens agrupada e 20% das mensagens contendo uma palavra ignorada. Mede a consulta completa da lista uma vez sem o índice de ordenação e uma vez com ele, e verifica que as ofertas exibidas e sua ordem são idênticas. A listagem limita mensagens antes de agrupar, por isso pode mostrar menos de 100 ofertas.

Uma execução local em 2026-11-04, com Python 3.14.4, Linux x86_64 e AMD Ryzen 7 5700X, apresentou:

| Consulta | Tempo | Ofertas exibidas |
|---|---:|---:|
| Sem índice | 6,414 s | 79 |
| Com índice | 0,180 s | 79 |

A diferença indica o custo de examinar e ordenar toda a tabela antes do limite. São resultados sintéticos de uma execução, sem concorrência e sem medir rede, carregamento de mídia ou a tela completa. O ganho em produção depende do banco e do ambiente. O índice é criado uma vez na abertura de bancos existentes; o tempo dessa criação não está incluído na medição.

## Filtro de palavras ignoradas

Execute `PYTHONPATH=. .venv/bin/python docs/performance/benchmark_ignored_filter.py` para comparar o filtro anterior, que normalizava e verificava cada termo para cada mensagem, com a regex compilada uma vez por consulta. O script usa uma base temporária com 1.078 mensagens sintéticas, 308 termos ignorados e alguns álbuns; exige que IDs e ordem dos cards resultantes sejam iguais (até 100 mensagens antes do agrupamento). Faz cinco medições e reporta a mediana.

Em 2026-11-05, no host local (Python 3.14, Linux x86_64, AMD Ryzen 7 5700X), a cópia isolada do backup com 1.078 ofertas e 308 termos passou de 1.815,2 ms para 15,4 ms na consulta do feed (99,2% menos, 118×). A rota Home completa passou de 1.845,7 ms para 38,7 ms no TestClient (97,9% menos, 47,7×); ambas retornaram 100 cards e cerca de 288 KB. Os dados privados não são incluídos no repositório. Resultados locais não preveem o tempo em produção.
