"""Readiness hierarchy, RCON client/allowlist, and server.properties schema
(Doc 14 sections 3, 6, 8; Doc 13 C8).

The readiness hierarchy is the Gate-1 heartbeat: a world is ``running`` only
after every signal at-or-below the server type's target level is green.
"""

from __future__ import annotations

import pytest

from app.domain.value_objects import ServerReadinessLevel, ServerType
from app.infrastructure.minecraft.capabilities import capabilities_for
from app.infrastructure.minecraft.properties_schema import (
    CORE_MANAGER_PROPERTIES,
    validate_properties,
)
from app.infrastructure.minecraft.rcon import SAFE_COMMANDS, RconClient, RconError
from app.infrastructure.minecraft.readiness import target_level_for

from app.ports.minecraft import ReadinessState, evaluate_readiness


def _state(**overrides) -> ReadinessState:
    base = dict(
        process_alive=False,
        port_bound=False,
        rcon_ready=False,
        probe_ok=False,
        operationally_valid=False,
    )
    base.update(overrides)
    return ReadinessState(**base)


# ---- Readiness hierarchy (Doc 14 section 3) -----------------------------------


def test_hierarchy_is_strictly_ordered():
    ranks = [level.rank for level in ServerReadinessLevel]
    assert ranks == sorted(ranks)
    assert ServerReadinessLevel.PROCESS_ALIVE.rank == 0
    assert ServerReadinessLevel.OPERATIONALLY_VALID.rank == 4


def test_no_signals_is_process_alive_dominated():
    # A running process is the floor of the ladder.
    assert (
        evaluate_readiness(_state(process_alive=True), ServerReadinessLevel.PROBE_OK)
        is ServerReadinessLevel.PROCESS_ALIVE
    )


def test_ladder_requires_all_lower_levels():
    # probe_ok true but port/rcon not confirmed must NOT claim probe_ok.
    state = _state(process_alive=True, port_bound=False, rcon_ready=False, probe_ok=True)
    assert (
        evaluate_readiness(state, ServerReadinessLevel.PROBE_OK)
        is ServerReadinessLevel.PROCESS_ALIVE
    )


def test_bound_tcp_port_alone_does_not_satisfy_readiness_target():
    state = _state(process_alive=True, port_bound=True)
    assert (
        evaluate_readiness(state, ServerReadinessLevel.PROBE_OK)
        is ServerReadinessLevel.PORT_BOUND
    )


def test_full_ladder_reaches_probe_ok():
    state = _state(
        process_alive=True,
        port_bound=True,
        rcon_ready=True,
        probe_ok=True,
        operationally_valid=False,
    )
    assert (
        evaluate_readiness(state, ServerReadinessLevel.PROBE_OK)
        is ServerReadinessLevel.PROBE_OK
    )


def test_operationally_valid_only_claims_when_all_below_green():
    state = _state(
        process_alive=True,
        port_bound=True,
        rcon_ready=True,
        probe_ok=True,
        operationally_valid=True,
    )
    assert (
        evaluate_readiness(state, ServerReadinessLevel.OPERATIONALLY_VALID)
        is ServerReadinessLevel.OPERATIONALLY_VALID
    )
    # probe_ok missing gates the top level
    assert (
        evaluate_readiness(
            _state(
                process_alive=True,
                port_bound=True,
                rcon_ready=True,
                probe_ok=False,
                operationally_valid=True,
            ),
            ServerReadinessLevel.OPERATIONALLY_VALID,
        )
        is ServerReadinessLevel.RCON_READY
    )


def test_target_levels_per_server_type():
    assert target_level_for(ServerType.PAPER) is ServerReadinessLevel.OPERATIONALLY_VALID
    assert target_level_for(ServerType.VANILLA) is ServerReadinessLevel.PROBE_OK
    assert target_level_for(ServerType.FORGE) is ServerReadinessLevel.PROBE_OK


# ---- RCON client (Doc 14 section 8) -------------------------------------------


def test_safe_command_allowlist_contains_only_documented():
    assert SAFE_COMMANDS == frozenset(
        {'save-all', 'save-off', 'save-on', 'stop', 'list', 'tps', 'tick'}
    )


def test_rcon_rejects_command_outside_allowlist():
    client = RconClient('127.0.0.1', 1, 'pw')
    with pytest.raises(RconError, match='not in allowlist'):
        client.command('op player1')


def test_rcon_error_on_unreachable_host():
    client = RconClient('127.0.0.1', 1, 'pw', timeout_s=0.2)
    with pytest.raises(RconError):
        client.connect()


# ---- server.properties schema (Doc 14 section 6) -------------------------------


def test_validate_properties_valid_full_set():
    payload = {
        'server-port': 25565,
        'max-players': 20,
        'difficulty': 'hard',
        'gamemode': 'survival',
        'online-mode': True,
        'white-list': False,
    }
    result = validate_properties(
        properties=payload, server_type=ServerType.VANILLA, mc_version='1.21'
    )
    assert result.valid, result.errors


@pytest.mark.parametrize(
    ('props', 'expected_error'),
    [
        ({'server-port': '25565'}, 'server-port'),
        ({'unknown-key': 1}, 'unknown-key'),
        ({'difficulty': 'ultra-hard'}, 'difficulty'),
        ({'max-players': 'twenty'}, 'max-players'),
    ],
)
def test_validate_properties_rejects_bad_values(props, expected_error):
    result = validate_properties(
        properties=props, server_type=ServerType.VANILLA, mc_version='1.21'
    )
    assert not result.valid
    assert any(expected_error in error for error in result.errors)


def test_deprecated_property_preserved_with_hint():
    result = validate_properties(
        properties={'generator-settings': 'oak'},
        server_type=ServerType.VANILLA,
        mc_version='1.20',
    )
    assert result.valid  # known-but-deprecated still validates
    assert any(
        'generator-settings' in hint and 'deprecated' in hint
        for hint in result.deprecated_hints
    )


def test_core_manager_properties_closed_set():
    # These are the properties only guarded editors may touch (Doc 14 6.1).
    assert 'server-port' in CORE_MANAGER_PROPERTIES
    assert 'enable-rcon' in CORE_MANAGER_PROPERTIES
    assert 'level-seed' in CORE_MANAGER_PROPERTIES


def test_capability_matrix_for_types():
    caps = capabilities_for(ServerType.PAPER)
    assert caps.rcon and caps.paper_api and caps.tps_metric
    assert capabilities_for(ServerType.VANILLA).save_coordination == 'rcon'
