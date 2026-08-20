# 15 商品数据库优先恢复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 复用旧数据库中的商品字段，用保存的 HTML/包装证据核对关键字段，完成 15 个试点的 known/pending/quarantine/unknown 闭环并恢复三份历史 HTML。

**Architecture:** `seed_dump.sql` 只读解析为数据库候选；Downloads 只读盘点后由平台解析器提取 item/SKU/官方参数/评论证据；两路按 product/item/SKU/source SHA 合并。自动化只生成候选和审核矩阵，不自动批准。

**Tech Stack:** Python 3.11、PostgreSQL COPY text parser、HTMLParser、JSON、Pydantic、SHA-256、pytest

---

## 文件边界

本计划 writer 独占：

- `tools/guide_data/**`
- `tests/guide/tools/**`
- `tests/fixtures/guide/data_recovery/**`
- `docs/audits/guide-closure/data/**`

不修改 Canonical、生产 category facts、已批准评论、`app/guide_runtime/composition.py`、
tasks/checklist/progress。原始 HTML、原始 SQL 派生候选和正文只放 `/private/tmp`，不提交。

固定目标：

```python
TARGET_PRODUCT_IDS = (
    38, 42, 49, 53, 55, 57, 69, 79,
    80, 86, 91, 103, 114, 120, 121,
)
```

### Task 1: 重新盘点 Downloads 并修正三份 HTML 状态

**Files:**
- Modify: `tests/guide/tools/test_inventory_local_sources.py`
- Modify: `tests/guide/tools/test_find_locked_review_sources.py`
- Generate locally: `/private/tmp/xiaoro-guide-weekend/inventory.jsonl`
- Generate locally: `/private/tmp/xiaoro-guide-weekend/review_source_recovery.json`

- [ ] **Step 1: 写多根目录和真实锁定 SHA RED**

在 `test_find_locked_review_sources.py` 增加一个三文件 fixture：

```python
LOCKED = (
    "b31206098d6839257e5dd29c1fae71495b067029568763d9a726b16fc47fd3e4",
    "55996a2a8207e65eb434fa376d61dc0f34d5621f51f9c3754e2369021d9a7f44",
    "56719aa64a4222a961b2ea118cf51415f25c4f88560e5de83172adc8e9c13783",
)


def test_all_locked_hashes_can_be_found_across_approved_roots(
    tmp_path: Path,
) -> None:
    inventory = tmp_path / "inventory.jsonl"
    inventory.write_text(
        "".join(
            json.dumps(
                {
                    "content_type": "html",
                    "relative_name": f"source-{index}.html",
                    "sha256": digest,
                    "size_bytes": 1,
                    "source_root_id": f"{index + 1:064x}",
                },
                sort_keys=True,
            )
            + "\n"
            for index, digest in enumerate(LOCKED)
        ),
        encoding="utf-8",
    )
    result = find_locked_sources(
        inventory,
        locked_hashes=LOCKED,
    )
    assert result.found_count == 3
    assert result.missing_count == 0
```

- [ ] **Step 2: 运行 focused baseline**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/tools/test_inventory_local_sources.py \
  tests/guide/tools/test_find_locked_review_sources.py
```

Expected: PASS；这一步证明工具本身可用，旧失败来自来源根选择。

- [ ] **Step 3: 运行受信只读 inventory**

```bash
mkdir -p /private/tmp/xiaoro-guide-weekend
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_data/inventory_local_sources.py \
  --root /Users/bytedance/Downloads \
  --root /Users/bytedance/Desktop/xiaoro-fresh/data \
  --continue-on-rejected-entry \
  --output /private/tmp/xiaoro-guide-weekend/inventory.jsonl
```

CLI 已支持重复 `--root`。不要改成隐式扫描 `$HOME`；批准根必须在命令中逐项出现。
Downloads 内若有 symlink 或特殊文件，`--continue-on-rejected-entry` 只跳过该条并将整体
标为 incomplete，普通 HTML 仍需进入 inventory。


- [ ] **Step 4: 查找锁定来源**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_data/find_locked_review_sources.py \
  --inventory /private/tmp/xiaoro-guide-weekend/inventory.jsonl \
  --approved-manifest \
    data/guide_review_sources/approved_tmall_feed_reviews_v1_manifest.json \
  --output \
    /private/tmp/xiaoro-guide-weekend/review_source_recovery.json
jq '{found_count,missing_count,duplicate_count}' \
  /private/tmp/xiaoro-guide-weekend/review_source_recovery.json
```

