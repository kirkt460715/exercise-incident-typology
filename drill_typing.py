"""失效分型：可解释类型的发现、归属、敏感性、留出稳定与版本对应。

类型只来自现场观测、按时点有效的预案链路与排演干预条件；
整改分类（checks）是组织者事后所写，绝不用于反填当时输入。
"""

from __future__ import annotations

from dataclasses import dataclass

from drill_ledger import (
    MODE_LABELS,
    PHENOMENON_LABELS,
    STATE_ADVERSE,
    STATE_UNKNOWN,
    Event,
    Registers,
    node_statuses,
    version_diffs,
)

SUPPORT_THRESHOLD = 2


@dataclass(frozen=True)
class FailureType:
    """一个可解释失效类型：判定规则 + 依据的链路共性。"""

    type_id: str
    kind: str  # segment=单段表现型 composite=共路同现型
    mode: str | None
    path: str | None
    pattern: tuple[tuple[str, str], ...]
    basis: str

    def to_dict(self, support: list[str]) -> dict:
        return {
            "类型": self.type_id,
            "类别": "共路同现型" if self.kind == "composite" else "单段表现型",
            "触发条件": self.mode or "跨条件",
            "表现": [f"{node}:{PHENOMENON_LABELS.get(p, p)}" for node, p in self.pattern],
            "共性链路": self.basis,
            "支持演练": support,
            "支持场数": len(support),
        }


def _exercise_adverse(
    events: list[Event], exercise_ids: set[str], accept_offplan: bool = False
) -> dict[str, dict[str, str]]:
    """每场演练的确证失效表现 {演练: {节点: 现象}}。"""
    per: dict[str, dict[str, str]] = {}
    for event in events:
        if event.exercise not in exercise_ids:
            continue
        bucket = per.setdefault(event.exercise, {})
        for node, phenomenon in event.adverse(accept_offplan).items():
            bucket.setdefault(node, phenomenon)
    return per


def _link_basis(registers: Registers, node: str, exercise_ids: set[str]) -> str:
    seen: dict[str, None] = {}
    for ex_id in sorted(exercise_ids):
        exercise = registers.exercises[ex_id]
        link = registers.link(exercise.plan, node)
        if link is not None:
            seen[link.describe()] = None
    return "；".join(seen)


def discover_types(
    registers: Registers, events: list[Event], exercise_ids: set[str]
) -> tuple[list[FailureType], dict[str, list[str]]]:
    """从给定演练集合发现可解释类型。返回（类型列表， 各型支持演练）。

    单段表现型：同一节点段反复出现同一失效表现；
    共路同现型：同一干预条件下，同一转发路径上多节点同现失效（同一次故障的多处表现）。
    """
    per_exercise = _exercise_adverse(events, exercise_ids)
    segment_support: dict[tuple[str, str], set[str]] = {}
    composite_support: dict[tuple, set[str]] = {}
    shared_paths: dict[str, set[str]] = {}
    for event in events:
        if event.exercise not in exercise_ids or not event.shared:
            continue
        adverse = event.adverse()
        if len(adverse) < 2:
            continue
        exercise = registers.exercises[event.exercise]
        for node in adverse:
            link = registers.link(exercise.plan, node)
            if link is not None:
                shared_paths.setdefault(event.exercise, set()).add(link.path)
    for ex_id, adverse in per_exercise.items():
        exercise = registers.exercises[ex_id]
        by_path: dict[str, list[tuple[str, str]]] = {}
        for node, phenomenon in adverse.items():
            segment_support.setdefault((node, phenomenon), set()).add(ex_id)
            link = registers.link(exercise.plan, node)
            if link is not None:
                by_path.setdefault(link.path, []).append((node, phenomenon))
        for path, items in by_path.items():
            if len({node for node, _ in items}) < 2:
                continue
            pattern = tuple(sorted(items))
            composite_support.setdefault((exercise.mode, path, pattern), set()).add(ex_id)
    types: list[FailureType] = []
    supports: dict[str, list[str]] = {}
    for (node, phenomenon), exs in sorted(segment_support.items()):
        if len(exs) < SUPPORT_THRESHOLD:
            continue
        type_id = f"SEG-{node}-{phenomenon}"
        basis = f"共性来自 {node} 段（{_link_basis(registers, node, exs)}）"
        types.append(FailureType(type_id, "segment", None, None, ((node, phenomenon),), basis))
        supports[type_id] = sorted(exs)
    for (mode, path, pattern), exs in sorted(composite_support.items()):
        if len(exs) < SUPPORT_THRESHOLD:
            continue
        nodes = "、".join(node for node, _ in pattern)
        type_id = "CO-" + "-".join([mode, path] + [f"{n}:{p}" for n, p in pattern])
        direct = sum(1 for ex_id in exs if path in shared_paths.get(ex_id, set()))
        basis = (
            f"共性来自 {path} 段：{MODE_LABELS.get(mode, mode)}条件下 {nodes} 同现"
            f"（{direct} 场为同源信号直接证据）"
        )
        types.append(FailureType(type_id, "composite", mode, path, pattern, basis))
        supports[type_id] = sorted(exs)
    return types, supports


