# 小 Ro Guide 分品类数据地基设计

状态：用户已批准书面设计
日期：2026-08-10
实现工作区：`/Users/bytedance/Desktop/xiaoro-fresh`
基线分支：`rebuild`
基线提交：`4dda1cae24082c385d01e756ed62f9d15c1894a3`

## 1. 目标

建立 Guide 自有、严格类型、可审计的分品类数据地基，使六类商品不再共用一套
通用字段语义，并为后续批量补充 HTML、OCR、官方资料和评论来源提供可重复工具。

本轮完成的是“规则、合同、工具和试点”，不是一次性填满 103 个商品：

- 六个品类画像进入 Guide 正式合同；
- 现有 39 种 Canonical 原始品类全部且仅映射到一个画像；
- 每个画像拥有明确的通用字段、专属字段和不适用字段；
- 每个字段明确证据来源、冲突策略、缺失策略和能力边界；
- 六个画像各选择两个 Canonical 商品，共 12 个试点；
- 建立 HTML/OCR 字段候选和评论候选的离线构建工具；
- 自动化只生成候选，人工批准后才进入正式事实资产；
- 现有 Guide、Canonical v1、排序和批准评论资产保持可复验。

## 2. 审计基线

专项审计结论：

- 原始天猫 HTML 中有 336 个评论候选；
- 111 个候选满足严格候选条件；
- 正式批准评论只有 6 条，覆盖商品 42、49、55；
- 评论商品覆盖率为 3/103，即约 2.9%；
- Canonical 包含 103 个商品和 39 种原始品类；
- Guide 正式 `TopicCode` 只有 `sunscreen` 和 `serum`；
- Canonical 当前统一包含 13 个字段；
- 排除 identity、brand、category、price 后，9 个领域字段只有
  239/927 为 `known`，已知率约 25.8%；
- 当前代码只有批准评论资产加载器，没有从原始 HTML 重建候选、审核队列和
  manifest 的正式工具；
- 专项 focused 测试 52 项通过。

因此当前方向正确，但不能宣称“所有品类均已按自己的字段模型完成”。旧工作区
`xiaoro-shopping-master` 中的 dynamic facet registry 仅作为只读参考，最终实现必须在
Guide 边界内重新设计，不复制 legacy 代码。

## 3. 设计原则

### 3.1 事实与能力分离

字段值和字段能做什么必须分开：

```text
value
resolved_state
source_refs
source_class
evidence_status
capabilities
```

允许的 capability：

```text
evidence
display
compare
hard_filter
soft_rank
```

默认只有 `evidence`。字段必须同时满足：

1. 对当前品类适用；
2. 来源类型获得该字段授权；
3. 状态为 `known`；
4. 没有阻断冲突；
5. capability 明确允许；

才能进入展示、比较、筛选或排序。

### 3.2 缺失不猜

- 缺失值保持 `unknown`；
- 同优先级冲突保持 `conflict`；
- 对当前画像无意义的字段为 `not_applicable`；
- OCR、评论和营销文案不得自动把字段升级成事实；
- `unknown`、`conflict` 和 `not_applicable` 不产生 winner、排序分或安全保证。

### 3.3 Canonical v1 保持只读

本轮不修改：

- `data/canonical/**`
- `app/services/**`
- `app/database/**`
- `app/guide/decision/deterministic_ranking.py`

Canonical v1 继续提供商品身份、品牌、原始品类和价格等权威核心字段。新增品类专属
事实进入 Guide 自有、内容寻址、人工批准的 category fact asset；它不能覆盖
Canonical 核心字段。

## 4. 六个品类画像

### 4.1 原始品类唯一映射

| 画像 | Canonical 原始品类 |
| --- | --- |
| `skincare` | 乳液、乳霜、爽肤水、眼部精华、眼霜、精华、精华水、精华液、面膜、面霜 |
| `suncare` | 防晒、防晒乳、防晒乳液、防晒隔离、防晒霜 |
| `base_makeup` | 妆前乳、散粉、气垫、气垫粉底、气垫粉底液、粉底液、蜜粉、遮瑕膏 |
| `color_makeup` | 单色眼影、口红、唇膏、腮红 |
| `cleanser` | 卸妆、卸妆水/洁肤液、卸妆洁肤液/卸妆水、卸妆膏、洁面/清洁、洁面乳/泡沫洁面乳、洁面乳/洁面泡沫、洁面泡沫、洁面霜/洁面、洁颜油/卸妆油、洁颜霜/卸妆膏 |
| `fragrance` | 香水 |

门禁要求：

- 39 种原始品类全部出现；
- 每种原始品类只映射一次；
- 新出现的未映射品类使构建失败；
- 不允许未知品类静默回退 `skincare`。

