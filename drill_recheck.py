"""整改复验核对：触发条件、替代链保障、观测能力、共用转发点影响与结案核准。

每个复验申请核对三件事：可重复触发的条件、替代链旧保障、复验观测能力；
再核对共用转发点对未打算复验村的影响。结案后若后续资料改变原事件结构，
或复验偏离预定条件，重新核准哪些整改可以结案、哪些必须另验，
并保留曾采用的解释与未解除的暴露。
"""

from __future__ import annotations

from drill_ledger import (
    STATE_ADVERSE,
    STATE_OFFPLAN,
    STATE_UNKNOWN,
    Registers,
    apply_revisions,
    build_events,
    node_statuses,
    version_diffs,
)
from drill_typing import assign_types

CLOSEABLE = ("可结案", "结案有效")


def _event_summary(events, assignments: dict[str, list[str]]) -> list[dict]:
    return [
        {
            "事件": event.key,
            "确证失效": event.adverse(),
            "口径外证据": event.offplan_known(),
            "未知": event.unknown_nodes(),
            "类型": assignments.get(event.key, []),
        }
        for event in sorted(events, key=lambda e: e.key)
    ]


def _structure(events, assignments) -> dict[str, dict]:
    return {
        event.key: {"确证失效": event.adverse(), "类型": assignments.get(event.key, [])}
        for event in events
    }


def evaluate_check(registers: Registers, check, types, changes_now: list[dict]) -> dict:
    exercise = registers.exercises[check.exercise]
    link = registers.link(check.version, check.node)
    replay = registers.replays.get(check.check)
    defects: list[str] = []
    notes: list[str] = []

    # 一、可重复触发的条件
    condition = "一致"
    if link is None:
        defects.append(f"{check.version} 预案无节点 {check.node} 的链路")
    else:
        if link.trigger != check.mode:
            defects.append(
                f"复验条件 {check.mode} 与该段预案触发 {link.trigger} 不符，不能重复触发原机制"
            )
        if check.mode != exercise.mode:
            if exercise.mode == "mixed":
                condition = "部分"
                notes.append("原演练为混合降级，复验只覆盖单一条件，原暴露的确切触发条件不能确证")
            else:
                condition = "偏离"
                defects.append(f"复验条件 {check.mode} 偏离原演练降级条件 {exercise.mode}")

    # 二、替代链旧保障（复验期间主链断开时依赖的旧保障路径）
    fallback = link.fallback if link else None

    # 三、复验观测能力
    if replay is None:
        defects.append("无复验记录")
    else:
        if replay.observed_mode != check.mode:
            defects.append(f"实际复验条件 {replay.observed_mode} 偏离预定条件 {check.mode}")
        if check.node not in replay.covered_nodes:
            defects.append(f"复验未覆盖节点 {check.node}")
        if replay.completeness != "complete":
            defects.append(f"复验观测不完整（{replay.completeness}）")
    if link is not None and link.observe not in check.observed:
        defects.append(
            f"现场可观察岗位 {list(check.observed)} 不含该段预案观察岗位 {link.observe}"
        )

    # 时序：结案不得早于复验执行
    if check.state == "closed" and replay is not None and replay.day > check.day:
        defects.append(f"结案（第 {check.day} 日）早于复验执行（第 {replay.day} 日）")

    # 共用转发点影响面：同一路径上未打算复验的村
    path_villages: list[str] = []
    side_villages: list[str] = []
    listed_not_on_path: list[str] = []
    mechanism_villages: list[str] = []
    if link is not None:
        same_path = registers.path_links(check.version, link.path)
        path_villages = sorted({l.village for l in same_path})
        side_villages = [v for v in path_villages if v not in check.affected]
        listed_not_on_path = [v for v in check.affected if v not in path_villages]
        mechanism_villages = sorted(
            {l.village for l in same_path if l.trigger == link.trigger}
        )
        if side_villages:
            notes.append(
                f"共用转发点 {link.path} 还服务未列入复验范围的村 {side_villages}，停用将影响它们"
            )
        if listed_not_on_path:
            notes.append(
                f"预定涉及村 {listed_not_on_path} 不在 {check.version} 预案 {link.path} 段影响面内"
            )

    # 后续资料对原事件证据的改写
    related = [
        c for c in changes_now
        if c["record"].startswith(f"{check.exercise}-") and c["日"] > check.day
    ]
    rewritten = [c for c in related if c["效果"] == "改写"]
    if rewritten:
        if check.state == "closed":
            defects.append("结案后又有后续资料改写原事件证据，结案依据需重新核准")
        else:
            defects.append("申请后又有后续资料改写原事件证据，复验目标需按新口径重新核准")

    # 曾采用解释（结案日口径）与当前解释
    obs_then, _ = apply_revisions(registers, as_of_day=check.day)
    events_then = [e for e in build_events(registers, obs_then) if e.exercise == check.exercise]
    obs_now, _ = apply_revisions(registers)
    events_now = [e for e in build_events(registers, obs_now) if e.exercise == check.exercise]
    assign_then = assign_types(registers, events_then, types)
    assign_now = assign_types(registers, events_now, types)
    structure_then = _structure(events_then, assign_then)
    structure_now = _structure(events_now, assign_now)
    changed_keys = sorted(
        key for key in set(structure_then) | set(structure_now)
        if structure_then.get(key) != structure_now.get(key)
    )

    # 版本差异提示：覆盖范围若按旧版本拓扑理解会得出不同结论
    diffs = version_diffs(registers).get(check.node)
    if diffs:
        notes.append(f"该段链路在版本间有变化 {diffs}，覆盖范围须按 {check.version} 口径理解")

    can_close = not defects
    decision = (
        ("结案有效" if can_close else "需重新核准并另验")
        if check.state == "closed"
        else ("可结案" if can_close else "需另验或补正")
    )
    covered_nodes = [check.node] if can_close else []
    covered_villages = mechanism_villages if can_close else []
    return {
        "复验": check.check,
        "演练": check.exercise,
        "节点": check.node,
        "状态": check.state,
        "预定条件": check.mode,
        "原演练条件": exercise.mode,
        "触发条件核对": condition,
        "替代链旧保障": fallback,
        "影响面": {
            "同机制段村": mechanism_villages,
            "同转发点村": path_villages,
            "未列入而受影响": side_villages,
            "列入但不在影响面": listed_not_on_path,
        },
        "缺陷": defects,
        "提示": notes,
        "结论": decision,
        "覆盖范围": {
            "节点": covered_nodes,
            "村": covered_villages,
            "依据": (
                f"{check.version} 预案 {link.path} 段 {link.trigger} 机制"
                if link is not None
                else None
            ),
            "说明": "一次通过的证据只覆盖它真能发现原机制重现的范围",
        },
        "曾采用解释": _event_summary(events_then, assign_then),
        "当前解释": _event_summary(events_now, assign_now),
        "解释变化": changed_keys,
        "后续资料": related,
    }