Expected:

```json
{"found_count":3,"missing_count":0,"duplicate_count":0}
```

- [ ] **Step 5: 复核原文件未变**

```bash
shasum -a 256 \
  '/Users/bytedance/Downloads/夸迪蓝金能量炮CT50悬油次抛2.0精华液玻尿酸礼盒-tmall.com天猫.html' \
  '/Users/bytedance/Downloads/玉泽皮肤屏障修护面霜保湿霜干敏肌保湿改善泛红补水缓解干燥舒缓-tmall.com天猫.html' \
  '/Users/bytedance/Downloads/薇诺娜清透防晒乳水感防晒套装清爽不粘腻15g 敏感肌轻薄防晒派-tmall.com天猫.html'
```

Expected: 三个 SHA 与设计文档一致。

- [ ] **Step 6: Commit 工具兼容改动**

只有 CLI 发生改动时提交：

```bash
git add \
  tools/guide_data/inventory_local_sources.py \
  tests/guide/tools/test_inventory_local_sources.py \
  tests/guide/tools/test_find_locked_review_sources.py
git commit -m "fix(data): include approved local source roots"
```

### Task 2: 安全读取旧数据库产品行

**Files:**
- Create: `tools/guide_data/read_seed_dump_products.py`
- Create: `tests/guide/tools/test_read_seed_dump_products.py`
- Create: `tests/fixtures/guide/data_recovery/products_copy.sql`

- [ ] **Step 1: 写 COPY parser RED**

fixture 使用完整表头和两行：

```sql
COPY public.products (id, name, category, brand, price, original_price, description, specifications, image_url, detail_url, platform, stock, sales_count, rating, review_count, created_at, updated_at, specs, tags, skincare_info) FROM stdin;
42	示例\t商品	精华	示例	100.00	\N	描述\n第二行	{"skincare_info":{"qa_facts":[]}}	/static/a.png	https://detail.tmall.com/item.htm?id=42	tmall	1	0	\N	0	2026-01-01	2026-01-01	\N	{精华}	{"texture":"水液","skin_types":["干性"]}
\.
```

测试：

```python
def test_reads_only_products_copy_and_decodes_copy_escapes() -> None:
    rows = read_seed_dump_products(
        FIXTURE,
        product_ids=(42,),
    )
    assert len(rows) == 1
    assert rows[0].product_id == 42
    assert rows[0].name == "示例\t商品"
    assert rows[0].description == "描述\n第二行"
    assert rows[0].detail_url.endswith("id=42")
    assert rows[0].skincare_info["texture"] == "水液"
```

再覆盖：

```python
def test_rejects_duplicate_missing_or_non_product_rows() -> None:
    with pytest.raises(SeedDumpError):
        read_seed_dump_products(FIXTURE, product_ids=(42, 42))
    with pytest.raises(SeedDumpError):
        read_seed_dump_products(FIXTURE, product_ids=(999,))
```

- [ ] **Step 2: 运行 RED**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/tools/test_read_seed_dump_products.py
```

Expected: module missing.

- [ ] **Step 3: 实现固定 products COPY reader**

核心合同：

```python
@dataclass(frozen=True, slots=True)
class SeedProductRow:
    product_id: int
    name: str
    category: str
    brand: str
    price: Decimal
    description: str
    specifications: dict[str, object]
    detail_url: str | None
    platform: str
    specs: dict[str, object] | None
    skincare_info: dict[str, object]
    source_sha256: str
    source_line: int
```

固定列：

```python
PRODUCT_COLUMNS = (
    "id", "name", "category", "brand", "price", "original_price",
    "description", "specifications", "image_url", "detail_url",
    "platform", "stock", "sales_count", "rating", "review_count",
    "created_at", "updated_at", "specs", "tags", "skincare_info",
)
```

实现要求：

```python
def read_seed_dump_products(
    path: str | Path,
    *,
    product_ids: Sequence[int],
) -> tuple[SeedProductRow, ...]:
    content = Path(path).read_bytes()
    source_sha256 = hashlib.sha256(content).hexdigest()
    text = content.decode("utf-8")
    # 只接受精确 COPY public.products (...) FROM stdin; 区段。
    # 以未转义的 TAB 切列；逐列解码 PostgreSQL COPY text 反斜杠转义。
    # JSON 列必须 json.loads 为 object；\N 只允许出现在 nullable 列。
    # 结果必须恰好覆盖 product_ids，按 product_id 排序。
