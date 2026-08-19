# XiaoRo 数据资产与路径无关性验收实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** 先验证并发布真实混合对话链路供小伙伴体验，再在不继续按句子修 Prompt 的前提下补齐 SMZDM 商品素材、图片资产、36/216 状态矩阵和最终浏览器验收。

**Architecture:** TurnMeaning v30 继续作为唯一开放语言翻译层，输出有限的 typed parent operation/concept/reference；代码只依据 typed atom、Canonical 商品身份、对象基数、会话状态和安全状态执行路由与展示。第一阶段只交付已验证的混合链路代码，图片和 SMZDM 数据不阻塞体验发布；第二阶段再按 `raw capture -> category review candidate -> approved asset` 接入数据，图片替换必须有 SKU、规格、来源和人工审核记录。

**Tech Stack:** Python 3.11、FastAPI、Pydantic v2、SQLite CAS state、typed SSE、DeepSeek V4 Pro、OpenCLIP ViT-B-32、NumPy、pytest、Playwright Chromium。

---

## 0. 执行优先级调整：混合链路体验先发布

用户要求将本计划的执行顺序调整为：

```text
1. 清理临时调试代码，验证混合链路正确性。
2. 只提交 typed 语义、状态和路由的已验证改动，推送 GitHub。
3. 让小伙伴先体验真实混合链路。
4. SMZDM 抓取、人工审核、图片替换和数字资产在体验发布后继续执行。
5. 最后完成 36/216 矩阵、真实浏览器复核和最终关闭。
```

本次 GitHub 推送明确排除：

```text
SMZDM 原始抓取和审核候选的半成品
尚未完成最终浏览器验收的图片替换
临时图片索引目录
调试日志、SQLite 临时状态和历史审计噪声
```

原资产任务保留，但不再阻塞混合链路体验发布；只有混合链路发布验收失败，才回到共享 typed 路由层修复。

## 0. 当前基线与昨天的架构教训

仓库：

```text
/Users/bytedance/Desktop/xiaoro-fresh
```

参考仓库：

```text
/Users/bytedance/Desktop/xiaoro-shopping-master
```

当前已经确认的事实：

```text
TurnMeaning v30 已冻结
多商品 suitability 的 typed 路由修复已出现在工作树
product_id=33 的小棕瓶图片已根据 SMZDM 页面 100ml 证据替换
Canonical 图片 manifest 已重建
103 款 OpenCLIP 图片索引已用项目 .venv 重建并通过 103/103 验收
上述内容尚未完成替换后的最终浏览器验收
```

昨天最重要的教训必须作为本计划的硬约束：

```text
不能看到一句失败句子，就给这句话加一个正则、同义词或分支。
先判断失败发生在哪一层：
  模型翻译、typed admission、身份绑定、路由、状态、数据还是展示。
如果模型已经正确表达了父概念，修复必须落在共享的 typed 架构责任层：
  对象基数、current_batch/current_item、状态继承、卡片类型和安全状态。
同一修复必须覆盖至少两个不同说法、一个反例，并通过 provider-parser 隔离和零 API 回放。
```

具体案例：

```text
推荐批次
  -> 问诊
  -> 回到刚才的两款商品
  -> 按当前状态判断哪款更适合
```

这里的根因不是某一句话没被 Prompt 识别，而是：

```text
suitability
+ current_batch
+ 多商品对象基数
+ consultation 状态仍然存在
```

没有在共享路由层收敛为 comparison。最终修复应表达为“多商品 suitability 进入比较处理器”，而不是匹配“哪款更适合”这句话。

## 1. 验收口径

### 1.1 普通路径无关性

对同一组 Canonical 商品、同一组用户事实、同一组安全条件：

```text
路径 A 到达状态 X
路径 B 到达状态 X
```

必须比较以下公共结果：

```text
processor family
resolved product IDs and order
current_batch/current_item/focus binding
public card type and card product IDs
price/specification presentation
conversation state version and active state
```

只要这些结果在没有新事实的情况下因历史路径不同而变化，就算路径污染。

### 1.2 允许的状态变化

以下情况不是路径污染，但必须被单独标记为 `expected_state_change`：

