"""演练台账的链路化观测、修订应用与事件构建。

证据口径：
- 只有记录岗位与按时点有效的预案 observe 岗位一致的现场记录，才作为独立证据
  （观测限定在能支持使用的局部链路）；
- transcript 为转抄，只作佐证，永不计为独立证据；
- observability 非 known 或现象空缺一律记为未知，绝不默认填失败；
- handled 为确证正常（确证未发生失效），与未知严格区分；
- revisions 为后续目击与保障资料，按 reported_day 依次应用，可重现任一日口径。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from pathlib import Path

ADVERSE_PHENOMENA = ("late", "silent", "list_incomplete", "relay_reset")
NORMAL_PHENOMENA = ("handled",)
TRANSCRIPT_OBSERVER = "transcript"

STATE_UNKNOWN = "未知"
STATE_NORMAL = "确证正常"
STATE_ADVERSE = "确证失效"
STATE_OFFPLAN = "口径不符"

PHENOMENON_LABELS = {
    "late": "迟滞",
    "silent": "失声",
    "list_incomplete": "名单不全",
    "relay_reset": "转发复位",
    "handled": "处置正常",
}

MODE_LABELS = {
    "grid_power": "供电切换",
    "roster_stale": "名单陈旧",
    "clock_reset": "时钟复位",
    "mixed": "混合降级",
}


def split_multi(value: str) -> tuple[str, ...]:
    """同一单元内用竖线列出的多项值。"""
    return tuple(part for part in (value or "").split("|") if part)


@dataclass(frozen=True)
class PlanLink:
    """某一预案版本下一个节点的局部链路。"""

    version: str
    node: str
    village: str
    trigger: str
    observe: str
    fallback: str
    path: str

    def describe(self) -> str:
        return (
            f"{self.version}:{self.node}（村 {self.village}，触发 {self.trigger}，"
            f"观察岗位 {self.observe}，备用保障 {self.fallback}，转发路径 {self.path}）"
        )


@dataclass(frozen=True)
class Exercise:
    exercise: str
    plan: str
    district: str
    mode: str
    fold: str


@dataclass(frozen=True)
class Revision:
    rid: str
    record: str
    day: int
    field: str
    value: str


@dataclass(frozen=True)
class Check:
    check: str
    exercise: str
    node: str
    version: str
    mode: str
    affected: tuple[str, ...]
    observed: tuple[str, ...]
    state: str
    day: int


@dataclass(frozen=True)
class Replay:
    check: str
    exercise: str
    observed_mode: str
    covered_nodes: tuple[str, ...]
    completeness: str
    day: int


@dataclass
class Observation:
    record: str
    exercise: str
    node: str
    observer: str
    observability: str
    phenomenon: str
    signal_ident: str
    link: PlanLink | None = None
    history: tuple[tuple[str, str, str, int], ...] = ()

    @property
    def is_transcript(self) -> bool:
        return self.observer == TRANSCRIPT_OBSERVER

    @property
    def on_plan_post(self) -> bool:
        return self.link is not None and self.observer == self.link.observe

    @property
    def state(self) -> str:
        if self.observability != "known" or not self.phenomenon:
            return STATE_UNKNOWN
        if self.phenomenon in NORMAL_PHENOMENA:
            return STATE_NORMAL
        if self.phenomenon in ADVERSE_PHENOMENA:
            return STATE_ADVERSE
        return STATE_UNKNOWN

    def usable(self, accept_offplan: bool = False) -> bool:
        """是否可作为独立证据。转抄永不独立；未知永不作证据。"""
        if self.is_transcript or self.state == STATE_UNKNOWN:
            return False
        return self.on_plan_post or accept_offplan


@dataclass
class Registers:
    plans: dict[tuple[str, str], PlanLink]
    exercises: dict[str, Exercise]
    observations: list[Observation]
    revisions: list[Revision]
    checks: dict[str, Check]
    replays: dict[str, Replay]

    def link(self, version: str, node: str) -> PlanLink | None:
        return self.plans.get((version, node))

    def path_links(self, version: str, path: str) -> list[PlanLink]:
        return sorted(
            (link for link in self.plans.values() if link.version == version and link.path == path),
            key=lambda link: link.node,
        )

    @property
    def versions(self) -> list[str]:
        return sorted({link.version for link in self.plans.values()})


def _read_rows(location: Path, table: str) -> list[dict[str, str]]:
    with (location / f"{table}.csv").open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def load_registers(location: Path | str) -> Registers:
    location = Path(location)
    plans: dict[tuple[str, str], PlanLink] = {}
    for row in _read_rows(location, "plans"):
        link = PlanLink(
            row["plan"], row["node"], row["village"], row["trigger"],
            row["observe"], row["fallback"], row["path"],
        )
        plans[(link.version, link.node)] = link
    exercises: dict[str, Exercise] = {}
    for row in _read_rows(location, "exercises"):
        exercises[row["exercise"]] = Exercise(
            row["exercise"], row["plan"], row["district"], row["mode"], row["fold"]
        )
    observations: list[Observation] = []
    for row in _read_rows(location, "observations"):
        exercise = exercises[row["exercise"]]
        observations.append(
            Observation(
                record=row["record"],
                exercise=row["exercise"],
                node=row["node"],
                observer=row["observer"],
                observability=row["observability"],
                phenomenon=row["phenomenon"],
                signal_ident=row["signal_ident"],
                link=plans.get((exercise.plan, row["node"])),
            )
        )
    revisions = [
        Revision(row["id"], row["record"], int(row["reported_day"]), row["field"], row["value"])
        for row in _read_rows(location, "revisions")
    ]
    checks: dict[str, Check] = {}
    for row in _read_rows(location, "checks"):
        checks[row["check"]] = Check(
            row["check"], row["exercise"], row["node"], row["version"], row["mode"],
            split_multi(row["affected"]), split_multi(row["observed"]),
            row["state"], int(row["day"]),
        )
    replays: dict[str, Replay] = {}
    for row in _read_rows(location, "replays"):
        replays[row["check"]] = Replay(
            row["check"], row["exercise"], row["observed_mode"],
            split_multi(row["covered_nodes"]), row["completeness"], int(row["day"]),
        )
    return Registers(plans, exercises, observations, revisions, checks, replays)


def apply_revisions(
    registers: Registers, as_of_day: int | None = None
) -> tuple[list[Observation], list[dict]]:
    """应用后续资料，返回（观测视图， 变更日志）。as_of_day 重现该日及以前的口径。"""
    view = {obs.record: replace(obs) for obs in registers.observations}
    changes: list[dict] = []
    for revision in sorted(registers.revisions, key=lambda r: (r.day, r.rid)):
        if as_of_day is not None and revision.day > as_of_day:
            continue
        target = view.get(revision.record)
        if target is None or not hasattr(target, revision.field):
            continue
        old = getattr(target, revision.field)
        effect = "确认原值" if old == revision.value else "改写"
        setattr(target, revision.field, revision.value)
        target.history = target.history + ((revision.field, old, revision.value, revision.day),)
        changes.append(
            {
                "id": revision.rid,
                "record": revision.record,
                "字段": revision.field,
                "原值": old,
                "新值": revision.value,
                "日": revision.day,
                "效果": effect,
            }
        )
    return list(view.values()), changes


@dataclass
class Event:
    """同一信号标识下的一组现场记录：同一次故障的一处或多处表现。"""

    exercise: str
    signal: str
    primary: tuple[Observation, ...]
    transcripts: tuple[Observation, ...]

    @property
    def key(self) -> str:
        return f"{self.exercise}|{self.signal}"

    @property
    def shared(self) -> bool:
        """同一信号标识跨节点：同一次故障的多处表现。"""
        return len({obs.node for obs in self.primary}) > 1

    def adverse(self, accept_offplan: bool = False) -> dict[str, str]:
        """确证失效表现 {节点: 现象}，仅计可用独立证据。"""
        found: dict[str, str] = {}
        for obs in self.primary:
            if obs.state == STATE_ADVERSE and obs.usable(accept_offplan):
                found[obs.node] = obs.phenomenon
        return found

    def normal_nodes(self, accept_offplan: bool = False) -> list[str]:
        return sorted(
            obs.node for obs in self.primary
            if obs.state == STATE_NORMAL and obs.usable(accept_offplan)
        )

    def unknown_nodes(self) -> list[str]:
        return sorted(obs.node for obs in self.primary if obs.state == STATE_UNKNOWN)

    def offplan_known(self) -> dict[str, str]:
        """有确证内容但记录岗位不在现行预案观察岗位上的节点。"""
        return {
            obs.node: obs.phenomenon
            for obs in self.primary
            if obs.state != STATE_UNKNOWN and not obs.on_plan_post
        }

    def corroborated_nodes(self) -> list[str]:
        """转抄与主记录一致的节点（佐证，不计独立证据）。"""
        primary = {(obs.node, obs.phenomenon) for obs in self.primary if obs.state != STATE_UNKNOWN}
        return sorted({obs.node for obs in self.transcripts if (obs.node, obs.phenomenon) in primary})

    def dangling_transcripts(self) -> list[str]:
        """与主记录对不上的转抄（常见于修订拆分后抄录未更新）。"""
        primary = {(obs.node, obs.phenomenon) for obs in self.primary if obs.state != STATE_UNKNOWN}
        return sorted(
            obs.record for obs in self.transcripts if (obs.node, obs.phenomenon) not in primary
        )


def build_events(registers: Registers, observations: list[Observation]) -> list[Event]:
    groups: dict[tuple[str, str], dict[str, list[Observation]]] = {}
    for obs in observations:
        bucket = groups.setdefault((obs.exercise, obs.signal_ident), {"primary": [], "transcripts": []})
        bucket["transcripts" if obs.is_transcript else "primary"].append(obs)
    events = []
    for exercise, signal in sorted(groups):
        bucket = groups[(exercise, signal)]
        events.append(
            Event(
                exercise=exercise,
                signal=signal,
                primary=tuple(sorted(bucket["primary"], key=lambda o: o.record)),
                transcripts=tuple(sorted(bucket["transcripts"], key=lambda o: o.record)),
            )
        )
    return events


def node_statuses(
    registers: Registers,
    observations: list[Observation],
    accept_offplan: bool = False,
) -> dict[str, dict[str, dict]]:
    """每场演练每节点的三态（默认严格岗位口径）：确证失效 / 确证正常 / 未知。

    未知绝不默认填失败；有内容但岗位口径不符的单列，不并入确证。
    """
    by_exercise: dict[str, dict[str, list[Observation]]] = {}
    for obs in observations:
        if obs.is_transcript:
            continue
        by_exercise.setdefault(obs.exercise, {}).setdefault(obs.node, []).append(obs)
    statuses: dict[str, dict[str, dict]] = {}
    for exercise in sorted(by_exercise):
        nodes: dict[str, dict] = {}
        for node in sorted(by_exercise[exercise]):
            records = by_exercise[exercise][node]
            adverse = sorted(
                {o.phenomenon for o in records if o.state == STATE_ADVERSE and o.usable(accept_offplan)}
            )
            normal = [o for o in records if o.state == STATE_NORMAL and o.usable(accept_offplan)]
            offplan = sorted({o.phenomenon for o in records if o.state != STATE_UNKNOWN and not o.on_plan_post})
            if adverse:
                nodes[node] = {"状态": STATE_ADVERSE, "现象": adverse}
            elif normal:
                nodes[node] = {"状态": STATE_NORMAL, "现象": []}
            elif offplan:
                nodes[node] = {"状态": STATE_OFFPLAN, "现象": offplan}
            else:
                nodes[node] = {"状态": STATE_UNKNOWN, "现象": []}
        statuses[exercise] = nodes
    return statuses


def version_diffs(registers: Registers) -> dict[str, dict[str, dict[str, str]]]:
    """同一节点跨预案版本的链路属性差异。"""
    diffs: dict[str, dict[str, dict[str, str]]] = {}
    nodes = sorted({link.node for link in registers.plans.values()})
    for node in nodes:
        per_version = {version: registers.link(version, node) for version in registers.versions}
        attrs: dict[str, dict[str, str]] = {}
        for attr in ("village", "trigger", "observe", "fallback", "path"):
            values = {version: getattr(link, attr) for version, link in per_version.items() if link}
            if len(set(values.values())) > 1:
                attrs[attr] = values
        if attrs:
            diffs[node] = attrs
    return diffs
