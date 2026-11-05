"""Single-elimination championship bracket generator (Phase W2).

Builds one bracket per weight class from the Phase W1 rosters. Placement
is SYNTHETIC/UNSEEDED: entrants are placed deterministically in roster
(school-number) order purely for reproducibility. This does NOT follow
official NFHS seeding or bye-distribution requirements.

Bracket model
-------------
* Capacity is the next power of two >= entrants.
* Round 1 contains capacity/2 "slots". Each slot is either:
    - a contested MATCH between two wrestlers (winner unknown: None), or
    - a BYE: one wrestler paired with an empty position, advancing
      automatically. A bye is NOT a contested match and has no "winner";
      the wrestler simply advances.
* Because the capacity is the NEXT power of two, byes = capacity - entrants
  is always strictly less than capacity/2 (for >= 2 entrants), so byes can
  be placed one-per-slot and no round-1 slot ever pairs two empty
  positions.
* Rounds 2..k are PLACEHOLDER slots: their participants are determined by
  earlier results. A participant is recorded only when it is already known
  (a wrestler advancing on a round-1 bye); match winners are never
  invented.
* Special cases: 1 entrant -> champion by walkover, no rounds, no matches;
  0 entrants -> empty bracket, no champion.
* Every slot has a stable identifier "W<weight>-R<round>-S<slot>" for
  future winner tracking and mat scheduling.

No matches are scheduled onto mats or times here - that is a later phase.

Run:  python -m wrestling.brackets
"""

import json
from pathlib import Path

from wrestling.rosters import (
    DEFAULT_SEED,
    SCHOOL_NAMES,
    WEIGHT_CLASSES,
    TeamRoster,
    generate_rosters,
    next_power_of_two,
    tournament_statistics,
)

PLACEMENT_NOTE = (
    "synthetic deterministic placement in roster order (unseeded); "
    "not official NFHS seeding or bye distribution"
)


def eligible_entrants(rosters: list[TeamRoster], weight: int) -> list[str]:
    """Schools entering `weight`, in deterministic school-number order."""
    return [r.school for r in rosters if weight in r.filled_weights]


def slot_id(weight: int, round_number: int, slot_number: int) -> str:
    """Stable identifier for one bracket slot."""
    return f"W{weight}-R{round_number}-S{slot_number}"