```

COPY 解码只允许以下转义：

```python
_COPY_ESCAPES = {
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\\": "\\",
}
```

遇到未知转义、列数不等于 20、重复 ID、非有限价格、非 object JSON 时 fail closed。

- [ ] **Step 4: 运行真实 15 商品只读检查**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python - <<'PY'
from tools.guide_data.read_seed_dump_products import read_seed_dump_products

ids = (38,42,49,53,55,57,69,79,80,86,91,103,114,120,121)
rows = read_seed_dump_products("data/seed_dump.sql", product_ids=ids)
print(len(rows))
print([row.product_id for row in rows])
PY
```

Expected:

```text
15
[38, 42, 49, 53, 55, 57, 69, 79, 80, 86, 91, 103, 114, 120, 121]
```

- [ ] **Step 5: GREEN 和 Commit**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/tools/test_read_seed_dump_products.py
git add \
  tools/guide_data/read_seed_dump_products.py \
  tests/guide/tools/test_read_seed_dump_products.py \
  tests/fixtures/guide/data_recovery/products_copy.sql
git commit -m "feat(data): read trusted product rows from seed dump"
```

### Task 3: 从数据库生成分层字段候选

**Files:**
- Create: `tools/guide_data/build_seed_database_candidates.py`
- Create: `tests/guide/tools/test_build_seed_database_candidates.py`
- Test: `tests/fixtures/guide/data_recovery/products_copy.sql`

- [ ] **Step 1: 写来源分层 RED**

测试必须覆盖：

```python
def test_structured_database_fields_become_typed_candidates() -> None:
    result = build_seed_database_candidates(
        seed_dump_path=FIXTURE,
        canonical_products_path=CANONICAL,
        product_ids=(42,),
        output_path=tmp_path / "pending.jsonl",
        quarantine_path=tmp_path / "quarantine.jsonl",
    )
    pending = rows(result.pending)
    assert {row["field_key"] for row in pending} == {
        "texture",
        "suitable_skin",
    }
    assert all(row["source_sha256"] == seed_sha for row in pending)


def test_marketing_qa_unbound_and_wrong_profile_are_quarantined() -> None:
    quarantine = rows(result.quarantine)
    assert {
        reason
        for row in quarantine
        for reason in row["quarantine_reasons"]
    } >= {
        "unbound_database_field",
        "consumer_qa",
        "field_not_applicable",
    }
```

- [ ] **Step 2: 运行 RED**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/tools/test_build_seed_database_candidates.py
```

- [ ] **Step 3: 实现闭合字段映射**

在新工具定义：

```python
DATABASE_FIELD_MAP = {
    "texture": ("texture", "string_list"),
    "skin_types": ("suitable_skin", "string_list"),
    "suitable_skin_types": ("suitable_skin", "string_list"),
    "spf": ("spf_pa", "string"),
    "usage_note": ("usage", "string_list"),
    "free_of": ("verified_absences", "string_list"),
    "shade_note": ("shade", "string_list"),
    "clinical": ("clinical_evidence", "string_list"),
}

IGNORED_DERIVED_FIELDS = frozenset({
    "concerns",
    "pitfalls",
    "product_note",
    "positioning",
})
```

`key_ingredients` 单独展开为 `ingredients_present`。来源 tag 映射：

```python
SOURCE_TAG_CLASSES = {
    "official_specs": "structured_official",
    "structured_spec_fallback": "structured_official",
    "detail_ocr_ingredient_list": "ocr_ingredient_list",
    "detail_ocr_marketing": "ocr_packaging",
    "ocr_html_enrich": "ocr_packaging",
    "brand_marketing": "official_description",
}
```

候选字段：

```python
{
    "candidate_id": str,
    "product_id": int,
    "category_profile": str,
    "field_key": str,
    "normalized_value": object,       # pending only
    "value_sha256": str,
    "source_class": str,
    "source_locator": (
        "urn:xiaoro:seed-dump:"
        f"sha256:{source_sha}:product:{product_id}:field:{json_path}"
    ),
    "source_sha256": str,
    "status": "pending" | "quarantine",
    "quarantine_reasons": list[str],
}
```

