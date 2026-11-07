from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_frontend_assets_and_environment_example_keep_their_canonical_locations() -> None:
    assert (ROOT / 'app' / 'shell' / 'static').is_dir()
    assert (ROOT / 'app' / 'shell' / 'templates').is_dir()
    assert any((ROOT / 'app' / 'shell' / 'static').iterdir())
    assert any((ROOT / 'app' / 'shell' / 'templates').iterdir())
    assert not (ROOT / 'static').exists()
    assert not (ROOT / 'templates').exists()

    env_example = ROOT / '.env.example'
    assert env_example.is_file()
    assert 'VERBOSE_LOGGING=false' in env_example.read_text(encoding='utf-8').splitlines()


def test_prototype_archive_keeps_its_existing_casing_and_layout() -> None:
    root_entry_names = {entry.name for entry in ROOT.iterdir()}
    assert 'Prototypes' in root_entry_names
    assert 'prototypes' not in root_entry_names

    prototypes = ROOT / 'Prototypes'
    assert {
        'Legacy',
        'V1',
        'V2',
        'V3',
    } <= {entry.name for entry in prototypes.iterdir() if entry.is_dir()}
