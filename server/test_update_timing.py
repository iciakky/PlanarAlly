"""
TDD tests for initiative effect updateTiming support in advance_turn.

Tests the three verified failure scenarios:
- Scenario B: TurnStart effects on entering actor never processed
- Scenario A: TurnStart effects on exiting actor processed at wrong time
- Scenario C: Mixed TurnEnd+TurnStart on same actor
"""

import json
import copy

TURN_END = 0
TURN_START = 1


def make_effect(name: str, turns: str | None, timing: int = TURN_END) -> dict:
    return {
        "name": name,
        "turns": turns,
        "highlightsActor": False,
        "updateTiming": timing,
    }


def make_combatant(shape_id: str, initiative: int, effects: list | None = None) -> dict:
    return {
        "shape": shape_id,
        "initiative": initiative,
        "isVisible": True,
        "isGroup": False,
        "effects": effects or [],
    }


def build_initiative_data(*combatants):
    return list(combatants)


def simulate_advance_turn(initiative_data: list[dict], current_turn: int) -> tuple[list[dict], int]:
    """
    Simulate the advance_turn effect processing logic.

    This function extracts the effect processing from combats.py advance_turn
    so we can test it in isolation. It should match upstream's behavior:
    1. Process TurnEnd effects on the exiting actor
    2. Advance the turn index
    3. Process TurnStart effects on the entering actor

    Returns: (updated_initiative_data, new_turn)
    """
    from src.api.rest.combats import _process_effects_on_advance

    total = len(initiative_data)
    new_turn = (current_turn + 1) % total

    _process_effects_on_advance(initiative_data, current_turn, new_turn)

    return initiative_data, new_turn


# === Scenario B: TurnStart effects on entering actor must be processed ===

def test_turnstart_on_entering_actor_decrements():
    """Poison (TurnStart, 2 turns) on Goblin should decrement when Goblin's turn starts."""
    fighter = make_combatant("fighter", 15)
    goblin = make_combatant("goblin", 10, effects=[
        make_effect("Poison", "2", TURN_START),
    ])

    data = build_initiative_data(fighter, goblin)
    current_turn = 0  # Fighter's turn, advancing to Goblin

    data, new_turn = simulate_advance_turn(data, current_turn)

    assert new_turn == 1, f"Expected turn 1, got {new_turn}"
    goblin_effects = data[1]["effects"]
    assert len(goblin_effects) == 1, f"Expected 1 effect, got {len(goblin_effects)}"
    assert goblin_effects[0]["turns"] == "1", f"Poison should be 2→1, got {goblin_effects[0]['turns']}"


def test_turnstart_on_entering_actor_decrements_to_zero():
    """Poison (TurnStart, 1 turn) on Goblin decrements to 0 (removed on next cycle)."""
    fighter = make_combatant("fighter", 15)
    goblin = make_combatant("goblin", 10, effects=[
        make_effect("Poison", "1", TURN_START),
    ])

    data = build_initiative_data(fighter, goblin)
    data, new_turn = simulate_advance_turn(data, 0)

    goblin_effects = data[1]["effects"]
    assert len(goblin_effects) == 1, f"Expected 1 effect (at turns=0), got {len(goblin_effects)}"
    assert goblin_effects[0]["turns"] == "0", f"Poison should be 1→0, got {goblin_effects[0]['turns']}"


def test_effect_at_zero_removed_on_next_processing():
    """Effect already at turns=0 gets removed on next processing."""
    goblin = make_combatant("goblin", 10, effects=[
        make_effect("Poison", "0", TURN_END),
    ])
    fighter = make_combatant("fighter", 15)

    data = build_initiative_data(goblin, fighter)
    # Goblin's turn ends → TurnEnd processes Poison at 0 → removed
    data, new_turn = simulate_advance_turn(data, 0)

    assert len(data[0]["effects"]) == 0, f"Poison at 0 should be removed, got {data[0]['effects']}"


def test_turnstart_on_entering_actor_not_processed_early():
    """TurnStart effect on Goblin must NOT be processed when it's not Goblin's turn starting."""
    fighter = make_combatant("fighter", 15, effects=[
        make_effect("Shield", "2", TURN_END),
    ])
    goblin = make_combatant("goblin", 10, effects=[
        make_effect("Poison", "3", TURN_START),
    ])
    wizard = make_combatant("wizard", 5)

    data = build_initiative_data(fighter, goblin, wizard)
    # Goblin's turn ends, advancing to Wizard
    data, new_turn = simulate_advance_turn(data, 1)

    assert new_turn == 2
    # Goblin's TurnStart effect should NOT have been processed (Goblin is exiting, not entering)
    assert data[1]["effects"][0]["turns"] == "3", \
        f"Goblin's TurnStart Poison should stay at 3 (not decremented on exit), got {data[1]['effects'][0]['turns']}"


# === Scenario A: TurnStart effects on exiting actor must NOT be processed ===

def test_turnstart_on_exiting_actor_not_processed():
    """Rage (TurnStart, 3 turns) on Fighter should NOT decrement when Fighter's turn ends."""
    fighter = make_combatant("fighter", 15, effects=[
        make_effect("Rage", "3", TURN_START),
    ])
    goblin = make_combatant("goblin", 10)

    data = build_initiative_data(fighter, goblin)
    # Fighter's turn ends, advancing to Goblin
    data, new_turn = simulate_advance_turn(data, 0)

    fighter_effects = data[0]["effects"]
    assert len(fighter_effects) == 1
    assert fighter_effects[0]["turns"] == "3", \
        f"Rage (TurnStart) should NOT decrement on turn-end, got {fighter_effects[0]['turns']}"


