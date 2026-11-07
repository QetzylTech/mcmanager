"""Gate 5 performance smoke for idle CPU and traced memory."""

from __future__ import annotations

import json
import time
import tracemalloc
from pathlib import Path

from app import create_app


def run(database_path: str, keyfile_path: str, thresholds_path: str | Path | None = None) -> dict:
    thresholds_file = Path(thresholds_path or Path(__file__).with_name('thresholds.json'))
    thresholds = json.loads(thresholds_file.read_text(encoding='utf-8'))
    window = float(thresholds['idle_window_seconds'])
    tracemalloc.start()
    app = create_app(database_path=database_path, keyfile_path=keyfile_path)
    client = app.test_client()
    client.get('/api/health')
    cpu_start = time.process_time()
    wall_start = time.perf_counter()
    time.sleep(window)
    cpu_elapsed = time.process_time() - cpu_start
    wall_elapsed = time.perf_counter() - wall_start
    current, peak = tracemalloc.get_traced_memory()
    rss_mb = peak / (1024 * 1024)
    cpu_pct = (cpu_elapsed / wall_elapsed) * 100 if wall_elapsed else 0.0
    app.extensions['mcmanager_container'].store.close()
    passed = (
        cpu_pct <= float(thresholds['idle_cpu_pct_max'])
        and rss_mb <= float(thresholds['idle_rss_mb_max'])
    )
    return {
        'passed': passed,
        'cpu_pct': round(cpu_pct, 3),
        'rss_memory_mb': round(rss_mb, 3),
        'thresholds': thresholds,
    }


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('database_path')
    parser.add_argument('keyfile_path')
    parser.add_argument('--thresholds')
    args = parser.parse_args()
    result = run(args.database_path, args.keyfile_path, args.thresholds)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