```text
用户主动引入新的安全条件或症状，触发安全升级
用户上传新的图片，形成新的 image bundle
用户明确修改预算、品类、商品或筛选条件
用户明确清空、重置或开启新会话
```

安全升级必须满足：

```text
只能升级或保持，不能因为路径不同而绕过硬条件
不能从安全状态偷偷降级到普通推荐
在同一安全事实下，升级结果必须路径一致
```

### 1.3 用户可见结果优先

测试不因内部等价枚举差异失败，优先断言：

```text
用户是否进入正确处理器族
商品是否绑定正确
是否返回正确的比较/推荐/问诊/知识/图片卡片
规格是否在价格行
是否出现错误拒答、错误重新识图或安全降级
```

### 1.4 退出条件

只有以下条件全部满足，才允许用户进行最终手测：

```text
SMZDM 候选和批准资产的来源、审核状态、规格和图片哈希完整
product_id=33 图片替换后的运行时和图片索引一致
36 条有向边全部覆盖
216 条三段路径全部覆盖
8-12 条长混合链通过，包括正序、逆序、重复进入和状态回切
推荐 -> 问诊 -> 回到两款商品适配比较通过
真实模型抽样结果没有模型翻译或路由严重错误
真实浏览器使用 DeepSeek 和真实润写通过
```

## 2. 文件边界

### 数据资产

```text
Create:
  data/guide_merchant_claims/smzdm_crawl_v1/
  tools/guide_data/crawl_smzdm_product_pages.py
  tools/guide_data/build_smzdm_review_candidates.py
  tools/guide_data/promote_smzdm_approved_assets.py
  tests/guide/data/test_smzdm_assets.py

Modify only after approval:
  data/guide_merchant_claims/merchant_claims_v1.*.jsonl
  data/guide_product_evidence/product_evidence_v1.*.jsonl
  data/canonical/seed_product_images_v1.jsonl
  data/canonical/seed_product_images_v1_manifest.json
  app/static/images/products/*
  data/guide_image_index/openclip_vit_b32_laion2b_s34b_b79k_v1/*
```

### 状态矩阵

```text
Create:
  tools/guide_gates/build_transition_matrix.py
  tools/guide_gates/run_transition_matrix.py
  tests/guide/tools/test_transition_matrix.py
  tests/fixtures/guide/transition_matrix/
    states.json
    pairwise_edges.jsonl
    triple_paths.jsonl
    long_walks.jsonl
    manifest.json
    truth.json
  docs/audits/continuous-conversation/transition-matrix/

Modify only when a failing shared-layer test proves the need:
  app/guide/intent/unified_turn_router.py
  app/guide/intent/transition_planning.py
  app/guide/application/text_recommendation_flow.py
  app/guide/application/unified_guide_flow.py
  tests/guide/intent/test_unified_turn_router.py
  tests/guide/application/test_text_recommendation_flow.py
```

### 最终浏览器验收

```text
Create or modify:
  tools/guide_gates/run_transition_browser_audit.py
  tests/guide/tools/test_transition_browser_audit.py
  docs/audits/continuous-conversation/browser-transition-matrix/
```

任何已有的未提交 debug 探针都必须在最终验收前清理，尤其是：

```text
app/guide/application/unified_guide_flow.py
```

生产代码不得保留向 `127.0.0.1:7777/event` 的调试请求。

## 3. Task 1：冻结工作树与清理调试残留

**Files:**

```text
Modify:
  app/guide/application/unified_guide_flow.py
  any file containing temporary debug instrumentation

Test:
  tests/guide/application/test_text_recommendation_flow.py
  tests/guide/intent/test_unified_turn_router.py
```

- [ ] **Step 1: 记录当前基线**

```bash
cd /Users/bytedance/Desktop/xiaoro-fresh
git status --short
git diff --stat
git diff -- app/guide/application/unified_guide_flow.py \
  app/guide/intent/unified_turn_router.py \
  app/guide/intent/transition_planning.py
```

Expected: 能明确区分 typed 路由修复、图片资产变更、测试证据和临时 debug 文件。

- [ ] **Step 2: 删除临时 debug 请求**

删除所有只用于本次诊断的 `urllib.request`、debug region 和本地事件上报代码；保留 typed translation、binding、route 的正式业务逻辑。