def recheck_section(registers: Registers, types) -> dict:
    _, changes_now = apply_revisions(registers)
    results = {
        check.check: evaluate_check(registers, check, types, changes_now)
        for check in sorted(registers.checks.values(), key=lambda c: c.check)
    }
    covered_by_exercise: dict[str, set[str]] = {}
    for result in results.values():
        if result["结论"] in CLOSEABLE:
            covered_by_exercise.setdefault(result["演练"], set()).update(
                result["覆盖范围"]["节点"]
            )
    obs_now, _ = apply_revisions(registers)
    statuses = node_statuses(registers, obs_now)
    events_now = build_events(registers, obs_now)
    assign_now = assign_types(registers, events_now, types)
    for result in results.values():
        ex_id = result["演练"]
        covered = covered_by_exercise.get(ex_id, set())
        exposures: list[dict] = []
        unknown_nodes: list[str] = []
        for node, info in sorted(statuses.get(ex_id, {}).items()):
            if info["状态"] == STATE_UNKNOWN:
                unknown_nodes.append(node)
            elif info["状态"] == STATE_ADVERSE and node not in covered:
                type_ids = sorted(
                    {
                        t
                        for e in events_now
                        if e.exercise == ex_id and node in e.adverse()
                        for t in assign_now[e.key]
                    }
                )
                exposures.append({"节点": node, "现象": info["现象"], "类型": type_ids})
            elif info["状态"] == STATE_OFFPLAN:
                adverse = [p for p in info["现象"] if p != "handled"]
                if adverse:
                    exposures.append(
                        {
                            "节点": node,
                            "现象": adverse,
                            "类型": [],
                            "备注": "岗位口径外记录，需先核正记录口径",
                        }
                    )
        result["未解除暴露"] = exposures
        result["未知不默认失败"] = unknown_nodes
    return results
