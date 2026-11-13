# Exclusão de regra de alerta

Em 2026-11-13, a investigação de `Store.remove_rule` identificou que, depois de remover os hits e a regra, o método reavalia todas as palavras ignoradas com `auto_delete=1`. Para cada termo, `_permanently_delete_ignored_matches` consulta `offers` com `ignored_matches(body, ?)`. Essa função é Python/regex e não pode usar os índices SQL de `offers`, portanto cada consulta percorre a tabela. Tudo ocorre dentro de `BEGIN IMMEDIATE`, mantendo a transação de escrita aberta durante as varreduras e eventuais exclusões.

Medição na cópia local `.data/offers.db`, aberta com SQLite `mode=ro`, sem iniciar o app nem alterar a base: 86 ofertas, 3.843 palavras de autoexclusão; o plano da busca foi `SCAN offers`. Repetir a consulta do método para cada termo levou 7,955 s em uma execução (Python 3.14.4, SQLite 3.46.1, Linux x86_64). A busca avalia até 330.198 pares termo/oferta. Esse tempo cobre somente as varreduras; a operação real pode gastar mais ao verificar proteção de alertas, expandir álbuns e apagar ofertas e dados associados.

A medição pode ser repetida sem escrita com `PYTHONPATH=. .venv/bin/python` e o trecho abaixo. Ele imprime somente contagens e tempo; não imprime palavras, mensagens ou IDs:

```python
import sqlite3, time
from app.store import ignored_matches
path = '.data/offers.db'
db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
db.create_function('ignored_matches', 2, ignored_matches, deterministic=True)
words = [row[0] for row in db.execute(
    'SELECT normalized FROM ignored_keywords WHERE auto_delete=1')]
offers = db.execute('SELECT count(*) FROM offers').fetchone()[0]
started = time.perf_counter()
for word in words:
    db.execute('SELECT id FROM offers WHERE ignored_matches(body, ?)', (word,)).fetchall()
print('offers:', offers, 'auto_delete:', len(words),
      'seconds:', round(time.perf_counter() - started, 3))
db.close()
```

## Comparação antes/depois

Após a otimização, repeti os dois algoritmos sobre a mesma cópia em modo somente leitura para uma regra existente com mais hits (sem revelar seu identificador). O cálculo antigo retornou os IDs que seriam apagados; o novo cálculo foi comparado por igualdade exata. Ambos retornaram zero ofertas para apagar neste caso.

| Caminho medido | Tempo | Trabalho observado |
|---|---:|---|
| Anterior | 7,649 s | 3.843 consultas `SCAN offers` |
| Otimizado | 47,692 ms | 2 ofertas candidatas, 2 grupos, um matcher combinado compilado |

O resultado indica redução de 160× para esse caso. A nova medição é uma simulação somente leitura do cálculo: não executa `DELETE`, não mede a requisição HTTP completa e não inclui o índice novo `hits_rule_offer`, ainda inexistente na cópia usada. A comparação verifica o conjunto final de ofertas a excluir, mas não representa latência da instância de produção. Em testes temporários, casos com exclusão real também verificam remoção integral de álbuns e limpeza relacionada.

A otimização reduz o trabalho de O(autoexclusões × ofertas) para os hits da regra removida e partes dos álbuns candidatos, além de compilar todos os termos autoexclusivos numa expressão regular só. O índice `hits_rule_offer` acelera a localização desses hits e é criado idempotentemente na inicialização, sem migração de dados. Há um custo único para criar o índice em bancos existentes. Não foi feita alteração no banco local.