- [ ] **Step 3: 运行 provider-parser 隔离测试**

```bash
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/guide/intent/test_unified_turn_router.py \
  tests/guide/application/test_text_recommendation_flow.py -q
```

Expected: PASS；provider 路径不调用 legacy action parser。

- [ ] **Step 4: 扫描新增语义补丁**

```bash
git diff -U0 -- app/guide \
  | rg '^\+.*(re\.compile|re\.search|re\.match|关键词|同义词)'
```

Expected: 没有新增按句子决定 action 的正则、关键词或 product ID 特判。

## 4. Task 2：先验证核心混合链路

**Files:**

```text
Read/modify only if a shared-layer failing test proves it:
  app/guide/intent/unified_turn_router.py
  app/guide/intent/transition_planning.py
  app/guide/application/text_recommendation_flow.py
  app/guide/application/unified_guide_flow.py

Test:
  tests/guide/intent/test_unified_turn_router.py
  tests/guide/application/test_text_recommendation_flow.py
  tests/guide/tools/test_unified_router_gate.py
```

- [ ] **Step 1: 跑关键混合链路的确定性回归**

```bash
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/guide/intent/test_unified_turn_router.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/tools/test_unified_router_gate.py -q
```

Expected: PASS；重点确认多商品 `suitability` 进入 `comparison`，而不是被 consultation 处理器继续接管。

- [ ] **Step 2: 固化人工体验链**

真实体验链固定为：

```text
油敏肌，夏天通勤想找修护精华，预算300内，先推荐两款。
先不继续选产品。我下午鼻子出油，洗脸后两颊发紧，帮我判断我现在的肤质和状态。
现在再回到刚才的两款精华，按我这个状态，哪款更适合？
```

第三轮必须满足：

```text
processor family = comparison
product IDs = 第一轮推荐批次的两款
public card = comparison card
不继续追问泛红/刺痛等问诊问题
```

- [ ] **Step 3: 用第二种说法验证同一父概念**

追加同义但不同句式：

```text
回到前面那两支，结合我刚才说的油和紧绷，帮我做二选一。
```

期望与上一句进入同一公共处理器族和商品绑定；以下反例不能误进比较：

```text
我现在鼻子还是很油，两颊也紧绷，你先继续帮我判断肤质。
```

- [ ] **Step 4: 失败时只修共享层**

发现失败时，必须记录：

```text
最早错误层
typed meaning
对象基数
current_batch/current_item 绑定
实际处理器
```

禁止把失败原句、同义词或商品 ID 写入生产分支。修复前先补 failing test，再跑 provider-parser 隔离和零 API 回放。

## 5. Task 3：只发布混合链路代码到 GitHub

**Files to stage:**

```text
app/guide/adapters/llm/turn_meaning_prompt.py
app/guide/application/text_recommendation_flow.py
app/guide/application/unified_guide_flow.py
app/guide/intent/transition_planning.py
app/guide/intent/unified_turn_router.py
app/guide/understanding/context_resolver.py
app/guide/understanding/semantic_contracts.py
app/guide/understanding/semantic_route_contracts.py
tests/guide/adapters/test_turn_meaning_prompt.py
tests/guide/application/test_query_context.py
tests/guide/application/test_text_recommendation_flow.py
tests/guide/intent/test_unified_turn_router.py
tests/guide/tools/test_intent_model_ab.py
tests/guide/tools/test_run_real_continuous_conversation_gate.py
tests/guide/tools/test_unified_router_gate.py
tests/guide/understanding/test_context_resolver.py
tests/guide/understanding/test_semantic_route_contracts.py
tools/guide_gates/intent_model_ab.py
tools/guide_gates/production_routing_gate.py
tools/guide_gates/real_ab_evidence.py
tools/guide_gates/run_real_continuous_conversation_gate.py
tools/guide_gates/run_real_intent_ab.py
tools/guide_gates/run_real_unified_router_gate.py
tools/guide_gates/unified_router_gate.py
docs/superpowers/plans/2026-08-19-smzdm-data-and-transition-matrix.md
```

**Files explicitly excluded from this release:**

