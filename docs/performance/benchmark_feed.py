"""Benchmark sintético: execute PYTHONPATH=. .venv/bin/python docs/performance/benchmark_feed.py."""
import tempfile
import time
from pathlib import Path

from app.store import Store


with tempfile.TemporaryDirectory() as temp:
    store = Store(Path(temp) / 'benchmark.db')
    with store.connect() as db:
        db.execute('INSERT INTO chats VALUES(1,?)', ('Grupo fictício',))
        db.executemany('INSERT INTO ignored_keywords(word,normalized) VALUES(?,?)',
                       [(f'filtro{i:03d}', f'filtro{i:03d}') for i in range(220)])
        db.executemany('''INSERT INTO offers(chat_id,message_id,chat_title,body,date,grouped_id)
                          VALUES(1,?,?,?,?,?)''', [
            (i, 'Grupo fictício', f'Oferta teste produto {i} preço baixo' + (' filtro000' if i % 5 == 0 else ''),
             f'2026-11-01T{(i // 3600) % 24:02d}:{(i // 60) % 60:02d}:{i % 60:02d}+00:00',
             str(i // 4) if i % 4 in (0, 1) else None)
            for i in range(1, 5001)
        ])

    def measure(label):
        start = time.perf_counter()
        cards = store.feed()
        elapsed = time.perf_counter() - start
        print(f'{label}: {elapsed:.3f} s; {len(cards)} ofertas exibidas')
        return [card['id'] for card in cards]

    store.execute('DROP INDEX offers_recent')
    before = measure('Sem índice')
    store.execute('CREATE INDEX offers_recent ON offers(date DESC, id DESC)')
    after = measure('Com índice')
    assert before == after, 'A ordenação ou filtragem mudou.'
    print('Resultados iguais nas duas consultas.')