### 4.2 通用字段

所有画像共享：

```text
product_identity
brand
category
price
ingredients_present
verified_absences
safety
usage
```

其中 identity、brand、category、price 仍由 Canonical v1 独占权威。其余字段只有
批准事实才能获得 display/compare/filter/rank 能力。

### 4.3 专属字段

| 画像 | 专属字段 |
| --- | --- |
| `skincare` | efficacy、suitable_skin、texture、mechanism、clinical_evidence |
| `suncare` | spf_pa、water_resistance、reapplication、texture、suitable_skin |
| `base_makeup` | shade、finish、coverage、longevity、texture、suitable_skin |
| `color_makeup` | shade、finish、texture、longevity |
| `cleanser` | cleansing_form、cleansing_power、surfactant_type、rinse_behavior、double_cleanse、texture、suitable_skin |
| `fragrance` | fragrance_family、top_notes、heart_notes、base_notes、longevity、sillage |

字段名字是稳定机器键。中文别名只用于解析和展示，不得成为第二套字段。

## 5. 字段来源政策

来源分级：

```text
canonical_core
structured_official
official_packaging
official_description
ocr_packaging
ocr_ingredient_list
approved_consumer_review
unknown
```

授权规则：

- `canonical_core`：核心身份、品牌、品类、价格；
- `structured_official`：可提供事实、展示和按字段声明的比较能力；
- `official_packaging`：可提供包装明确标注的规格、SPF/PA、用法、色号等；
- `official_description`：默认 evidence/display，不自动 hard filter 或 rank；
- `ocr_packaging`：只作为观察，必须与原图定位和人工审核绑定后才能升级；
- `ocr_ingredient_list`：只证明识别到的成分文本，不证明功效、安全或未添加；
- `approved_consumer_review`：只生成体验事实和评论摘要，不生成配方、安全或商品硬事实；
- `unknown`：不得进入正式资产。

同一字段按来源优先级解析。不同来源的相同值可以合并 provenance；不同值必须记录
冲突，不得用“多数票”覆盖。

## 6. 12 个试点商品

每个画像选择两个同类 Canonical 商品：

| 画像 | 商品 ID |
| --- | --- |
| `skincare` | 38 理肤泉 B5 修护精华；91 玉泽屏障修护精华乳 |
| `suncare` | 53 理肤泉特护清盈防晒乳；57 碧柔水活防晒凝蜜 |
| `base_makeup` | 79 雅诗兰黛轻透持妆粉底液；80 阿玛尼权力持妆 PRO 粉底液 |
| `color_makeup` | 86 M.A.C See Sheer 口红；114 M.A.C 大子弹头 602 |
| `cleanser` | 69 植村秀臻萃养肤洁颜油；103 植村秀琥珀绿茶卸妆油 |
| `fragrance` | 120 祖玛珑英国梨与小苍兰；121 香奈儿五号之水 |

试点只批准能够回指来源的字段。没有可信来源的专属字段必须明确留空，不能为了达到
覆盖率填入推断值。

## 7. 数据流

### 7.1 品类事实

```text
raw HTML / product image / OCR / official document
-> source fingerprint
-> category profile
-> field-specific candidate extraction
-> normalization
-> duplicate/conflict detection
-> human review queue
-> approved fact decisions
-> atomic category fact JSONL + manifest
-> Guide category fact reader
-> evidence/display/compare/filter/rank projection
```

每条候选必须包含：

```text
candidate_id
product_id
category_profile
field_key
raw_value
normalized_value
source_class
source_locator
source_sha256
extraction_method
```

批准记录额外包含 reviewer、reviewed_at、decision 和 reason。生产资产不得包含原始
HTML、未脱敏 PII、本地绝对路径或未批准候选。

批准 category fact 数量允许为 0。没有新的人类批准决定时，manifest 仍需记录
`fact_count=0` 和 12 个试点 ID，reader 必须正常加载，覆盖报告把全部专属字段诚实标为
unknown。不得因为生产 sidecar 为空而创建伪事实。

### 7.2 评论来源

```text
original HTML
-> deterministic page candidate extraction
-> stable item + HTML hash + ordinal identity
-> exact duplicate collapse
-> PII / marketing / Q&A quarantine
-> human review queue
-> approved review JSONL + manifest + audit block
```

构建工具必须一次原子生成 JSONL、manifest 和审计机器块，禁止人工分别修改三者。
自动化不得改变批准状态。

历史 336 个总候选和 111 个严格候选来自此前审计，但三份原始 HTML 当前没有进入可复验
仓库。本轮只能：