```text
app/static/images/products/*
data/canonical/seed_product_images_v1.*
data/guide_image_index/*
data/guide_merchant_claims/smzdm_crawl_v1/*
docs/audits/*
.dbg/*
.tmp-*
```

- [ ] **Step 1: 运行发布前 focused gate**

```bash
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/guide/adapters/test_turn_meaning_prompt.py \
  tests/guide/application/test_query_context.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/intent/test_unified_turn_router.py \
  tests/guide/tools/test_unified_router_gate.py \
  tests/guide/understanding/test_context_resolver.py \
  tests/guide/understanding/test_semantic_route_contracts.py -q
```

Expected: PASS；所有严重计数为零。

- [ ] **Step 2: 检查暂存边界**

```bash
git add <上方 allowlist 中的文件>
git diff --cached --name-only
git diff --cached -U0 -- app/guide \
  | rg '^\+.*(re\.compile|re\.search|re\.match|关键词|同义词)'
```

Expected: 暂存区只有混合链路代码、测试和计划；没有图片、抓取、临时日志或按句子补丁。

- [ ] **Step 3: 创建体验发布提交**

```bash
git commit -m "fix(guide): stabilize mixed conversation routing"
```

提交说明必须明确：

```text
typed TurnMeaning v30 保持冻结
多商品 suitability 按对象基数进入 comparison
问诊回切不再劫持已绑定商品批次
图片和 SMZDM 数字资产不包含在本提交
```

- [ ] **Step 4: 推送独立体验分支并确认远端**

```bash
git push -u origin mixed-chain-experience-20260819
gh repo view --json nameWithOwner,defaultBranchRef
git ls-remote --heads origin mixed-chain-experience-20260819
```

Expected: GitHub 上存在最新 `mixed-chain-experience-20260819` 分支提交；小伙伴可从该分支体验混合链路。不得对已有的 `rebuild` 分支执行 force push。

## 6. Task 4：固化 SMZDM 原始抓取与人工审核候选

**Files:**

```text
Create:
  tools/guide_data/crawl_smzdm_product_pages.py
  tools/guide_data/build_smzdm_review_candidates.py
  data/guide_merchant_claims/smzdm_crawl_v1/raw_pages.jsonl
  data/guide_merchant_claims/smzdm_crawl_v1/review_candidates.jsonl
  data/guide_merchant_claims/smzdm_crawl_v1/manifest.json
  tests/guide/data/test_smzdm_assets.py
```

- [ ] **Step 1: 定义原始抓取行**

每条原始页面必须包含：

```json
{
  "canonical_product_id": 33,
  "page_url": "https://www.smzdm.com/p/180595258/",
  "captured_at": "2026-08-19T00:00:00Z",
  "page_title": "页面 title",
  "product_title": "页面商品标题",
  "page_specification": "100ml",
  "main_image_url": "https://qny.smzdm.com/...",
  "main_image_sha256": "64位 sha256",
  "raw_product_introduction": "商品介绍正文",
  "excluded_sections": ["Powered by ZDM-AIGC Engine v0.3", "优势", "建议"],
  "raw_page_text_sha256": "64位 sha256"
}
```

价格只作为时效抓取字段保存：

```json
{
  "observed_price": 0,
  "price_observed_at": "2026-08-19T00:00:00Z",
  "price_role": "promotion_observation"
}
```

不得用 SMZDM 促销价覆盖 Canonical 长期参考价。

- [ ] **Step 2: 定义审核候选行**

```json
{
  "candidate_id": "sha256(raw_page_url + canonical_product_id)",
  "canonical_product_id": 33,
  "category": "护肤",
  "source_url": "https://www.smzdm.com/p/180595258/",
  "sku_match": {
    "status": "approved",
    "evidence": ["页面标题包含第七代小棕瓶", "主图 alt 包含 100ml"]
  },
  "candidate_fields": {
    "net_content": "100ml",
    "efficacy_positioning": ["抗衰老"],
    "suitable_people": ["所有肤质"],
    "hero_ingredients": ["三肽-32"],
    "brand_technology": ["Chronolux Power Signal 时钟基因信源科技"]
  },
  "image_candidate": {
    "source_url": "https://qny.smzdm.com/...",
    "source_sha256": "64位 sha256",
    "background_assessment": "clean_white",
    "sku_match_assessment": "same_product_100ml",
    "review_status": "approved"
  },
  "reviewed_by": "human",
  "reviewed_at": "2026-08-19T00:00:00Z",
  "review_reason": "页面规格和主图 alt 均明确为第七代 100ml，主体清楚，适合商品卡片"
}
```

