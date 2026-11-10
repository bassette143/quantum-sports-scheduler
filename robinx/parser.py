"""Parse RobinX (ITC2021) instance and solution files.

Format reference: "ITC2021 - Sports Timetabling: Problem Description and File
Format" (Van Bulck, Goossens, Beliën, Davari), shipped with QOBLIB as
05-sports/info/OrganizationITC2021_V7.pdf.

The parser keeps every constraint element it finds, whatever its tag, so that
the validator can report unsupported constraints instead of silently dropping
them.
"""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

# A game is (home team id, away team id, slot id), all 0-based integers.
Game = tuple[int, int, int]


@dataclass(frozen=True)
class Constraint:
    """One constraint element, e.g. <CA4 .../>, kept with its raw attributes."""

    tag: str           # e.g. "CA4"
    group: str         # e.g. "CapacityConstraints"
    index: int         # position among constraints with the same tag (0-based)
    attrs: dict

    @property
    def type(self) -> str:
        return self.attrs.get("type", "")

    @property
    def is_hard(self) -> bool:
        return self.type == "HARD"

    @property
    def label(self) -> str:
        return f"{self.tag}#{self.index}"


@dataclass
class Instance:
    name: str
    teams: list[int]
    slots: list[int]
    number_round_robin: int
    compactness: str
    game_mode: str
    constraints: list[Constraint] = field(default_factory=list)

    @property
    def n_teams(self) -> int:
        return len(self.teams)

    @property
    def n_slots(self) -> int:
        return len(self.slots)

    @property
    def n_games(self) -> int:
        return self.number_round_robin * self.n_teams * (self.n_teams - 1) // 2

    def constraints_by_tag(self, tag: str) -> list[Constraint]:
        return [c for c in self.constraints if c.tag == tag]


@dataclass
class Solution:
    games: list[Game]
    metadata: dict


def _read_bytes(path: str | Path) -> bytes:
    path = Path(path)
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == ".gz" else data


def parse_id_list(value: str | None) -> list[int]:
    """Parse '0;3;5' (RobinX list syntax) into [0, 3, 5]. Empty -> []."""
    if not value:
        return []
    return [int(x) for x in value.split(";") if x.strip() != ""]


def parse_meetings(value: str | None) -> list[tuple[int, int]]:
    """Parse '1,4;4,3;' into [(1, 4), (4, 3)] as (home, away) pairs."""
    if not value:
        return []
    out = []
    for item in value.split(";"):
        item = item.strip()
        if item:
            home, away = item.split(",")
            out.append((int(home), int(away)))
    return out


def parse_instance_xml(xml_bytes: bytes) -> Instance:
    root = ET.fromstring(xml_bytes)
    if root.tag != "Instance":
        raise ValueError(f"Not a RobinX instance: root element is <{root.tag}>")

    name_el = root.find("MetaData/InstanceName")
    teams = [int(t.get("id")) for t in root.findall("Resources/Teams/team")]
    slots = [int(s.get("id")) for s in root.findall("Resources/Slots/slot")]
    fmt = root.find("Structure/Format")
    if fmt is None:
        raise ValueError("Instance has no <Structure><Format> element")

    def fmt_text(tag: str) -> str:
        el = fmt.find(tag)
        if el is None or el.text is None:
            raise ValueError(f"Instance format is missing <{tag}>")
        return el.text.strip()

    constraints: list[Constraint] = []
    counters: dict[str, int] = {}
    cons_root = root.find("Constraints")
    if cons_root is not None:
        for group in cons_root:
            for el in group:
                idx = counters.get(el.tag, 0)
                counters[el.tag] = idx + 1
                constraints.append(Constraint(el.tag, group.tag, idx, dict(el.attrib)))

    return Instance(
        name=(name_el.text or "").strip() if name_el is not None else "",
        teams=teams,
        slots=slots,
        number_round_robin=int(fmt_text("numberRoundRobin")),
        compactness=fmt_text("compactness"),
        game_mode=fmt_text("gameMode"),
        constraints=constraints,
    )


def parse_instance(path: str | Path) -> Instance:
    """Parse a RobinX instance file (.xml or .xml.gz)."""
    return parse_instance_xml(_read_bytes(path))


def parse_solution_xml(xml_bytes: bytes) -> Solution:
    root = ET.fromstring(xml_bytes)
    if root.tag != "Solution":
        raise ValueError(f"Not a RobinX solution: root element is <{root.tag}>")
    games = [
        (int(m.get("home")), int(m.get("away")), int(m.get("slot")))
        for m in root.iter("ScheduledMatch")
    ]
    meta = {}
    md = root.find("MetaData")
    if md is not None:
        for el in md:
            meta[el.tag] = dict(el.attrib) if el.attrib else (el.text or "").strip()
    return Solution(games=games, metadata=meta)


def parse_solution(path: str | Path) -> Solution:
    """Parse an ITC2021 solution file (.xml or .xml.gz)."""
    return parse_solution_xml(_read_bytes(path))


def parse_mip_solution(path: str | Path) -> Solution:
    """Parse a QOBLIB .sol file where 'x#h#a#s 1' means h hosts a in slot s."""
    games: list[Game] = []
    meta: dict = {}
    for line in _read_bytes(path).decode("utf-8").splitlines():
        line = line.strip()
        if line.startswith("# Objective value ="):
            meta["objective"] = line.split("=", 1)[1].strip()
        if not line.startswith("x#"):
            continue
        name, value = line.split()[:2]
        if float(value) < 0.99:
            continue
        _, home, away, slot = name.split("#")
        games.append((int(home), int(away), int(slot)))
    return Solution(games=games, metadata=meta)
