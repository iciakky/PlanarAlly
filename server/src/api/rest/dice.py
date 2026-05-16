"""
DiceParser - Full dice notation parser with advantage/disadvantage support.

Supports:
- NdX notation: 1d20, 2d6, 3d8
- Modifiers: 1d20+5, 2d6-2
- Compound: 1d20+5+1d4, 2d6+1d8+3
- Keep highest: 4d6kh3, 2d20kh1 (advantage)
- Keep lowest: 4d6kl1, 2d20kl1 (disadvantage)

Examples:
    >>> parse_and_roll("1d20+5")
    {"notation": "1d20+5", "rolls": [{"dice": "1d20", "results": [15], "kept": [15]}], "modifiers": [5], "total": 20}

    >>> parse_and_roll("2d20kh1")  # Advantage
    {"notation": "2d20kh1", "rolls": [{"dice": "2d20", "results": [12, 18], "kept": [18]}], "modifiers": [], "total": 18}
"""

import re
import random
from typing import Any


class DiceParseError(Exception):
    """Raised when dice notation cannot be parsed."""
    pass


def parse_and_roll(notation: str) -> dict[str, Any]:
    """
    Parse dice notation and execute the roll.

    Args:
        notation: Dice notation string (e.g., "1d20+5", "4d6kh3", "2d20kl1")

    Returns:
        Dictionary with structure:
        {
            "notation": str,  # Original notation
            "rolls": [        # List of dice roll groups
                {
                    "dice": str,      # Dice notation (e.g., "1d20")
                    "results": [int], # All rolled values
                    "kept": [int]     # Values kept after kh/kl
                }
            ],
            "modifiers": [int],  # All modifiers
            "total": int         # Final sum
        }

    Raises:
        DiceParseError: If notation is invalid
    """
    notation = notation.strip()
    if not notation:
        raise DiceParseError("Empty notation")

    # Pattern: (optional +/-)(NdX)(optional kh/kl N)
    # Example: "+2d6kh1" or "1d20" or "-1d4"
    dice_pattern = r'([+-]?)(\d+)d(\d+)(?:k([hl])(\d+))?'
    modifier_pattern = r'([+-]\d+)'

    rolls = []
    modifiers = []
    position = 0

    while position < len(notation):
        # Try to match dice roll
        dice_match = re.match(dice_pattern, notation[position:])
        if dice_match:
            sign = dice_match.group(1) or '+'
            num_dice = int(dice_match.group(2))
            die_size = int(dice_match.group(3))
            keep_type = dice_match.group(4)  # 'h' or 'l'
            keep_count = int(dice_match.group(5)) if dice_match.group(5) else None

            # Validate
            if num_dice <= 0:
                raise DiceParseError(f"Number of dice must be positive: {num_dice}")
            if die_size <= 0:
                raise DiceParseError(f"Die size must be positive: {die_size}")
            if num_dice > 1000:
                raise DiceParseError(f"Too many dice (max 1000): {num_dice}")
            if die_size > 1000:
                raise DiceParseError(f"Die size too large (max 1000): {die_size}")
            if keep_count is not None:
                if keep_count <= 0:
                    raise DiceParseError(f"Keep count must be positive: {keep_count}")
                if keep_count > num_dice:
                    raise DiceParseError(f"Cannot keep {keep_count} dice from {num_dice}")

            # Roll dice
            results = [random.randint(1, die_size) for _ in range(num_dice)]

            # Apply keep highest/lowest
            if keep_count is not None:
                sorted_results = sorted(results, reverse=(keep_type == 'h'))
                kept = sorted_results[:keep_count]
            else:
                kept = results

            # Apply sign to kept values
            if sign == '-':
                kept = [-v for v in kept]
                results = [-v for v in results]

            dice_notation = f"{sign if sign == '-' else ''}{num_dice}d{die_size}"
            if keep_count is not None:
                dice_notation += f"k{keep_type}{keep_count}"

            rolls.append({
                "dice": dice_notation,
                "results": results,
                "kept": kept
            })

            position += len(dice_match.group(0))
            continue

        # Try to match modifier
        modifier_match = re.match(modifier_pattern, notation[position:])
        if modifier_match:
            modifier = int(modifier_match.group(1))
            modifiers.append(modifier)
            position += len(modifier_match.group(0))
            continue

        # Skip whitespace
        if notation[position].isspace():
            position += 1
            continue

        # Unknown character
        raise DiceParseError(f"Invalid character at position {position}: '{notation[position]}'")

    # Validate we got at least one dice roll
    if not rolls:
        raise DiceParseError("No dice rolls found in notation")

    # Calculate total
    total = sum(sum(roll["kept"]) for roll in rolls) + sum(modifiers)

    return {
        "notation": notation,
        "rolls": rolls,
        "modifiers": modifiers,
        "total": total
    }


def roll_advantage() -> dict[str, Any]:
    """Roll with advantage (2d20kh1)."""
    return parse_and_roll("2d20kh1")


def roll_disadvantage() -> dict[str, Any]:
    """Roll with disadvantage (2d20kl1)."""
    return parse_and_roll("2d20kl1")


def roll_ability_scores() -> dict[str, Any]:
    """Roll ability scores (4d6kh3, standard D&D method)."""
    return parse_and_roll("4d6kh3")