- [ ] **Step 3: 写候选验证测试**

测试必须拒绝：

```text
缺 page_url 或图片 URL
canonical_product_id 不存在
SKU 证据为空但 review_status=approved
规格冲突
AIGC 优势/建议文本进入 candidate_fields
只有促销价、没有 observed_at
image_candidate.review_status=approved 但没有 image hash
```

- [ ] **Step 4: 运行小棕瓶 smoke**

```bash
PYTHONPATH=. .venv/bin/python tools/guide_data/crawl_smzdm_product_pages.py \
  --url https://www.smzdm.com/p/180595258/ \
  --product-id 33 \
  --output-dir data/guide_merchant_claims/smzdm_crawl_v1

PYTHONPATH=. .venv/bin/python tools/guide_data/build_smzdm_review_candidates.py \
  --raw-pages data/guide_merchant_claims/smzdm_crawl_v1/raw_pages.jsonl \
  --output data/guide_merchant_claims/smzdm_crawl_v1/review_candidates.jsonl
```

Expected: product 33 候选为 `approved`，规格为 `100ml`，AIGC 段落被排除。

## 7. Task 5：正式写入已批准图片并保持索引一致

**Files:**

```text
Modify:
  app/static/images/products/jd_v3_100022610146.png
  data/canonical/seed_product_images_v1.jsonl
  data/canonical/seed_product_images_v1_manifest.json
  data/guide_image_index/openclip_vit_b32_laion2b_s34b_b79k_v1/*

Create:
  data/guide_merchant_claims/smzdm_crawl_v1/source_images/33/*
  docs/audits/slice2.0/task11_smzdm_33_rebuild_report.json
```

- [ ] **Step 1: 保存原始下载图**

保留 SMZDM 原始 JPEG，不覆盖原始抓取证据：

```bash
mkdir -p data/guide_merchant_claims/smzdm_crawl_v1/source_images/33
curl -L --fail --silent --show-error \
  'https://qny.smzdm.com/202101/27/601116308b05b4959.jpg_d250.jpg' \
  -o data/guide_merchant_claims/smzdm_crawl_v1/source_images/33/smzdm_180595258_main_250.jpg
```

- [ ] **Step 2: 生成正式卡片图**

将已批准候选转换为 PNG，保持原有 product 33 资源路径，避免运行时引用断裂：

```bash
sips -s format png \
  data/guide_merchant_claims/smzdm_crawl_v1/source_images/33/smzdm_180595258_main_250.jpg \
  --out app/static/images/products/jd_v3_100022610146.png
```

- [ ] **Step 3: 重建 Canonical 图片 manifest**

```bash
.venv/bin/python scripts/build_seed_image_manifest.py \
  --root . \
  --seed-dump data/seed_dump.sql \
  --output-dir data/canonical
```

Expected: product 33 的 `bytes`、`source_image_sha256`、`products_sha256`、`source_images_sha256` 和 `manifest_sha256` 一致。

- [ ] **Step 4: 用项目专用环境重建图片索引**

```bash
weight=$(find /Users/bytedance/.cache/huggingface/hub \
  -name open_clip_model.safetensors | head -1)

PYTHONPATH=. HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python tools/guide_gates/build_guide_image_index.py \
  --repo-root . \
  --weight-path "$weight" \
  --output-dir .tmp-image-index-primary \
  --repeat-output-dir .tmp-image-index-repeat \
  --report-path docs/audits/slice2.0/task11_smzdm_33_rebuild_report.json \
  --device mps \
  --batch-size 16
```

Expected:

```text
source_count=103
original_top1_hits=103
transformed_top3_hits=103
reproducible=true
acceptance_passed=true
```

- [ ] **Step 5: 运行图片资产完整性测试**