分类规则：

- canonical 核心字段永不生成；
- 不适用于 profile -> quarantine；
- `qa_facts`、`user_review_notes` 不生成 category fact；
- `claim_notes`、无 source tag 的任意扩展字段 -> quarantine；
- `verified_absences` 只有 `structured_official` 才 pending；
- OCR 只生成 evidence-only candidate，并标记
  `proposed_capabilities=["evidence"]`；
- 输出按 candidate ID 排序，输入守恒且字节确定。

- [ ] **Step 4: 运行真实候选构建**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_data/build_seed_database_candidates.py \
  --seed-dump data/seed_dump.sql \
  --canonical data/canonical/core_products_v1.jsonl \
  --product-id 38 --product-id 42 --product-id 49 \
  --product-id 53 --product-id 55 --product-id 57 \
  --product-id 69 --product-id 79 --product-id 80 \
  --product-id 86 --product-id 91 --product-id 103 \
  --product-id 114 --product-id 120 --product-id 121 \
  --output /private/tmp/xiaoro-guide-weekend/db-pending.jsonl \
  --quarantine /private/tmp/xiaoro-guide-weekend/db-quarantine.jsonl
```

Expected: return code 0；输出不包含绝对路径、原始评论或问答正文。

- [ ] **Step 5: GREEN 和 Commit**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/tools/test_build_seed_database_candidates.py
git add \
  tools/guide_data/build_seed_database_candidates.py \
  tests/guide/tools/test_build_seed_database_candidates.py
git commit -m "feat(data): classify trusted seed database fields"
```

### Task 4: 解析真实保存网页的官方参数和评论

**Files:**
- Create: `tools/guide_data/extract_saved_page_evidence.py`
- Create: `tests/guide/tools/test_extract_saved_page_evidence.py`
- Create: `tests/fixtures/guide/data_recovery/tmall_saved_page.html`
- Create: `tests/fixtures/guide/data_recovery/jd_saved_page.html`
- Modify: `tools/guide_data/build_review_candidates.py:141-203, 604-621`
- Modify: `tools/guide_data/recover_candidate_queues.py:575-700`
- Modify: `tests/guide/tools/test_build_review_candidates.py`
- Modify: `tests/guide/tools/test_recovery_is_non_promoting.py`

- [ ] **Step 1: 写真实形状 parser RED**

Tmall fixture 包含最小：

```html
<script>
!(function () {
  var b = {"loaderData":{"home":{"data":{"res":{
    "item":{"itemId":"998532090974","title":"示例精华"},
    "skuBase":{"skus":[{"skuId":"6153782938028"}]},
    "plusViewVO":{"industryParamVO":{
      "basicParamList":[
        {"propertyName":"品名","valueName":"示例精华"},
        {"propertyName":"适用肤质","valueName":"干性"},
        {"propertyName":"质地","valueName":"水液"}
      ]
    }},
    "rateVO":{"group":{"items":[
      {"feedId":"1","content":"清爽","skuInfo":"30ml"}
    ]}}
  }}}}};
  window.__ICE_APP_CONTEXT__ = b;
})();
</script>
```

测试：

```python
def test_extracts_tmall_item_sku_parameters_and_reviews() -> None:
    evidence = extract_saved_page_evidence(TMALL)
    assert evidence.platform == "tmall"
    assert evidence.item_id == "998532090974"
    assert evidence.sku_ids == ("6153782938028",)
    assert evidence.parameters["适用肤质"] == ("干性",)
    assert evidence.review_count == 1
```

JD fixture 用 `application/ld+json` 加参数表，测试 item/SKU、标题、参数；不得从推荐商品
区或用户评论生成官方参数。

- [ ] **Step 2: 运行 RED**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/tools/test_extract_saved_page_evidence.py
```

- [ ] **Step 3: 实现平台解析器**

公共输出：

```python
@dataclass(frozen=True, slots=True)
class SavedReview:
    feed_id: str
    sku_id: str
    content: str


@dataclass(frozen=True, slots=True)
class SavedPageEvidence:
    platform: Literal["tmall", "taobao", "jd"]
    item_id: str
    sku_ids: tuple[str, ...]
    title: str
    parameters: dict[str, tuple[str, ...]]
    reviews: tuple[SavedReview, ...]
    source_sha256: str
