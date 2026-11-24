"""一轮核对的总装：读台账目录，输出失效分型与整改复验核对报告。

用法：
    python3 drill_report.py [台账目录] [--json 输出路径]

每办完一轮演练，把新材料补进台账目录后重跑本命令即可继续核对；
全部结果由输入确定性推出，不留中间状态。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from drill_ledger import apply_revisions, build_events, load_registers
from drill_recheck import recheck_section
from drill_typing import (
    manifestation_trigger_section,
    sensitivity_section,
    stability_section,
    typing_section,
    version_mapping_section,
)

ROOT = Path(__file__).resolve().parent


def full_report(location: Path | str) -> dict:
    registers = load_registers(location)
    observations, changes = apply_revisions(registers)
    events = build_events(registers, observations)
    typing, types, _ = typing_section(registers, events, observations)
    return {
        "台账概况": {
            "演练数": len(registers.exercises),
            "观测记录": sum(1 for o in observations if not o.is_transcript),
            "转抄记录": sum(1 for o in observations if o.is_transcript),
            "事件数": len(events),
            "后续资料": changes,
        },
        "失效分型": typing,
        "敏感性": sensitivity_section(registers, events, types, observations),
        "留出检验": stability_section(registers, events),
        "同表现不同触发": manifestation_trigger_section(registers, events),
        "版本对应": version_mapping_section(registers, types),
        "整改复验": recheck_section(registers, types),
    }


def _summarize(report: dict) -> str:
    lines: list[str] = []
    overview = report["台账概况"]
    lines.append(
        "台账概况：{演练数} 场演练，{事件数} 起事件，后续资料 {n} 条".format(
            n=len(overview["后续资料"]), **overview
        )
    )
    typing = report["失效分型"]
    lines.append(f"\n失效类型 {len(typing['类型'])} 个：")
    for ftype in typing["类型"]:
        lines.append(
            f"  {ftype['类型']}（{ftype['类别']}，支持 {ftype['支持场数']} 场）{ftype['共性链路']}"
        )
    lines.append(f"未归类事件 {len(typing['未归类'])} 起")
    stability = report["留出检验"]
    unstable = [tid for tid, info in stability["逐型稳定"].items() if not info["稳定"]]
    lines.append(f"\n留出检验：不稳定类型 {len(unstable)} 个：{unstable}")
    manifest = report["同表现不同触发"]
    mixed = [k for k, v in manifest.items() if v["不可互相证明解除"]]
    lines.append(f"同表现不同触发（不可互相证明解除）：{mixed}")
    mapping = report["版本对应"]
    lines.append(f"版本间链路变化节点：{sorted(mapping['节点链路版本差异'])}")
    lines.append("\n整改复验：")
    for cid, result in report["整改复验"].items():
        lines.append(f"  {cid}（{result['演练']} {result['节点']}）→ {result['结论']}")
        for defect in result["缺陷"]:
            lines.append(f"    缺陷：{defect}")
        for note in result["提示"]:
            lines.append(f"    提示：{note}")
        if result["未解除暴露"]:
            lines.append(f"    未解除暴露：{result['未解除暴露']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("location", nargs="?", type=Path, default=ROOT / "data", help="台账目录")
    parser.add_argument("--json", type=Path, default=None, help="完整报告 JSON 输出路径")
    args = parser.parse_args()
    report = full_report(args.location)
    print(_summarize(report))
    if args.json is not None:
        args.json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"\n完整报告已写入 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