```bash
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/guide/data/test_frontend_product_image_inventory.py \
  tests/guide/adapters/catalog/test_seed_product_assets.py \
  tests/guide/adapters/image/test_image_index_source_preflight.py -q
```

## 8. Task 6：生成 6 状态切换矩阵

**Files:**

```text
Create:
  tools/guide_gates/build_transition_matrix.py
  tests/fixtures/guide/transition_matrix/states.json
  tests/fixtures/guide/transition_matrix/pairwise_edges.jsonl
  tests/fixtures/guide/transition_matrix/triple_paths.jsonl
  tests/fixtures/guide/transition_matrix/long_walks.jsonl
  tests/fixtures/guide/transition_matrix/manifest.json
  tests/fixtures/guide/transition_matrix/truth.json
```

六个状态固定为：

```text
recommendation_batch
single_product_focus
comparison_batch
consultation
general_knowledge
confirmed_image_product
```

- [ ] **Step 1: 生成 36 条有向边**

```python
states = (
    "recommendation_batch",
    "single_product_focus",
    "comparison_batch",
    "consultation",
    "general_knowledge",
    "confirmed_image_product",
)
edges = [
    {"edge_id": f"{source}->{target}", "source": source, "target": target}
    for source in states
    for target in states
]
assert len(edges) == 36
```

每条边必须带：

```text
起始 snapshot
typed meaning 输入
期待 processor family
期待商品/图片绑定
是否允许产生安全升级
```

- [ ] **Step 2: 生成 216 条三段路径**

```python
paths = [
    (first, second, third)
    for first in states
    for second in states
    for third in states
]
assert len(paths) == 216
```

三段路径的判定不是内部 enum 严格相等，而是比较每一段的公共结果和最终 snapshot。

- [ ] **Step 3: 生成长混合链**

至少包含：

```text
1 -> 2 -> 3 -> 4
3 -> 2 -> 4 -> 1
1 -> 2 -> 3 -> 4 -> 4 -> 3 -> 2 -> 1
1 -> 2 -> 3 -> 4 -> 1
3 -> 1 -> 2 -> 4
2 -> 4 -> 3 -> 2 -> 1
```

再补足到 8-12 条，覆盖正序、逆序、重复进入、问诊回切、图片确认后回到商品比较。

## 9. Task 7：实现矩阵 outcome scorer

**Files:**

```text
Create:
  tools/guide_gates/run_transition_matrix.py
  tests/guide/tools/test_transition_matrix.py
  docs/audits/continuous-conversation/transition-matrix/*
```

- [ ] **Step 1: 固化 outcome contract**

```python
class TransitionOutcome:
    processor_family: str
    product_ids: tuple[int, ...]
    image_ordinals: tuple[int, ...]
    card_type: str | None
    card_product_ids: tuple[int, ...]
    active_state: str | None
    safety_state: str | None
    expected_state_change: bool
```

- [ ] **Step 2: 实现普通路径比较**

同一目标状态由两条不同历史路径到达时，比较：

```python
assert actual.processor_family == expected.processor_family
assert actual.product_ids == expected.product_ids
assert actual.card_type == expected.card_type
assert actual.card_product_ids == expected.card_product_ids
assert actual.active_state == expected.active_state
```

允许 `expected_state_change=True` 的安全升级、新图片、新条件和显式重置必须单独记录，不得用普通路径断言覆盖。

- [ ] **Step 3: 加入关键回归断言**

必须明确覆盖：

```text
推荐 -> 问诊 -> 回到刚才两款商品 -> 哪款更适合
```

期望：

```text
第三轮 processor_family=comparison
product_ids=原推荐批次的两款
card_type=comparison
card_product_ids=两款商品
不会继续输出问诊澄清卡片
```

- [ ] **Step 4: 运行 36/216 矩阵**

```bash
PYTHONPATH=. .venv/bin/python tools/guide_gates/run_transition_matrix.py \
  --fixture-root tests/fixtures/guide/transition_matrix \
  --output-dir docs/audits/continuous-conversation/transition-matrix \
  --outcome-scoring
```

Expected:

```text
pairwise_edges=36
triple_paths=216
ordinary_path_pollution=0
serious_failures=0
allowed_safety_escalations=only_expected
```

## 10. Task 8：真实模型抽样与责任层定位