def assign_types(
    registers: Registers,
    events: list[Event],
    types: list[FailureType],
    accept_offplan: bool = False,
) -> dict[str, list[str]]:
    """事件归类。同一事件可属于不止一型，也可以没有足够证据归类。"""
    assignments: dict[str, list[str]] = {}
    for event in events:
        adverse = event.adverse(accept_offplan)
        exercise = registers.exercises[event.exercise]
        hits: set[str] = set()
        for ftype in types:
            if ftype.kind == "segment":
                (node, phenomenon), = ftype.pattern
                if adverse.get(node) == phenomenon:
                    hits.add(ftype.type_id)
            elif exercise.mode == ftype.mode:
                for node, phenomenon in ftype.pattern:
                    if adverse.get(node) != phenomenon:
                        continue
                    link = registers.link(exercise.plan, node)
                    if link is not None and link.path == ftype.path:
                        hits.add(ftype.type_id)
        assignments[event.key] = sorted(hits)
    return assignments


def event_diagnosis(event: Event, hits: list[str]) -> str:
    """未归类事件的原因说明。"""
    if hits:
        return "已归类"
    if not event.primary:
        return "证据不足：仅转抄，无独立记录"
    if event.adverse():
        return "孤例：表现组合支持不足，未定型"
    if event.adverse(accept_offplan=True):
        return "仅岗位口径外证据：严格口径下不能归类"
    if all(obs.state == STATE_UNKNOWN for obs in event.primary):
        return "证据不足：无确证观测"
    return "无确证失效表现"


def exercise_features(
    registers: Registers,
    events: list[Event],
    assignments: dict[str, list[str]],
    observations,
) -> dict[str, dict]:
    """每场演练的可比较特征：节点三态、事件、命中类型、证据质量。"""
    statuses = node_statuses(registers, observations)
    by_exercise: dict[str, list[Event]] = {}
    for event in events:
        by_exercise.setdefault(event.exercise, []).append(event)
    features: dict[str, dict] = {}
    for ex_id in sorted(registers.exercises):
        exercise = registers.exercises[ex_id]
        ex_events = by_exercise.get(ex_id, [])
        ex_obs = [o for o in observations if o.exercise == ex_id]
        features[ex_id] = {
            "降级条件": exercise.mode,
            "地区": exercise.district,
            "预案版本": exercise.plan,
            "分折": exercise.fold,
            "节点状态": statuses.get(ex_id, {}),
            "命中类型": sorted({t for e in ex_events for t in assignments[e.key]}),
            "事件": [
                {
                    "事件": e.key,
                    "同源多节点": e.shared,
                    "确证失效": e.adverse(),
                    "确证正常": e.normal_nodes(),
                    "未知": e.unknown_nodes(),
                    "口径外证据": e.offplan_known(),
                    "转抄佐证": e.corroborated_nodes(),
                    "悬空转抄": e.dangling_transcripts(),
                    "类型": assignments[e.key],
                }
                for e in ex_events
            ],
            "证据质量": {
                "未知记录": sum(1 for o in ex_obs if not o.is_transcript and o.state == STATE_UNKNOWN),
                "转抄记录": sum(1 for o in ex_obs if o.is_transcript),
                "口径外记录": sum(
                    1 for o in ex_obs
                    if not o.is_transcript and o.state != STATE_UNKNOWN and not o.on_plan_post
                ),
                "同源事件": sum(1 for e in ex_events if e.shared),
            },
        }
    return features


