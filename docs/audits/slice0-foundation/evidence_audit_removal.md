# evidence_audit 机械搬运件删除记录

## 结论

从 `xiaoro-fresh` 移除机械搬运进来的 `evidence_audit` 实现及其测试。
原因：严格逻辑审计确认它继承了旧仓库的缺陷（认错商品、旧品类表已与
当前 103 条 Canonical 失配 33 条、商品编号隐式转换、指纹与真实输入脱钩、
充当第二 Canonical 权威）。这些属于旧业务逻辑本身的问题，不是搬运抄错。

采用「参考不搬运」：删除旧实现，将来按新合同重写；保留可复用的资产。

## 删除范围

- `tools/evidence_audit/`（8 个模块，2271 行）
- `tests/tools/evidence_audit/`（7 个测试，1716 行）

## 安全性

- 生产代码零引用：`app/` 下无任何模块 import `tools.evidence_audit`
  （`check_boundaries.py` 仅有「禁止 import」的护栏规则，非依赖）。
- 因此删除不影响任何现有运行链路。

## 保留的资产（删代码不删需求）

- 来源清单与逐文件 SHA：`evidence_audit_source_manifest.csv`（永久保留）。
- 测试 fixture：`tests/fixtures/evidence_audit/*.json`（重写时复用）。
- 边界护栏：`check_boundaries.py` 的 `SEALED_TOOLING_IMPORT` 规则及其
  反例测试保留不变，防止旧实现被重新引入运行时。
- 本次审计缺陷结论与去留矩阵（见对话审计报告）。

## 将来重写必须满足的铁律

1. 商品编号严格类型，拒绝 `36.9` / `True` / 数字字符串的隐式转换。
2. 证据归属对不上即 fail-closed，不静默写入。
3. 平台编号重复或冲突直接报错，不后写覆盖。
4. 名称 / 品牌 / 品类任一变化，输入指纹必须变化。
5. 不建立第二 Canonical 权威，只作审计投影 / 校验器。
6. 品类判断由新 Canonical 体系驱动，不使用旧写死品类表。
