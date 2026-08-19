# Slice 1.3 修护精华纵切设计

状态：对话设计已确认，等待书面复核
日期：2026-08-07
实现工作区：`/Users/bytedance/Desktop/xiaoro-fresh`
分支：`rebuild`

## 1. 背景

当前新主链已经完成一条真实的文本防晒纵切：

- 六层后端使用强类型合同通信；
- Canonical 商品事实经过 manifest 和 SHA 校验；
- 预算、肤质和成分排除执行严格决策；
- 独立 `app.guide_runtime` 可在最小依赖环境启动；
- SSE、商品图片、平台链接和共享聊天页已经完成浏览器闭环。

但当前能力仍被写明为 `slice1_text_sunscreen`。这只能证明一条防晒场景
可运行，尚未证明六层架构可以在不复制主流程、不搬旧实现的前提下承载第二类
业务规则。

下一步不搬运旧仓库的 `presenter.py`、Agent 或意图链。旧代码只用于提取失败
案例和业务经验。新仓库继续从公开合同和真实 Canonical 证据向上生长。

## 2. 目标

新增一条“修护精华”文本导购纵切，并与现有防晒能力共同运行在干净运行时中。

核心验收句：

```text
500 元内敏感肌修护精华
```

本纵切必须同时证明：

1. 精华类目能够被准确理解和召回；
2. “修护”是可审计的结构化功效约束，不是营销词匹配；
3. 预算、功效、成分排除和肤质口径在决策层统一执行；
4. 商品卡能展示被授权的修护证据和数据缺失提示；
5. 现有防晒结果、排序内核和运行边界不发生漂移。

## 3. 非目标

本 Slice 不实现：

- 美白、抗老、保湿等其他精华功效；
- 通用的全部护肤类目引擎；
- 多轮追问、候选集记忆或用户画像；
- 图片识别、图片向量检索或 OCR；
- LLM 意图识别、LLM 选品或 LLM winner；
- 数据库、Redis、Milvus 或旧 `app.main` 接入；
- Canonical 数据补写或缺失事实猜测；
- 旧 `presenter.py`、Agent、V1/V2 服务的迁入或包装。

## 4. 方案选择

采用“单场景纵切”，不采用以下两种路线：

1. 只把防晒的预算和肤质筛选复制到精华。该方案没有验证精华的核心功效需求。
2. 一次支持所有精华功效。该方案会把词义、功效冲突和证据缺失同时引入，
   超出一个可审计 Slice 的范围。

本 Slice 只新增 `repair_serum`，后续功效必须复用本次合同和门禁逐项增加。

## 5. 业务口径

### 5.1 类目

新增主题 `SERUM`。本 Slice 的 Canonical 类目家族只包含：

```text
精华
精华液
```

以下类目不自动并入：

```text
精华水
眼部精华
面霜
乳液
```

类目名称相似不能代替业务同类。类目家族仍由 retrieval 层拥有。

### 5.2 修护功效

新增受控功效 `REPAIR`。只有用户明确表达“修护”时才生成该约束。

当用户请求修护精华时：

- `efficacy` 为 known 且审核值包含“修护”：功效匹配；
- `efficacy` 为 known 但不含“修护”：明确不匹配，排除；
- `efficacy` 为 unknown：证据不足，排除；
- `efficacy` 为 conflict：事实冲突，排除并记录风险。

功效是本场景的硬条件。系统不得把商品名、营销描述或原始文本中的“修护”
当作已审核功效。

### 5.3 预算

沿用现有严格预算口径：

- 价格 known 且满足上下限才可继续决策；
- 价格 unknown 或 conflict 直接排除；
- 预算小于或等于 0 转澄清；
- 不设置人为预算上限；
- 小数、区间、下限和上限保持原方向。

### 5.4 肤质 A2

沿用 A2，并补清敏感肌语义：

- 明确写明“敏感肌适用”等正向证据：`matched`；
- 明确写明“敏感肌除外/不适用”：`mismatch`，排除；
- 只写“多种肤质适用”等泛化表述，未明确覆盖敏感肌：`unknown`；
- 肤质字段缺失：`unknown`。

`unknown` 商品保留、排在明确匹配之后，并显示“肤质数据缺失/未确认”。
如果所有入选商品都是 unknown，不指定唯一 winner。

### 5.5 成分排除

继续沿用 fail-closed：