def typing_section(registers: Registers, events: list[Event], observations) -> dict:
    dev_ids = {eid for eid, ex in registers.exercises.items() if ex.fold == "development"}
    types, supports = discover_types(registers, events, dev_ids)
    assignments = assign_types(registers, events, types)
    unclassified = {
        event.key: event_diagnosis(event, assignments[event.key])
        for event in events
        if not assignments[event.key]
    }
    return {
        "口径说明": "类型只来自现场观测、预案链路与排演干预条件，不使用事后整改分类",
        "类型": [ftype.to_dict(supports[ftype.type_id]) for ftype in types],
        "事件归属": {event.key: assignments[event.key] for event in events},
        "未归类": unclassified,
        "逐演练特征": exercise_features(registers, events, assignments, observations),
    }, types, supports


def sensitivity_section(
    registers: Registers, events: list[Event], types: list[FailureType], observations
) -> dict:
    """类型对缺失和记录口径的敏感性。各口径仅作压力测试，不改变默认口径。"""
    base = assign_types(registers, events, types)
    loose = assign_types(registers, events, types, accept_offplan=True)
    statuses = node_statuses(registers, observations)
    report: dict[str, dict] = {}
    for ftype in types:
        entry: dict = {}
        if ftype.kind == "segment":
            (node, _), = ftype.pattern
            unknown_ex = sorted(
                ex_id for ex_id, nodes in statuses.items()
                if nodes.get(node, {}).get("状态") == STATE_UNKNOWN
            )
            entry["缺失口径压力"] = {
                "说明": "未知绝不默认填失败；此处仅给出若误按不利计的支持上界",
                "相关未知演练": unknown_ex,
                "支持上界增量": len(unknown_ex),
            }
        else:
            entry["缺失口径压力"] = {"说明": "共路同现型的缺失压力见各成员段的单段表现型"}
        base_hits = {e.key for e in events if ftype.type_id in base[e.key]}
        loose_hits = {e.key for e in events if ftype.type_id in loose[e.key]}
        gained = sorted(loose_hits - base_hits)
        entry["岗位口径压力"] = {
            "说明": "默认只计预案观察岗位记录；此处为若接受口径外记录的变化",
            "新增事件": gained,
            "新增事件数": len(gained),
        }
        corroborated = sorted(e.key for e in events if ftype.type_id in base[e.key] and e.corroborated_nodes())
        entry["转抄口径"] = {
            "说明": "转抄只佐证不独立；若计为独立会虚增证据",
            "有转抄佐证的事件": corroborated,
        }
        shared_hits = sorted(e.key for e in events if ftype.type_id in base[e.key] and e.shared)
        entry["同源口径"] = {
            "说明": "同源信号为同一次故障；按记录拆分会把一次故障计为多起",
            "同源多节点事件": shared_hits,
        }
        report[ftype.type_id] = entry
    return report