```

Tmall：

- HTMLParser 收集 script text；
- 找到 `var b = ` 后使用 `json.JSONDecoder().raw_decode()`，不使用正则匹配嵌套 JSON；
- 只读取 `loaderData.home.data.res`；
- item ID 只读 `item.itemId`；
- SKU 只读 `skuBase.skus[].skuId`；
- 参数只读 `industryParamVO.basicParamList/enhanceParamList`；
- 评论只读 `rateVO.group.items`。

JD：

- 优先读取 `application/ld+json` 的 product SKU/name；
- 参数只读取明确的“参数信息/规格参数”键值节点；
- 无法绑定 item ID 时 fail closed，不从文件名猜。

两者都必须验证：

- source 是普通文件、非 symlink；
- UTF-8 可解析；
- item/SKU 只含数字；
- parameters 不包含用户评价、问答、推荐商品；
- 输出只含 normalized values 和 source SHA。

- [ ] **Step 4: 让评论 builder 支持真实 Tmall JSON**

先给 `build_review_candidates()` 增加显式 `source_root`：

```python
def build_review_candidates(
    *,
    source_manifest_path: str | Path,
    source_root: str | Path,
    output_root: str | Path,
) -> ReviewCandidateBuildResult:
    sources = _load_sources(
        Path(source_manifest_path),
        source_root=Path(source_root),
    )
```

`_load_sources()` 使用 `read_relative_regular_bytes(source_root, source_path)`；manifest
中的 path 必须相对该批准 root。CLI 增加必填 `--source-root`。输出仍必须位于 root
之外。这样不复制 268 MB 原始网页，也不允许 `..` 或绝对路径逃逸。
更新现有 fixture helper，显式传 `source_root=manifest_path.parent`，不提供兼容默认值。
`recover_candidate_queues()` 同步增加必填 `review_source_root`；只有传
`review_source_manifest_path` 时使用该 root。调用 review builder 时必须显式传：

```python
build_review_candidates(
    source_manifest_path=review_source_manifest_path,
    source_root=review_source_root,
    output_root=queue_paths.review_pending.parent,
)
```

CLI 和 `test_recovery_is_non_promoting.py` 同步更新，不允许默认回退到 manifest parent。

`_parse_html()` 先运行现有 marker parser。若 marker 记录为空，则调用：

```python
evidence = extract_saved_page_evidence_bytes(payload)
return tuple(
    _Extracted(
        attributes={
            "data-item-id": evidence.item_id,
            "data-sku-id": review.sku_id,
            "data-feed-id": review.feed_id,
        },
        content=review.content,
        page_ordinal=index,
    )
    for index, review in enumerate(evidence.reviews, start=1)
)
```

真实三页当前各暴露 2 条评论，因此本轮预期 `extracted_count=6`。不要伪造
`336/111`；由于未重现历史中间计数，provenance 保持 `source_incomplete`，但
locked source 状态必须是 `found=3`。

- [ ] **Step 5: 重放三份 HTML**

生成 `/private/tmp/xiaoro-guide-weekend/review-source-manifest.json`，内容使用：

```json
{
  "schema_version": "review-candidate-sources-v1",
  "sources": [
    {
      "product_id": 42,
      "item_id": "998532090974",
      "sku_id": "6153782938028",
      "path": "夸迪蓝金能量炮CT50悬油次抛2.0精华液玻尿酸礼盒-tmall.com天猫.html",
      "sha256": "b31206098d6839257e5dd29c1fae71495b067029568763d9a726b16fc47fd3e4",
      "collected_at": "2026-07-01T14:18:25+08:00"
    }
  ]
}
```

另外两条按批准 manifest 填写；path 必须由 inventory match 还原到受信 root，
不能手工按文件名猜。`source_root` 固定为本轮用户批准的
`/Users/bytedance/Downloads`。

Run:

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_data/build_review_candidates.py \
  --source-manifest \
    /private/tmp/xiaoro-guide-weekend/review-source-manifest.json \
  --source-root /Users/bytedance/Downloads \
  --output-root /private/tmp/xiaoro-guide-weekend/reviews
```

Expected:

- extracted = 6；
- 三个 source SHA 与批准 manifest 一致；
- 六条 normalized review content hash 与现有批准 JSONL 一致；
- 不自动 promotion。