- [ ] **Step 1: 从 36 条边抽取 30-50 条真实语义翻译**

每条记录保存：

```text
raw message
typed TurnMeaning
source snapshot
expected parent concept
actual outcome
provider/model metadata
```

- [ ] **Step 2: 分类第一错误层**

只允许使用以下责任层：

```text
model_translation
semantic_admission
identity_binding
route_selection
state_transition
decision_execution
data_coverage
public_presentation
browser_renderer
```

- [ ] **Step 3: 发现失败时先写共享层 failing test**

不得先改 Prompt。必须先证明：

```text
至少两个不同说法共享同一父概念
一个反例不应进入该父概念
provider path 不调用 legacy parser
零 API 回放与真实模型结果一致
```

只有明确证明 `model_translation` 错误时，才允许修改 Prompt v30，并且不能把失败原句写进 Prompt。

## 11. Task 9：最终真实浏览器验收

**Files:**

```text
Create:
  tools/guide_gates/run_transition_browser_audit.py
  tests/guide/tools/test_transition_browser_audit.py
  docs/audits/continuous-conversation/browser-transition-matrix/*
```

- [ ] **Step 1: 启动干净服务**

启动前确认：

```text
没有旧进程占用目标端口
真实 DeepSeek key 已注入
copywriter provider 没有被 fallback 替代
服务使用最新 Canonical 图片 manifest 和图片索引
```

- [ ] **Step 2: 浏览器复核 8-12 条长链**

至少真实走：

```text
推荐 -> 问诊 -> 回到两款比较
推荐 -> 单品 -> 知识 -> 回推荐
对比 -> 问诊 -> 回对比
图片确认 -> 单品事实 -> 适配比较
正序与逆序长链
重复进入同一状态
```

- [ ] **Step 3: 检查真实展示**

每条链检查：

```text
图片实际加载完成
商品图与商品身份一致
卡片不重叠、不串商品
规格只出现在价格行
润写包含已批准的成分/技术/肤感素材
没有证据块缺失导致的基础事实拒答
没有秒出本地兜底冒充真实润写
```

- [ ] **Step 4: 用户最终手测**

交给用户的只包含：

```text
真实服务 URL
建议测试链
已知允许的安全升级说明
```

用户确认浏览器展示、润写和混合链路均无问题后，才进入关闭流程。

## 12. Task 10：最终关闭

- [ ] **Step 1: 重新运行必要回归**

```bash
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/guide/intent \
  tests/guide/application \
  tests/guide/data \
  tests/guide/retrieval \
  tests/guide/tools -q
```

- [ ] **Step 2: 检查 git diff**

确认：

```text
没有临时 debug 请求
没有按句子打补丁
没有 product ID 特判
没有 AIGC 内容进入正式事实
所有图片来源和 hash 可追溯
```

- [ ] **Step 3: 生成 closure report**

报告必须包含：

```text
SMZDM 原始抓取数量、人工批准数量、隔离数量
图片替换清单及哈希
36/216/长链覆盖结果
安全升级例外统计
真实模型和浏览器证据
剩余已知风险
```

- [ ] **Step 4: 用户确认后再提交后续资产**

混合链路体验代码已经在 Task 3 单独提交并推送；本步骤只负责用户确认后的图片、SMZDM 数据和矩阵后续提交，不把测试通过自动等同于最终上线。

## 13. 计划自检

```text
需求覆盖：
  混合链路回归                 -> Task 2
  GitHub 体验发布              -> Task 3
  SMZDM 抓取与人工审核         -> Task 4
  product 33 图片替换          -> Task 5
  图片索引一致性               -> Task 5
  36 条边                      -> Task 6
  216 条路径                   -> Task 6
  允许的安全升级例外           -> Task 1、Task 7
  路径无关性 outcome scoring   -> Task 7
  真实模型抽样                 -> Task 8
  浏览器长链                   -> Task 9
  最终回归与关闭               -> Task 10
```

本计划明确禁止：

```text
继续堆随机盲卷代替状态覆盖
用失败句子、关键词或商品 ID 做补丁
把内部枚举差异当成用户可见失败
把安全升级误报为路径污染
未经人工审核直接把抓取内容接入正式资产
```
