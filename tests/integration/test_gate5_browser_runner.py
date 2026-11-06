"""Run the browser-contract suite with Node's dependency-free test runner."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_gate5_browser_contracts_with_node():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is required for the Gate 5 browser contract tests')

    suite = Path(__file__).resolve().parents[1] / 'browser' / 'test_gate5_browser.test.cjs'
    result = subprocess.run(
        [node, '--test', str(suite)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f'{result.stdout}\n{result.stderr}'