- [ ] **Step 6: GREEN 和 Commit**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/tools/test_extract_saved_page_evidence.py \
  tests/guide/tools/test_build_review_candidates.py \
  tests/guide/tools/test_recovery_is_non_promoting.py
git add \
  tools/guide_data/extract_saved_page_evidence.py \
  tools/guide_data/build_review_candidates.py \
  tools/guide_data/recover_candidate_queues.py \
  tests/guide/tools/test_extract_saved_page_evidence.py \
  tests/guide/tools/test_build_review_candidates.py \
  tests/guide/tools/test_recovery_is_non_promoting.py \
  tests/fixtures/guide/data_recovery/tmall_saved_page.html \
  tests/fixtures/guide/data_recovery/jd_saved_page.html
git commit -m "feat(data): parse evidence from real saved product pages"
```

### Task 5: 合并数据库候选和 HTML 核验结果

**Files:**
- Create: `tools/guide_data/reconcile_pilot_candidates.py`
- Create: `tests/guide/tools/test_reconcile_pilot_candidates.py`
- Modify: `tools/guide_data/report_pilot_field_coverage.py`
- Modify: `tests/guide/tools/test_report_pilot_field_coverage.py`

- [ ] **Step 1: 写核对矩阵 RED**

测试输入同一字段三种情况：

```python
def test_matching_database_and_html_becomes_pending() -> None:
    row = reconcile(database_value="SPF50+", html_value="SPF50+")
    assert row["status"] == "pending"
    assert row["evidence_sources"] == ["database", "html"]


def test_conflict_is_quarantined_and_missing_stays_unknown() -> None:
    conflict = reconcile(database_value="SPF48", html_value="SPF50+")
    missing = reconcile(database_value=None, html_value=None)
    assert conflict["status"] == "quarantine"
    assert conflict["quarantine_reasons"] == ["source_conflict"]
    assert missing["status"] == "unknown"
```

- [ ] **Step 2: 实现三态合并**

输出每个适用字段：

```python
{
    "product_id": int,
    "category_profile": str,
    "field_key": str,
    "status": "known" | "pending" | "quarantine" | "unknown",
    "candidate_id": str | None,
    "source_classes": list[str],
    "source_sha256": list[str],
    "normalized_value": object | None,
    "value_sha256": str | None,
    "quarantine_reasons": list[str],
}
```

规则：

- Canonical known -> `known`，不允许覆盖；
- DB pending + HTML 同值 -> `pending`；
- DB OCR evidence + HTML 官方同值 -> `pending`，source class 以 HTML 官方来源为准；
- DB 和 HTML 冲突 -> `quarantine`；
- 只有 DB 结构化官方来源 -> `pending`；
- 只有 OCR -> `pending` 但 capabilities 仅 `evidence`；
- 评论只允许 experiential field；
- 无来源 -> `unknown`；
- 不适用字段不输出。

工具必须同时输出三个文件：

- `pilot-status.jsonl`：包含 known/pending/quarantine/unknown 全状态，用于报告；
- `category-pending.jsonl`：只含兼容 `_PendingCandidate` 的可审核候选；
- `category-quarantine.jsonl`：只含兼容 `_QuarantineCandidate` 的隔离候选。

pending/quarantine 字段集合必须直接用现有 promotion 测试中的闭合 schema 校验，不能
另造一个 promotion 不认识的格式。

- [ ] **Step 3: 扩展 coverage 工具**

`build_pilot_field_coverage()` 增加可选：

```python
reconciled_candidates_path: str | Path | None = None
```

有候选时覆盖字段状态；报告只提交状态、candidate ID、value SHA、source SHA，不提交
原始 HTML 或长正文。

- [ ] **Step 4: 运行 15 商品核对**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_data/reconcile_pilot_candidates.py \
  --database-pending /private/tmp/xiaoro-guide-weekend/db-pending.jsonl \
  --database-quarantine \
    /private/tmp/xiaoro-guide-weekend/db-quarantine.jsonl \
  --inventory /private/tmp/xiaoro-guide-weekend/inventory.jsonl \
  --source-root /Users/bytedance/Downloads \
  --canonical data/canonical/core_products_v1.jsonl \
  --status-output /private/tmp/xiaoro-guide-weekend/pilot-status.jsonl \
  --pending-output /private/tmp/xiaoro-guide-weekend/category-pending.jsonl \
  --quarantine-output \
    /private/tmp/xiaoro-guide-weekend/category-quarantine.jsonl
```

