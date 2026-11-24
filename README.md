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
