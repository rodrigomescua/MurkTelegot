"""Compare the former per-term SQLite matcher with the compiled filter."""
import statistics
import tempfile
import time
from pathlib import Path

from app.store import Store, ignored_matches


class LegacyStore(Store):
    def _register_ignored_filter(self, db):
        words = [row[0] for row in db.execute('SELECT normalized FROM ignored_keywords')]
        db.create_function('ignored_offer', 1,
                           lambda body: any(ignored_matches(body, word) for word in words),
                           deterministic=True)


with tempfile.TemporaryDirectory() as temp:
    path = Path(temp) / 'benchmark.db'
    store = Store(path)
    with store.connect() as db:
        db.execute('INSERT INTO chats VALUES(1,?)', ('Grupo fictício',))
        db.executemany('INSERT INTO ignored_keywords(word,normalized) VALUES(?,?)',
                       [(f'filtro{i:03d}', f'filtro{i:03d}') for i in range(308)])
        db.executemany('''INSERT INTO offers(chat_id,message_id,chat_title,body,date,grouped_id)
                          VALUES(1,?,?,?,?,?)''', [
            (i, 'Grupo fictício',
             f'Oferta sintética item {i}' + (' filtro307' if i % 5 == 0 else ''),
             f'2026-11-05T{(i // 3600) % 24:02d}:{(i // 60) % 60:02d}:{i % 60:02d}+00:00',
             str(i // 3) if i % 3 in (0, 1) else None)
            for i in range(1, 1079)
        ])

    legacy = LegacyStore(path)

    def measure(label, target, repeats=5):
        durations, card_ids = [], None
        for _ in range(repeats):
            start = time.perf_counter()
            cards = target.feed()
            durations.append(time.perf_counter() - start)
            card_ids = [card['id'] for card in cards]
        median = statistics.median(durations)
        print(f'{label}: {median * 1000:.1f} ms; {len(card_ids)} cards')
        return card_ids

    before = measure('Per-termo', legacy)
    after = measure('Regex compilada', store)
    assert before == after, 'A seleção ou ordem das ofertas mudou.'
    print('Resultados idênticos.')