没有找到对应保存页的字段保持 DB provenance 或 unknown；不得按相似商品名绑定。

- [ ] **Step 5: GREEN 和 Commit**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/tools/test_reconcile_pilot_candidates.py \
  tests/guide/tools/test_report_pilot_field_coverage.py
git add \
  tools/guide_data/reconcile_pilot_candidates.py \
  tools/guide_data/report_pilot_field_coverage.py \
  tests/guide/tools/test_reconcile_pilot_candidates.py \
  tests/guide/tools/test_report_pilot_field_coverage.py
git commit -m "feat(data): reconcile pilot database and html evidence"
```

### Task 6: 生成用户可审核矩阵并执行明确批准

**Files:**
- Create: `tools/guide_data/render_pilot_review_matrix.py`
- Create: `tools/guide_data/sign_category_fact_decisions.py`
- Create: `tests/guide/tools/test_render_pilot_review_matrix.py`
- Create: `tests/guide/tools/test_sign_category_fact_decisions.py`
- Generate: `docs/audits/guide-closure/data/pilot_review_matrix.md`
- Modify only after approval:
  `data/guide_category_facts/category_facts_v1_manifest.json`
- Generate only after approval: the content-addressed facts JSONL named by
  `facts_file` in the updated manifest

- [ ] **Step 1: 写无原文泄漏 RED**

测试矩阵只允许：

```text
product_id | profile | field | normalized value | source class |
source hash prefix | recommendation
```

断言不包含绝对路径、HTML、用户昵称、评论正文、API Key。

- [ ] **Step 2: 生成矩阵**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_data/render_pilot_review_matrix.py \
  --candidates /private/tmp/xiaoro-guide-weekend/pilot-status.jsonl \
  --output docs/audits/guide-closure/data/pilot_review_matrix.md
```

每个 `pending` 行必须有：

```markdown
| 42 | skincare | texture | 悬油质地 | official_description |
b31206098d68 | approve/reject |
```

不得自动填写 reviewer 或 decision。

- [ ] **Step 3: 用户审核 gate**

只提交矩阵供用户选择：

- approve：允许 promotion；
- reject：进入 quarantine；
- defer：保持 pending/unknown。

没有用户明确决定时跳过 promotion，仍可完成来源恢复和状态闭环。

- [ ] **Step 4: 只 promotion 已批准字段**

将用户决定保存为独立 review decision 文件，使用现有
`promote_approved_category_facts.py`，并传入 pending/quarantine SHA。

若存在 `approved_fact`，先用一次性环境变量生成 detached signature：

```bash
export GUIDE_DATA_DECISION_HMAC_KEY="$(openssl rand -hex 32)"
DECISION_SIGNATURE=$(
  /private/tmp/xiaoro-guide-runtime-venv/bin/python \
    tools/guide_data/sign_category_fact_decisions.py \
    --decisions /private/tmp/xiaoro-guide-weekend/review-decisions.jsonl \
    --candidate-sha256 "$PENDING_SHA" \
    --key-env GUIDE_DATA_DECISION_HMAC_KEY
)
```

`sign_category_fact_decisions.py` 必须复用 promotion 模块的 canonical signature
payload，输出只含 64 位 signature，不打印 key。对应测试证明候选 SHA、决策字节或 key
任一变化都会改变 signature。

在 promotion 前计算并锁定：

```bash
PENDING_SHA=$(
  shasum -a 256 \
    /private/tmp/xiaoro-guide-weekend/category-pending.jsonl |
  awk '{print $1}'
)
QUARANTINE_SHA=$(
  shasum -a 256 \
    /private/tmp/xiaoro-guide-weekend/category-quarantine.jsonl |
  awk '{print $1}'
)
DECISIONS_SHA=$(
  shasum -a 256 \
    /private/tmp/xiaoro-guide-weekend/review-decisions.jsonl |
  awk '{print $1}'
)
```