def stability_section(registers: Registers, events: list[Event]) -> dict:
    """以整场降级条件和地区留出检验稳定程度，并把类型套用到独立留档。"""
    dev_ids = {eid for eid, ex in registers.exercises.items() if ex.fold == "development"}
    full_types, full_support = discover_types(registers, events, dev_ids)
    full_ids = {t.type_id for t in full_types}
    holdouts: dict[str, dict] = {}
    for axis, attr in (("降级条件", "mode"), ("地区", "district")):
        values = sorted({getattr(ex, attr) for ex in registers.exercises.values() if ex.fold == "development"})
        for value in values:
            subset = {eid for eid in dev_ids if getattr(registers.exercises[eid], attr) != value}
            sub_types, _ = discover_types(registers, events, subset)
            sub_ids = {t.type_id for t in sub_types}
            holdouts[f"留出{axis}={value}"] = {
                "消失类型": sorted(full_ids - sub_ids),
                "新增类型": sorted(sub_ids - full_ids),
            }
    per_type: dict[str, dict] = {}
    for ftype in full_types:
        support = full_support[ftype.type_id]
        by_mode: dict[str, int] = {}
        by_district: dict[str, int] = {}
        for eid in support:
            exercise = registers.exercises[eid]
            by_mode[exercise.mode] = by_mode.get(exercise.mode, 0) + 1
            by_district[exercise.district] = by_district.get(exercise.district, 0) + 1
        lost_in = sorted(k for k, v in holdouts.items() if ftype.type_id in v["消失类型"])
        per_type[ftype.type_id] = {
            "支持场数": len(support),
            "按降级条件": by_mode,
            "按地区": by_district,
            "留出下消失": lost_in,
            "稳定": not lost_in,
        }
    hold_ids = {eid for eid, ex in registers.exercises.items() if ex.fold == "holdout"}
    hold_events = [e for e in events if e.exercise in hold_ids]
    strict = assign_types(registers, hold_events, full_types)
    loose = assign_types(registers, hold_events, full_types, accept_offplan=True)
    holdout_apply = {
        "严格岗位口径": {
            t.type_id: sum(1 for e in hold_events if t.type_id in strict[e.key]) for t in full_types
        },
        "接受口径外记录": {
            t.type_id: sum(1 for e in hold_events if t.type_id in loose[e.key]) for t in full_types
        },
        "未归类事件": {
            e.key: event_diagnosis(e, strict[e.key]) for e in hold_events if not strict[e.key]
        },
    }
    return {"整组留出": holdouts, "逐型稳定": per_type, "留档套用": holdout_apply}


def manifestation_trigger_section(registers: Registers, events: list[Event]) -> dict:
    """共同表现却触发条件不同的事件组：单次复演不能证明全部解除。"""
    groups: dict[str, list[dict]] = {}
    for event in events:
        exercise = registers.exercises[event.exercise]
        for node, phenomenon in event.adverse().items():
            link = registers.link(exercise.plan, node)
            groups.setdefault(phenomenon, []).append(
                {
                    "演练": event.exercise,
                    "节点": node,
                    "段触发": link.trigger if link else None,
                    "降级条件": exercise.mode,
                    "分折": exercise.fold,
                }
            )
    report: dict[str, dict] = {}
    for phenomenon, items in sorted(groups.items()):
        triggers = sorted({i["段触发"] for i in items})
        modes = sorted({i["降级条件"] for i in items})
        report[PHENOMENON_LABELS.get(phenomenon, phenomenon)] = {
            "表现": phenomenon,
            "涉及段触发": triggers,
            "涉及降级条件": modes,
            "不可互相证明解除": len(triggers) > 1 or len(modes) > 1,
            "事件": items,
        }
    return report


def version_mapping_section(registers: Registers, types: list[FailureType]) -> dict:
    """类别跨预案版本的对应关系：分类变化不得当作险情频率变化。"""
    diffs = version_diffs(registers)
    per_type: dict[str, dict] = {}
    for ftype in types:
        nodes = sorted({node for node, _ in ftype.pattern})
        changed = {node: diffs[node] for node in nodes if node in diffs}
        if not changed:
            status = "同口径可比"
        elif ftype.kind == "composite" and any("path" in c for c in changed.values()):
            status = "不可直接比较：共路基础在版本间变化，频率需按版本分列"
        elif any("path" in c or "fallback" in c for c in changed.values()):
            status = "可比但链路基础变化，对比需注明"
        else:
            status = "可比但记录口径变化，对比需注明"
        per_type[ftype.type_id] = {
            "涉及节点": nodes,
            "版本间变化": changed,
            "历史对比口径": status,
        }
    return {
        "说明": "历史对比只看同一版本口径，或按逐型对应关系注明；分类变化不得当作险情频率变化",
        "节点链路版本差异": diffs,
        "逐型对应": per_type,
    }
