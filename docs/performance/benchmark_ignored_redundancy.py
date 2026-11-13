"""Compare the former pairwise matcher with substring-index matching."""
import statistics
import time

from app.store import _irrelevant_ignored_words, ignored_matches


def pairwise(rows):
    irrelevant = []
    for row in rows:
        covered_by = [other['word'] for other in rows if other['id'] != row['id'] and
                      ignored_matches(row['normalized'], other['normalized'])]
        if covered_by:
            irrelevant.append({**row, 'covered_by': covered_by})
    return irrelevant


def fixture(size):
    terms = []
    for i in range((size + 1) // 2):
        base = f'catalog item {i:05d}'
        terms.append(base)
        if len(terms) < size:
            terms.append(base + ' special')
    return [{'id': i, 'word': term, 'normalized': term}
            for i, term in enumerate(sorted(terms))]


def measure(fn, rows, repeats):
    samples = []
    result = None
    for _ in range(repeats):
        start = time.perf_counter()
        result = fn(rows)
        samples.append(time.perf_counter() - start)
    return statistics.median(samples), result


for size in (150, 400, 4281):
    rows = fixture(size)
    optimized_time, optimized = measure(_irrelevant_ignored_words, rows, 5)
    if size <= 400:
        pairwise_time, baseline = measure(pairwise, rows, 3)
        assert baseline == optimized, f'Resultados divergentes com {size} filtros.'
        print(f'{size} filtros: pares={pairwise_time * 1000:.3f} ms; '
              f'índice={optimized_time * 1000:.3f} ms; '
              f'ganho={pairwise_time / optimized_time:.1f}x; '
              f'redundantes={len(optimized)}; resultados idênticos')
    else:
        print(f'{size} filtros: índice={optimized_time * 1000:.3f} ms; '
              f'redundantes={len(optimized)}; comparativo par-a-par omitido')
