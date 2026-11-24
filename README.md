# 预警联动演练的失效分型与交叉复验

这些演练台账是本地合成资料，使用虚构编号。CSV 采用 UTF-8 和带表头的逗号分隔格式。同一单元内用竖线列出的值表示多项或候选集合，含义见各表说明。空值通常表示未记录或不适用，明确的零会保留为 0。

## 资料

- `data/plans.csv`  排演条件跨版本变化，不作为事后分型真值。fallback 是该节点下游获准启用的保障路径。observe 为可观察岗位。
  字段为 `plan / node / village / trigger / observe / fallback / path`。
- `data/checks.csv`  复验申请和已提交的结案记录。affected 是预定涉及的村，observed 为现场实际可以观察的岗位。
  字段为 `check / exercise / node / version / mode / affected / observed / state / day`。
- `data/revisions.csv`  后续目击和保障资料。record 指向 observations 的原现场条目；value 新提供的是观测事实。
  字段为 `id / record / reported_day / field / value`。
- `data/exercises.csv`  降级模式由排演记录给出，可作为干预条件。资料分为开发和独立留档的演练，留档不提供机制标签。
  字段为 `exercise / plan / district / mode / fold`。
- `data/observations.csv`  现场独立或抄录事实。signal_ident 相同表示同源。phenomenon 是直接观察，空白表示岗位未知。
  字段为 `record / exercise / node / observer / observability / phenomenon / signal_ident`。
- `data/replays.csv`  实际复验的降级条件和可观察节点，并非结案结论。
  字段为 `check / exercise / observed_mode / covered_nodes / completeness / day`。

## 核对台账

环境为 Python 3.11.2，只使用标准库。在仓库根目录运行下列命令检查文件格式、表头和基础外键。输出为各张源表可读行数。

```sh
python3 input_audit.py
python3 -m unittest discover -s tests -v
```

可在第一条命令后指定另一个输入目录，目录中的同名 CSV 沿用上述格式。列名和基础引用清单见 `input_contract.json`。

## 失效分型与交叉复验

```sh
python3 drill_report.py [台账目录] [--json 报告路径]
```

每办完一轮演练，把新材料补进台账目录后重跑本命令即可继续核对；全部结果由输入确定性推出，不留中间状态。核对口径：

- `drill_ledger.py`  观测限定在能支持使用的局部链路：只计记录岗位与按时点有效预案 observe 岗位一致的现场记录；transcript 为转抄只作佐证；未知绝不默认填失败，handled 为确证未发生；revisions 按 reported_day 应用，可重现任一日口径；signal_ident 相同归为同一事件（同一次故障的多处表现）。
- `drill_typing.py`  从开发演练发现可解释类型（单段表现型与共路同现型），每型给出依据的链路共性。同一事件可属于多型，也可证据不足不归类。可查看类型对缺失与记录口径（岗位口径、转抄、同源拆分）的敏感性，按整场降级条件和地区留出检验稳定程度，并套用到独立留档。同表现不同触发的事件组标记为不可互相证明解除。版本对应给出各类别跨预案版本的适用关系，分类变化不得当作险情频率变化。分型不使用事后整改分类反填当时输入。
- `drill_recheck.py`  每个复验申请核对可重复触发的条件、替代链旧保障与复验观测能力；列出共用转发点停用对未打算复验村的影响；结案早于复验、复验偏离预定条件或后续资料改写原事件证据时，重新核准哪些整改可结案、哪些必须另验，并保留曾采用的解释、当前解释与未解除的暴露。一次通过的证据只覆盖它真能发现原机制重现的范围。