- 审核事实确认成分存在：排除；
- 审核事实确认该成分不存在：通过；
- 没有“不含该成分”的审核证据：排除并说明证据缺失。

精华类目加入后，否定解析的类目后缀必须正确剥离。例如：

```text
不要酒精的修护精华
```

应生成排除项 `酒精`，不能生成 `酒精的修护精华`。

## 6. 六层设计

### 6.1 Understanding

新增：

- `TopicCode.SERUM`
- `EfficacyTarget.REPAIR`
- `EfficacyDraft`

精确解析器负责：

- 把“精华/精华液”解析为 `SERUM`；
- 把明确“修护”解析为 `REPAIR`；
- 保持预算、肤质和否定项的现有精确解析。

本层不读商品、不判断功效真假、不选品。

### 6.2 Intent

新增 `EfficacyConstraint`，由 `EfficacyDraft` 编译。

任务规则：

- 防晒请求保持现有行为；
- 精华 + 修护进入 `recommend`；
- 只有精华、没有修护诉求时进入 `clarify`；
- 精华中的其他未支持功效不得静默退化成普通精华推荐；
- 没有支持类目时进入 `clarify`。

建议澄清文案：

```text
当前精华纵切先支持修护诉求，请确认你是否在找修护精华。
```

### 6.3 Retrieval

`category_taxonomy` 增加 `SERUM` 家族。召回仍只返回：

- `product_id`
- Canonical 类目证据状态

retrieval 不读取功效决定 winner，不因名称带“修护”而扩召回。

### 6.4 Decision

`DecisionProductFacts` 增加：

- `efficacy`
- `efficacy_state`

过滤顺序固定为：

```text
价格证据
-> 预算
-> 功效证据
-> 成分排除
-> 肤质 A2
-> 稳定排序
```

`CandidateEvaluation` 增加结构化功效结果：

- `efficacy_match`
- `matched_efficacies`

新增明确 disposition：

- `excluded_efficacy_mismatch`
- `excluded_efficacy_unknown`

排序继续复用锁定内核。入选商品的业务排序键保持：

```text
肤质明确匹配优先
-> 肤质 unknown
-> 价格升序
-> product_id 兜底
```

价格用于稳定排序，不得被文案描述成质量更好。

### 6.5 Presentation

`ProductCardFacts` 和 `ProductCard` 增加 `category`，由展示事实端口透传
Canonical 审核类目。前端适配器不得继续把类目写死成“防晒”。

`ProductCard` 同时增加 `matched_efficacies`。该字段只能来自
`CandidateEvaluation` 的已匹配审核事实，展示层不重新读取或解释 Canonical。

卡片至少显示：

- 商品身份、品牌和参考价；
- 真实商品图和平台链接；
- “已审核修护功效”；
- 肤质 `matched/unknown`；
- 商品身份、图片或其他事实缺失 warning。

核心场景的总结文案应表达：

```text
已找到有审核修护功效且符合预算的候选，但现有敏感肌适配证据不足，
暂不指定唯一推荐。
```

展示层不得改变商品顺序、增加候选或把 unknown 写成适合。

### 6.6 Feedback

保持 `SKIPPED_SLICE_SCOPE`。本 Slice 不伪造反馈落库成功。

## 7. 数据流

```text
UserTurn("500 元内敏感肌修护精华")
  -> StructuredUnderstanding(
       topic=SERUM,
       budget.max=500,
       skin=SENSITIVE,
       efficacy=REPAIR
     )
  -> TaskPlan(mode=recommend)
  -> SERUM category retrieval
  -> authorized decision facts
  -> budget + repair efficacy + A2 decision
  -> ResponsePlan with evidence-backed ProductCard
  -> typed SSE
  -> legacy frontend compatibility adapter
  -> shared chat page
```

## 8. 真实数据锁定

当前 Canonical 中，`精华/精华液` 共 16 个候选。核心验收句经过类目、预算和
修护功效过滤后，应只保留：

```text
91  玉泽皮肤屏障修护精华乳50ml  88.00
38  理肤泉新B5多效修护精华      294.00
```

两者的审核功效均包含“修护”，但 `suitable_skin` 只写“多种肤质适用”，
没有明确敏感肌适配证据。因此：

```text
ordered_product_ids = [91, 38]
winner_status = INSUFFICIENT_FOR_WINNER
winner_product_id = null
skin_match = unknown, unknown
matched_efficacies = ["修护"], ["修护"]
```