- 用提交的脱敏 fixture 验证候选构建器；
- 保留历史 336/111 口径为 provenance，不表述为本轮重跑结果；
- 字节级保留现有 6 条批准来源；
- 只有重新取得并 hash 锁定原始 HTML 后，才允许声明真实复跑 336/111。

## 8. 组件边界

建议新增：

```text
app/guide/retrieval/category_profiles.py
app/guide/retrieval/category_fact_contracts.py
app/guide/retrieval/category_fact_reader.py
tools/guide_data/build_category_fact_candidates.py
tools/guide_data/build_review_candidates.py
tools/guide_data/promote_approved_category_facts.py
tools/guide_data/promote_approved_reviews.py
data/guide_category_facts/category_facts_v1.jsonl
data/guide_category_facts/category_facts_v1_manifest.json
```

共享入口、SSE 和前端只有 Integration Writer 可以修改。领域 worktree 只能提交自身模块、
资产构建工具和 focused tests。

## 9. 错误处理

- 未映射品类：构建失败；
- 未注册字段：拒绝；
- 字段不适用于画像：记录 `not_applicable`，不得入值；
- 来源未授权：进入 quarantine；
- hash、manifest 或产品归属不一致：加载失败；
- 同一稳定 ID 内容不同：加载失败；
- 冲突事实：记录 conflict，不展示 winner；
- OCR 不可用：输出 unavailable，不回退猜测；
- 评论来源不足：展示 verified absence，不生成假摘要；
- 构建中断：保留旧资产，临时文件不得替换生产文件。

## 10. 测试与门禁

### 10.1 合同门禁

- 六个画像键稳定；
- 39 种原始品类完整、唯一映射；
- 字段键、别名和来源策略无重复；
- 每个字段至少属于一个画像；
- 不适用字段不能获得值；
- 未授权来源不能获得能力。

### 10.2 数据门禁

- 12 个试点均可从 Canonical ID 定位；
- 每个 known 值都有非空 source refs；
- candidate、approved、quarantine 数量守恒；
- 构建输入顺序不影响输出和 hash；
- 重复执行字节级一致；
- `fact_count=0` 的合法资产可正常加载；
- 无批准值保持 unknown；
- 当前 6 条批准评论原样可复验。

### 10.3 行为门禁

- 六类文本请求进入 Guide，不再因缺少 TopicCode 落 legacy；
- 每类专属问题只请求适用字段；
- 同类比较只使用 compare-safe 字段；
- unknown/conflict 不改变 winner；
- 商品卡 ID 和顺序仍由后端合同决定；
- 评论和 OCR 不覆盖 Canonical 核心字段。

### 10.4 全量门禁

```text
focused category/data tests
Guide full
runtime full
compileall
app/guide boundary
app/guide_runtime boundary
git diff --check
protected path diff
ranking SHA
normal browser
adversarial browser
```

## 11. 并发与审计

初始采用 6 个 Agent：

1. Integration Writer：唯一集成写入者；
2. category contract worker；
3. data/review tooling worker；
4. routing/behavior worker；
5. test/browser verifier；
6. independent read-only auditor。

硬限制：

```text
active agents: 2..8
concurrent code writers: 0..4
integration writers: exactly 1 maximum
writers per file authority: exactly 1 maximum
```

集成和回归阶段降至 3 个 Agent。共享文件、未知回归、审计 finding 或资源争用出现时进入：

```text
freeze -> reproduce -> RED -> single-writer fix -> independent verify
```

每个能力循环只执行一次 opening full-file audit；确认 finding 必须 RED/GREEN，不能在同一
循环重复审计。最终使用独立的 `FINAL-CATEGORY-DATA-AUDIT`。

## 12. 明确不做

- 不一次性补齐 103 个商品；
- 不自动批准 HTML/OCR/评论候选；
- 不复制旧 V2 facet registry 实现；
- 不修改 Canonical v1 和旧服务；
- 不让评论、OCR 或营销文案直接影响 winner；
- 不在本轮处理全部发布阻断、前端视觉精修或生产部署；
- 不 push、不部署、不切流。

## 13. 完成条件

只有以下条件全部满足，Phase 3A 才能标记完成：

1. 六个画像及字段政策进入 Guide；
2. 39 种原始品类完整唯一映射；
3. 12 个试点的 approved/unknown/conflict 可机械复验；
4. 评论和品类事实均具备 fixture 可重复候选构建与原子 promotion 工具；
5. 六类正式文本链和同类比较通过；
6. focused、全量、runtime、边界和双浏览器门禁通过；
7. 唯一最终审计无未解决 P0–P2；
8. tasks/checklist 全部勾选；
9. 工作区干净；
10. 未执行 push、部署或流量切换。