def test_turnend_on_exiting_actor_processed():
    """Shield (TurnEnd, 2 turns) on Fighter SHOULD decrement when Fighter's turn ends."""
    fighter = make_combatant("fighter", 15, effects=[
        make_effect("Shield", "2", TURN_END),
    ])
    goblin = make_combatant("goblin", 10)

    data = build_initiative_data(fighter, goblin)
    data, new_turn = simulate_advance_turn(data, 0)

    fighter_effects = data[0]["effects"]
    assert len(fighter_effects) == 1
    assert fighter_effects[0]["turns"] == "1", \
        f"Shield (TurnEnd) should decrement 2→1, got {fighter_effects[0]['turns']}"


# === Scenario C: Mixed TurnEnd + TurnStart on same actor ===

def test_mixed_timing_on_exiting_actor():
    """Only TurnEnd effects processed on exit; TurnStart effects left alone."""
    cleric = make_combatant("cleric", 15, effects=[
        make_effect("Bless", "2", TURN_END),
        make_effect("Delayed Heal", "1", TURN_START),
    ])
    goblin = make_combatant("goblin", 10)

    data = build_initiative_data(cleric, goblin)
    data, new_turn = simulate_advance_turn(data, 0)

    cleric_effects = data[0]["effects"]
    bless = next(e for e in cleric_effects if e["name"] == "Bless")
    delayed_heal = next((e for e in cleric_effects if e["name"] == "Delayed Heal"), None)

    assert bless["turns"] == "1", f"Bless (TurnEnd) should 2→1, got {bless['turns']}"
    assert delayed_heal is not None, "Delayed Heal (TurnStart) should NOT be removed on turn-end"
    assert delayed_heal["turns"] == "1", \
        f"Delayed Heal (TurnStart) should stay at 1 on turn-end, got {delayed_heal['turns']}"


def test_mixed_timing_entering_actor():
    """TurnStart effects processed on entry; TurnEnd effects left alone."""
    fighter = make_combatant("fighter", 15)
    cleric = make_combatant("cleric", 10, effects=[
        make_effect("Bless", "2", TURN_END),
        make_effect("Aura", "3", TURN_START),
    ])

    data = build_initiative_data(fighter, cleric)
    # Fighter's turn ends, Cleric's turn starts
    data, new_turn = simulate_advance_turn(data, 0)

    cleric_effects = data[1]["effects"]
    bless = next(e for e in cleric_effects if e["name"] == "Bless")
    aura = next(e for e in cleric_effects if e["name"] == "Aura")

    assert bless["turns"] == "2", f"Bless (TurnEnd) should stay at 2 on turn-start, got {bless['turns']}"
    assert aura["turns"] == "2", f"Aura (TurnStart) should 3→2 on entry, got {aura['turns']}"


# === Edge cases ===

def test_none_turns_unaffected():
    """Effects with turns=None should never be modified regardless of timing."""
    fighter = make_combatant("fighter", 15, effects=[
        make_effect("Permanent Buff", None, TURN_END),
        make_effect("Persistent Aura", None, TURN_START),
    ])
    goblin = make_combatant("goblin", 10)

    data = build_initiative_data(fighter, goblin)
    data, _ = simulate_advance_turn(data, 0)

    assert len(data[0]["effects"]) == 2
    assert data[0]["effects"][0]["turns"] is None
    assert data[0]["effects"][1]["turns"] is None


def test_wrap_around_processes_correctly():
    """When turn wraps from last combatant to first, effects still process correctly."""
    fighter = make_combatant("fighter", 15, effects=[
        make_effect("Buff", "2", TURN_START),
    ])
    goblin = make_combatant("goblin", 10, effects=[
        make_effect("Shield", "1", TURN_END),
    ])

    data = build_initiative_data(fighter, goblin)
    # Goblin's turn (index 1) ends, wraps to Fighter (index 0)
    data, new_turn = simulate_advance_turn(data, 1)

    assert new_turn == 0
    # Goblin's TurnEnd Shield: 1→0 (stays, removed on next processing)
    assert len(data[1]["effects"]) == 1
    assert data[1]["effects"][0]["turns"] == "0", \
        f"Goblin's Shield should 1→0, got {data[1]['effects'][0]['turns']}"
    # Fighter's TurnStart Buff: 2→1
    assert data[0]["effects"][0]["turns"] == "1", \
        f"Fighter's TurnStart Buff should 2→1 on wrap-around entry, got {data[0]['effects'][0]['turns']}"


# === Runner ===

if __name__ == "__main__":
    tests = [
        test_turnstart_on_entering_actor_decrements,
        test_turnstart_on_entering_actor_decrements_to_zero,
        test_effect_at_zero_removed_on_next_processing,
        test_turnstart_on_entering_actor_not_processed_early,
        test_turnstart_on_exiting_actor_not_processed,
        test_turnend_on_exiting_actor_processed,
        test_mixed_timing_on_exiting_actor,
        test_mixed_timing_entering_actor,
        test_none_turns_unaffected,
        test_wrap_around_processes_correctly,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except (AssertionError, AssertionError) as e:
            print(f"  FAIL  {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {test.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed, {passed + failed} total")
    if failed > 0:
        exit(1)
