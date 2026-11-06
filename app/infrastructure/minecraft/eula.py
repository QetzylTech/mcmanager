"""EULA detection + acceptance writer (Doc 14 section 5, Doc 6 / ruling 11).

The manager never silently flips ``eula=true``. The only writer here is
called exclusively after an explicit, audited, step-up-protected operator
action (ConfigEdit Entity=eula).
"""

from __future__ import annotations

import os

from app.domain.value_objects import EulaState
from app.ports.minecraft import detect_eula, write_eula_acceptance


def provision_eula_file(world_dir: str, file_name: str = 'eula.txt') -> None:
    """Provision a world directory WITHOUT an accepted EULA.

    Writes ``eula=false`` when the file is absent so the server generates no
    surprise; never writes ``true``. New worlds enter ``eula_required``.
    """
    path = os.path.join(world_dir, file_name)
    if os.path.exists(path):
        return  # never overwrite an operator's file
    with open(path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(
            '# By changing the setting below to TRUE you are indicating your '
            'agreement to our EULA.\n'
        )
        handle.write('# https://aka.ms/MinecraftEULA\n')
        handle.write('eula=false\n')


def current_state(world_dir: str, file_name: str = 'eula.txt') -> EulaState:
    """Detect the current EULA state of a world directory."""
    if not world_dir:
        return EulaState.NOT_PRESENT
    return detect_eula(world_dir, file_name)


def accept(
    world_dir: str, file_name: str = 'eula.txt', *, operator_id: str | None = None
) -> None:
    """Write an accepted eula.txt — the ONLY ``eula=true`` writer.

    Call only after the audited operator-acceptance flow completes.
    """
    write_eula_acceptance(world_dir, file_name, operator_id=operator_id)
