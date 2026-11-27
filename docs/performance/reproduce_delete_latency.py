"""Reproduce SQLite lock waits and ignored-word ingestion cost with synthetic data."""
import asyncio
import json
import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from statistics import median
from types import SimpleNamespace
import sys


runtime = tempfile.TemporaryDirectory()
os.environ.update(DATA_DIR=runtime.name, APP_PASSWORD='temporary-diagnostic-password')
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.store import Store  # noqa: E402
from app import main  # noqa: E402


def create_store(path, ignored=0, auto_delete=0):
    store = Store(path)
    store.execute('INSERT INTO chats VALUES(-100123,?)', ('Synthetic',))
    with store.connect() as db:
        db.executemany('INSERT INTO ignored_keywords(word,normalized,auto_delete) VALUES(?,?,?)',
                       [(f'SyntheticTerm{i:05d}', f'syntheticterm{i:05d}', int(i < auto_delete))
                        for i in range(ignored)])
    return store


def measure_ingest(ignored, auto_delete):
    with tempfile.TemporaryDirectory() as tmp:
        store = create_store(Path(tmp) / 'offers.db', ignored, auto_delete)
        samples = []
        for message_id in range(1, 4):
            start = time.perf_counter()
            store.ingest(-100123, message_id, 'Offer without filter terms', '2026-11-27', None)
            samples.append(time.perf_counter() - start)
        return round(median(samples), 4)


def measure_delete_with_writer_lock(seconds=1.5):
    with tempfile.TemporaryDirectory() as tmp:
        store = create_store(Path(tmp) / 'offers.db')
        offer_id = store.ingest(-100123, 1, 'Synthetic offer', '2026-11-27', None)
        main.store = store
        timings = {}
        delete_offer, unread = store.delete_offer, store.unread

        def timed(name, operation):
            def call(*args):
                start = time.perf_counter()
                try:
                    return operation(*args)
                finally:
                    timings[name] = time.perf_counter() - start
            return call

        store.delete_offer = timed('delete_offer', delete_offer)
        store.unread = timed('unread', unread)
        locked, release = threading.Event(), threading.Event()

        def hold_writer():
            db = sqlite3.connect(store.path, timeout=0)
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE offers SET seen=seen+1 WHERE id=?', (offer_id,))
            locked.set()
            release.wait(seconds)
            db.rollback()
            db.close()

        writer = threading.Thread(target=hold_writer)
        writer.start()
        if not locked.wait(3):
            raise RuntimeError('Synthetic writer did not acquire its lock.')
        start = time.perf_counter()
        try:
            result = asyncio.run(main.delete_offer(
                SimpleNamespace(headers={'accept': 'application/json'}), offer_id))
        finally:
            release.set()
            writer.join()
        return {'route_s': round(time.perf_counter() - start, 3),
                **{key + '_s': round(value, 3) for key, value in timings.items()},
                'ok': result['ok']}


print(json.dumps({
    'ingest_median_s_no_filters': measure_ingest(0, 0),
    'ingest_median_s_5530_filters_5307_auto_delete': measure_ingest(5530, 5307),
    'delete_route_with_1_5s_writer_lock': measure_delete_with_writer_lock(),
}, sort_keys=True))