def build_bracket(weight: int, entrants: list[str]) -> dict:
    """Build one weight class's single-elimination bracket structure."""
    n = len(entrants)

    if n == 0:
        return {
            "weight": weight,
            "entrants": [],
            "entrant_ids": [],
            "n_entrants": 0,
            "bracket_size": 0,
            "byes": 0,
            "projected_contested_matches": 0,
            "placement": PLACEMENT_NOTE,
            "positions": [],
            "rounds": [],
            "champion": None,
            "note": "no entrants: no bracket, no matches, no champion",
        }

    if n == 1:
        return {
            "weight": weight,
            "entrants": entrants,
            "entrant_ids": [f"{entrants[0]} @ {weight}"],
            "n_entrants": 1,
            "bracket_size": 1,
            "byes": 0,
            "projected_contested_matches": 0,
            "placement": PLACEMENT_NOTE,
            "positions": [entrants[0]],
            "rounds": [],
            "champion": entrants[0],
            "note": "single entrant: champion by walkover, no matches",
        }

    capacity = next_power_of_two(n)
    byes = capacity - n
    first_round_slots = capacity // 2
    # byes < first_round_slots always holds here (capacity is the NEXT
    # power of two), so one bye per slot suffices.
    assert byes < first_round_slots

    # --- Positions: first `byes` slots get [wrestler, empty], the rest
    # get [wrestler, wrestler], filling entrants in deterministic order ---
    positions: list[str | None] = []
    idx = 0
    for s in range(first_round_slots):
        if s < byes:
            positions += [entrants[idx], None]
            idx += 1
        else:
            positions += [entrants[idx], entrants[idx + 1]]
            idx += 2
    assert idx == n

    # --- Round 1: byes and contested matches ---
    rounds: list[dict] = []
    round1 = []
    for s in range(first_round_slots):
        a, b = positions[2 * s], positions[2 * s + 1]
        sid = slot_id(weight, 1, s + 1)
        if b is None:
            round1.append({
                "id": sid,
                "round": 1,
                "type": "bye",
                "wrestlers": [a, None],
                "advances": a,  # automatic advancement, not a match win
            })
        else:
            round1.append({
                "id": sid,
                "round": 1,
                "type": "match",
                "wrestlers": [a, b],
                "winner": None,  # to be contested; never invented
            })
    rounds.append({"round": 1, "slots": round1})

    # --- Later rounds: placeholders fed by the previous round ---
    n_rounds = capacity.bit_length() - 1  # log2(capacity)
    prev_slots = round1
    for r in range(2, n_rounds + 1):
        this_round = []
        for s in range(len(prev_slots) // 2):
            feed_a, feed_b = prev_slots[2 * s], prev_slots[2 * s + 1]
            participants = [
                feed["advances"] if feed["type"] == "bye" else None
                for feed in (feed_a, feed_b)
            ]
            this_round.append({
                "id": slot_id(weight, r, s + 1),
                "round": r,
                "type": "placeholder",
                "fed_by": [feed_a["id"], feed_b["id"]],
                "participants": participants,  # known only via byes
                "winner": None,
            })
        rounds.append({"round": r, "slots": this_round})
        prev_slots = this_round

    contested = sum(
        1 for rnd in rounds for slot in rnd["slots"]
        if slot["type"] in ("match", "placeholder")
    )
    assert contested == n - 1  # single-elimination invariant

    return {
        "weight": weight,
        "entrants": entrants,
        "entrant_ids": [f"{e} @ {weight}" for e in entrants],
        "n_entrants": n,
        "bracket_size": capacity,
        "byes": byes,
        "projected_contested_matches": contested,
        "placement": PLACEMENT_NOTE,
        "positions": positions,
        "rounds": rounds,
        "champion": None,  # unknown until matches are actually contested
    }


def generate_all_brackets(seed: int = DEFAULT_SEED) -> dict:
    """Generate the complete championship bracket set from Phase W1 rosters."""
    rosters = generate_rosters(seed)
    stats = tournament_statistics(rosters)
    brackets = {
        weight: build_bracket(weight, eligible_entrants(rosters, weight))
        for weight in WEIGHT_CLASSES
    }
    return {
        "experiment": "wrestling_bracket_generation_phase_w2",
        "settings": {
            "seed": seed,
            "n_schools": len(SCHOOL_NAMES),
            "weight_classes": WEIGHT_CLASSES,
            "bracket_type": "single-elimination championship (simplified)",
            "placement": PLACEMENT_NOTE,
        },
        "brackets": brackets,
        "summary": {
            "total_schools": stats["total_schools"],
            "total_wrestlers": stats["total_wrestlers"],
            "total_missing_positions": stats["total_missing_positions"],
            "total_byes": sum(b["byes"] for b in brackets.values()),
            "total_projected_contested_matches": sum(
                b["projected_contested_matches"] for b in brackets.values()
            ),
            "n_brackets": len(brackets),
        },
    }


def save_brackets(data: dict, path: Path) -> None:
    """Save bracket data as JSON (weight keys become strings in JSON)."""
    path.write_text(json.dumps(data, indent=2))


def display_summary(data: dict, example_weight: int = 106) -> None:
    print("=== Wrestling championship brackets (Phase W2) ===")
    print(f"Placement: {data['settings']['placement']}\n")

    print(f"{'Weight':<8}{'Entrants':<10}{'Bracket Size':<14}{'Byes':<6}"
          f"{'Projected Matches':<18}")
    print("-" * 56)
    for weight in data["settings"]["weight_classes"]:
        b = data["brackets"][weight]
        print(f"{weight:<8}{b['n_entrants']:<10}{b['bracket_size']:<14}"
              f"{b['byes']:<6}{b['projected_contested_matches']:<18}")

    s = data["summary"]
    print("\nTournament totals")
    print(f"  Participating schools:            {s['total_schools']}")
    print(f"  Total wrestlers:                  {s['total_wrestlers']}")
    print(f"  Missing roster positions:         {s['total_missing_positions']}")
    print(f"  Total byes:                       {s['total_byes']}")
    print(f"  Projected contested matches:      "
          f"{s['total_projected_contested_matches']}")
    print(f"  Generated brackets:               {s['n_brackets']}")

    # --- Readable round-1 example for one weight class ---
    b = data["brackets"][example_weight]
    print(f"\nExample: {example_weight} lbs first round "
          f"({b['n_entrants']} entrants, bracket of {b['bracket_size']}, "
          f"{b['byes']} byes)")
    for slot in b["rounds"][0]["slots"]:
        if slot["type"] == "bye":
            print(f"  {slot['id']}: {slot['wrestlers'][0]} - BYE "
                  f"(advances automatically, not a contested match)")
        else:
            print(f"  {slot['id']}: {slot['wrestlers'][0]} vs "
                  f"{slot['wrestlers'][1]} (winner TBD)")
    r2 = b["rounds"][1]["slots"]
    print(f"  ... {len(r2)} quarter/semi slots and later rounds are "
          f"placeholders fed by these results.")


def main(seed: int = DEFAULT_SEED) -> None:
    data = generate_all_brackets(seed)
    display_summary(data)
    out_path = Path(__file__).parent.parent / "results" / "wrestling_brackets.json"
    save_brackets(data, out_path)
    print(f"\nBracket data saved to {out_path}")


if __name__ == "__main__":
    main()
