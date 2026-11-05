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