如果加上“不要酒精”，两者都没有经审核的 `verified_absences=酒精`，应
fail-closed 为无候选，而不是猜测无酒精。

## 9. 运行时与页面

干净运行时继续作为正式入口，不接旧 `app.main`。

运行范围由：

```text
slice1_text_sunscreen
```

升级为：

```text
slice1_text_skincare
```

`/health` 明确声明能力：

```json
{
  "status": "healthy",
  "runtime": "guide",
  "scope": "slice1_text_skincare",
  "capabilities": ["sunscreen", "repair_serum"]
}
```

页面状态显示：

```text
文本护肤 · 防晒/修护精华
```

图片入口和反馈按钮继续隐藏。SSE URL 和现有事件类型保持不变；只扩展
`ProductCard` 的结构化功效字段。

## 10. 错误与澄清

- 不支持的类目：返回可见澄清，不进入旧 Agent；
- 精华缺少修护诉求：返回精华范围澄清；
- 预算非法：沿用现有预算澄清；
- 没有候选：返回正常 `NO_CANDIDATE` 结果，不抛内部错误；
- 内部异常：只返回 terminal `GUIDE_INTERNAL_ERROR`，不泄漏异常详情；
- 图片请求：继续明确说明当前运行时不支持图片。

正常流只有一个 `end`。异常流以 `error` 终止，不再发送伪成功事件。

## 11. 测试与门禁

### 11.1 合同与解析

- `TopicCode.SERUM` 和 `EfficacyTarget.REPAIR` 严格类型测试；
- 精华、精华液、修护及组合句解析；
- 精华缺少修护时澄清；
- 美白/抗老精华不被误判为已支持；
- 精华否定项后缀正确剥离；
- 未知 constraint kind 继续拒绝。

### 11.2 召回与事实端口

- SERUM 只召回 `精华/精华液`；
- `精华水/眼部精华` 不进入；
- efficacy known/unknown/conflict 映射正确；
- 商品 ID 错绑继续 fail-closed。

### 11.3 决策

- 修护 known match 入选；
- known mismatch 排除；
- unknown/conflict 排除并留下风险；
- 敏感肌明确匹配、明确排除和泛化 unknown 分开处理；
- 成分排除继续 fail-closed；
- 锁定核心结果 `[91, 38]` 和
  `INSUFFICIENT_FOR_WINNER`。

### 11.4 回归

- 防晒核心查询继续返回原锁定的 11 个商品 ID；
- 防晒 SSE 顺序和页面三张卡不变；
- 排序内核 SHA 保持：
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`；
- Canonical 和图片资产文件不修改；
- 双 boundary checker 零违规。

### 11.5 HTTP 与浏览器

正式 Uvicorn 从 `/tmp` 启动，验证：

- `/health` 的 scope 和 capabilities；
- 防晒 SSE 回归；
- 修护精华 SSE 返回 `[91, 38]`；
- 页面显示两张真实商品卡、图片、平台链接和修护证据；
- 页面显示肤质证据不足，不显示唯一推荐；
- 无 page error、无失败商品图片请求；
- 图片和反馈入口保持隐藏。

## 12. 保护范围

本 Slice 不得修改：

- `app/main.py`
- `app/services/**`
- `app/database/**`
- 旧仓库 `xiaoro-shopping-master`
- Canonical 和图片资产
- `app/guide/decision/deterministic_ranking.py`

允许修改：

- `app/guide/**` 中与本纵切直接相关的合同和实现；
- `app/guide_runtime/**` 的能力声明；
- SSE 前端兼容 adapter；
- `app/static/chat.html` 的功效证据展示和范围文案；
- 对应 tests、gates 和文档。

## 13. 验收标准

- 核心句被解析为预算、敏感肌、精华和修护四个结构化约束；
- 真实结果严格锁定为 `[91, 38]`；
- 两张卡均显示审核过的修护功效；
- 两张卡均如实标注敏感肌适配证据不足；
- 不产生虚假的唯一 winner；
- “不要酒精”在缺少 verified absence 时返回无候选；
- 精华水和眼部精华不被错误召回；
- 防晒全链路无回归；
- 独立运行时、HTTP、SSE 和浏览器门禁全绿；
- 保护文件、Canonical 和排序 SHA 无漂移。

完成本 Slice 后，再单独设计多轮追问。多轮不得在本次精华纵切中顺带实现。