Run:

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_data/promote_approved_category_facts.py \
  --candidates /private/tmp/xiaoro-guide-weekend/category-pending.jsonl \
  --quarantine /private/tmp/xiaoro-guide-weekend/category-quarantine.jsonl \
  --decisions /private/tmp/xiaoro-guide-weekend/review-decisions.jsonl \
  --canonical-manifest data/canonical/core_products_v1_manifest.json \
  --canonical-products data/canonical/core_products_v1.jsonl \
  --output-dir data/guide_category_facts \
  --expected-candidates-sha256 "$PENDING_SHA" \
  --expected-quarantine-sha256 "$QUARANTINE_SHA" \
  --expected-decisions-sha256 "$DECISIONS_SHA" \
  --decision-signature "$DECISION_SIGNATURE" \
  --decision-key-env GUIDE_DATA_DECISION_HMAC_KEY
unset GUIDE_DATA_DECISION_HMAC_KEY
```

若没有批准行，不运行该命令，生产 `fact_count` 保持 0。

- [ ] **Step 5: Commit**

```bash
git add \
  tools/guide_data/render_pilot_review_matrix.py \
  tools/guide_data/sign_category_fact_decisions.py \
  tests/guide/tools/test_render_pilot_review_matrix.py \
  tests/guide/tools/test_sign_category_fact_decisions.py \
  docs/audits/guide-closure/data/pilot_review_matrix.md
git commit -m "docs(data): publish pilot evidence review matrix"
```

只有存在用户批准时，另做数据提交：

```bash
git add data/guide_category_facts
git commit -m "data(guide): promote reviewed pilot facts"
```

### Task 7: 修正错误报告并运行数据门禁

**Files:**
- Modify: `docs/audits/guide-closure/data/source_inventory_summary.md`
- Modify: `docs/audits/guide-closure/data/candidate_queue_summary.json`
- Generate: `docs/audits/guide-closure/data/pilot_field_coverage.json`

- [ ] **Step 1: 重新生成汇总**

汇总必须写：

```text
locked_review_sources_found=3
locked_review_sources_missing=0
historical_html_sha_match=3/3
historical_intermediate_336_111=NOT_REPRODUCED
approved_review_sources=6
automatic_reviewers=0
automatic_approvals=0
promotion_invocations=0 before a signed user decision
promotion_invocations=1 after one signed reviewed promotion batch
```

删除“文件缺失”结论，不改写历史 git 记录。

- [ ] **Step 2: 运行数据 focused**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/tools/test_inventory_local_sources.py \
  tests/guide/tools/test_find_locked_review_sources.py \
  tests/guide/tools/test_read_seed_dump_products.py \
  tests/guide/tools/test_build_seed_database_candidates.py \
  tests/guide/tools/test_extract_saved_page_evidence.py \
  tests/guide/tools/test_build_review_candidates.py \
  tests/guide/tools/test_reconcile_pilot_candidates.py \
  tests/guide/tools/test_report_pilot_field_coverage.py \
  tests/guide/tools/test_recovery_is_non_promoting.py \
  tests/guide/tools/test_promote_approved_category_facts.py \
  tests/guide/tools/test_promote_approved_reviews.py
```

Expected: PASS。

- [ ] **Step 3: 保护资产检查**

```bash
shasum -a 256 \
  data/canonical/core_products_v1_manifest.json \
  data/canonical/core_products_v1.jsonl \
  app/guide/decision/deterministic_ranking.py \
  data/guide_review_sources/approved_tmall_feed_reviews_v1_manifest.json \
  data/guide_review_sources/approved_tmall_feed_reviews_v1.jsonl
git diff --check
```

Expected:

- Canonical 和 ranking 保持冻结值；
- 六条批准评论不漂移；
- 未批准候选不进入生产。

- [ ] **Step 4: Commit**

```bash
git add \
  docs/audits/guide-closure/data/source_inventory_summary.md \
  docs/audits/guide-closure/data/candidate_queue_summary.json \
  docs/audits/guide-closure/data/pilot_field_coverage.json
git commit -m "docs(data): correct recovered source evidence"
```

- [ ] **Step 5: 固定 checkpoint**

```text
已完成：三份 HTML 找回；数据库字段分层；15 商品核对矩阵
当前卡点：待用户批准的候选数量 / 无
剩余工作：只 promotion 明确批准字段
预计完成：2026-08-15
```

若同一 parser 或 binding 问题连续两次修复仍失败，停止并讨论；不得按文件名或相似商品
猜绑定。
