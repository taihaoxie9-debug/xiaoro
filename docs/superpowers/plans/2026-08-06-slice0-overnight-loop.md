# Slice 0 Overnight Mechanical Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不写旧仓库、不访问网络或数据库、不修改业务语义的条件下，完成 Slice 0 资产存档、图片源 manifest、前端与测试基线、CSV 证据和晨间交接。

**Architecture:** 夜间循环只处理可机械验证的资产和证据。旧仓库是只读来源，新仓库是唯一写入目标；每轮只完成一个小任务并独立验证，任何需要产品判断的事项进入晨间交接，不在夜间猜测。

**Tech Stack:** Python 3.11、pytest、标准库 `csv/json/hashlib/pathlib`、Git、SHA-256、Markdown、CSV。

---

## 1. 执行边界

### 1.1 允许

- 读取 `/Users/bytedance/Desktop/xiaoro-shopping-master`
- 在 `/Users/bytedance/Desktop/xiaoro-fresh` 创建本计划列出的文件
- 运行完全离线的专项测试
- 计算 SHA-256、行数、文件数和 Git 状态
- 生成 JSONL、JSON、CSV 和 Markdown 证据
- 在 `rebuild` 分支创建本地小提交

### 1.2 禁止

- 修改旧仓库任何文件
- 运行网络请求、模型下载、数据库连接、Milvus、Redis 或 Celery
- 修改 `app/static/chat.html`
- 修改 `app/api/v1/chat.py`
- 修改意图分类、决策权重、轻问诊规则或画像 Schema
- 修改或提交当前未跟踪的 `app/guide/`
- 复制 Agent、Presenter、TurnParser、Retriever、Ranker 或 followup 模块
- 执行 `git reset --hard`、`git clean`、`git checkout --` 或其他破坏性命令
- push 到远程
- 为了让测试变绿而改变旧测试或旧实现

### 1.3 硬停止条件

出现任一条件时，停止当前任务并记录到晨间交接：

- 旧仓库 `git status --porcelain=v1` 的 SHA-256 不再等于 `be35dbe626b26a65c8cff09d594aba2e4540f9f8f9e55a3d5fe0a1783c9f4d8c`
- Canonical、审核决定、seed dump 或 103 张种子图片的已知 SHA 不匹配
- 需要解释业务语义或选择字段权威
- 命令尝试访问网络或数据库
- 同一失败连续出现两次
- 新仓库暂存区包含计划白名单之外的文件
- 任一操作会覆盖用户未提交内容

已知例外：

- 旧 LLM cache 专项预期保持 `7 failed / 4 passed`，只记录，不修复。
- 当前 `app/guide/check_boundaries.py` 编码的是旧 `catalog/response/orchestration` 结构，今晚隔离，不提交。

## 2. 循环协议

每轮严格执行：

1. 读取本计划和最新 Git 状态。
2. 选择第一个未完成任务。
3. 校验该任务的输入 SHA 和禁止条件。
4. 只执行一个任务或一个 2 到 5 分钟步骤。
5. 运行该步骤指定的验证命令。
6. 在本计划的 `Loop Progress` 追加真实结果。
7. 只暂存该任务白名单文件。
8. 达到任务提交点时创建本地提交。
9. 继续下一轮，直到安全队列完成。

失败处理：

- 第一次失败：记录原始错误，检查是否为命令或环境问题。
- 第二次相同失败：停止该任务，写入晨间交接，继续不依赖它的任务。
- 不允许添加兼容补丁绕过失败。

完成定义：

- Task 1 到 Task 6 均为 `completed` 或明确记录为 `deferred`。
- 新仓库没有意外暂存内容。
- 旧仓库状态 SHA 未变化。
- 晨间交接列出所有提交、证据和需白天决定的问题。

## 3. 文件映射

### 创建

- `data/canonical/shadow_review_v1/review_decisions_manifest.json`
- `tests/slice0/test_canonical_assets.py`
- `scripts/build_seed_image_manifest.py`
- `tests/slice0/test_seed_image_manifest.py`
- `data/canonical/seed_product_images_v1.jsonl`
- `data/canonical/seed_product_images_v1_manifest.json`
- `docs/audits/slice0/asset_ledger.csv`
- `docs/audits/slice0/frontend_contract_baseline.md`
- `docs/audits/slice0/test_asset_map.csv`
- `docs/audits/slice0/test_evidence.csv`
- `docs/audits/slice0/morning_handoff.md`

### 修改

- `docs/superpowers/plans/2026-08-06-slice0-overnight-loop.md`

### 明确不修改

- `app/guide/**`
- `app/static/chat.html`
- `app/api/v1/chat.py`
- 旧仓库全部文件

## Task 1: 固化 Canonical 与审核决定

**Files:**
- Create: `data/canonical/shadow_review_v1/review_decisions_manifest.json`
- Create: `tests/slice0/test_canonical_assets.py`
- Verify: `data/canonical/core_products_v1.jsonl`
- Verify: `data/canonical/core_products_v1_manifest.json`
- Verify: `data/canonical/shadow_review_v1/review_decisions.jsonl`
- Verify: `data/seed_dump.sql`

- [x] **Step 1: 写 Canonical 资产失败测试**

创建 `tests/slice0/test_canonical_assets.py`：

```python
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "data/canonical"

EXPECTED = {
    "seed_dump": "ae45bbb513868619e578f63f252fff549ad62289aba0d474e2ae65aa754bc386",
    "products": "0ba95df8c38d39f5bc0d73a32c318b157903abb64778c3e7b0acebfb75e95734",
    "review_decisions": "12b0e1f82df3509ad8886af68a04ddcc62b28f3d3a5c72f4496ea22708fe50e9",
}


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_digest(payload: dict) -> str:
    unsigned = {
        key: value
        for key, value in payload.items()
        if key != "manifest_sha256"
    }
    text = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        assert line.strip(), f"blank JSONL line: {line_number}"
        rows.append(json.loads(line))
    return rows


def test_canonical_assets_are_complete_and_hash_locked() -> None:
    products_path = CANONICAL / "core_products_v1.jsonl"
    products_manifest_path = CANONICAL / "core_products_v1_manifest.json"
    decisions_path = (
        CANONICAL / "shadow_review_v1/review_decisions.jsonl"
    )
    decisions_manifest_path = (
        CANONICAL
        / "shadow_review_v1/review_decisions_manifest.json"
    )
    seed_dump_path = ROOT / "data/seed_dump.sql"

    assert sha256_path(seed_dump_path) == EXPECTED["seed_dump"]
    assert sha256_path(products_path) == EXPECTED["products"]
    assert sha256_path(decisions_path) == EXPECTED["review_decisions"]

    products = read_jsonl(products_path)
    decisions = read_jsonl(decisions_path)
    assert len(products) == 103
    assert len(decisions) == 1234

    product_ids = {int(row["product_id"]) for row in products}
    reviewed_ids = {int(row["product_id"]) for row in decisions}
    assert len(product_ids) == 103
    assert reviewed_ids == product_ids

    products_manifest = json.loads(
        products_manifest_path.read_text(encoding="utf-8")
    )
    decisions_manifest = json.loads(
        decisions_manifest_path.read_text(encoding="utf-8")
    )

    assert products_manifest["product_count"] == 103
    assert products_manifest["products_sha256"] == EXPECTED["products"]
    assert (
        products_manifest["review_decisions_sha256"]
        == EXPECTED["review_decisions"]
    )
    assert (
        products_manifest["manifest_sha256"]
        == manifest_digest(products_manifest)
    )

    assert decisions_manifest["reviewed_products"] == 103
    assert decisions_manifest["total_decisions"] == 1234
    assert (
        decisions_manifest["review_decisions_sha256"]
        == EXPECTED["review_decisions"]
    )
    assert (
        decisions_manifest["manifest_sha256"]
        == manifest_digest(decisions_manifest)
    )
```

- [x] **Step 2: 运行测试确认缺少审核 manifest**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest \
  -p no:cacheprovider \
  tests/slice0/test_canonical_assets.py -q
```

Expected: FAIL，原因是
`data/canonical/shadow_review_v1/review_decisions_manifest.json`
不存在。

- [x] **Step 3: 原样复制审核 manifest**

Run:

```bash
cp \
  /Users/bytedance/Desktop/xiaoro-shopping-master/.tmp_user_download_audit/shadow_review_v1/review_decisions_manifest.json \
  data/canonical/shadow_review_v1/review_decisions_manifest.json
```

Expected SHA-256:

```text
999be8b3238176ed57cab47d2fa7db30ed76a2840908bc9c2d52c06a3ec7f633
```

- [x] **Step 4: 运行 Canonical 资产测试**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest \
  -p no:cacheprovider \
  tests/slice0/test_canonical_assets.py -q
```

Expected: `1 passed`

- [x] **Step 5: 只提交 Canonical 资产**

Run:

```bash
git add \
  data/canonical/core_products_v1.jsonl \
  data/canonical/core_products_v1_manifest.json \
  data/canonical/shadow_review_v1/review_decisions.jsonl \
  data/canonical/shadow_review_v1/review_decisions_manifest.json \
  tests/slice0/test_canonical_assets.py
git diff --cached --check
git commit -m "data: preserve canonical decision assets"
```

禁止暂存 `app/guide/`。

## Task 2: 生成 103 张种子图片源 manifest

**Files:**
- Create: `scripts/build_seed_image_manifest.py`
- Create: `tests/slice0/test_seed_image_manifest.py`
- Create: `data/canonical/seed_product_images_v1.jsonl`
- Create: `data/canonical/seed_product_images_v1_manifest.json`

- [x] **Step 1: 写图片 manifest 失败测试**

创建 `tests/slice0/test_seed_image_manifest.py`：

```python
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.build_seed_image_manifest import build_seed_image_manifest


ROOT = Path(__file__).resolve().parents[2]


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_digest(payload: dict) -> str:
    unsigned = {
        key: value
        for key, value in payload.items()
        if key != "manifest_sha256"
    }
    text = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_seed_image_manifest_is_complete_and_deterministic(
    tmp_path: Path,
) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first = build_seed_image_manifest(
        root=ROOT,
        seed_dump=ROOT / "data/seed_dump.sql",
        output_dir=first_dir,
    )
    second = build_seed_image_manifest(
        root=ROOT,
        seed_dump=ROOT / "data/seed_dump.sql",
        output_dir=second_dir,
    )

    first_jsonl = first_dir / "seed_product_images_v1.jsonl"
    second_jsonl = second_dir / "seed_product_images_v1.jsonl"
    assert first_jsonl.read_bytes() == second_jsonl.read_bytes()
    assert first == second

    rows = [
        json.loads(line)
        for line in first_jsonl.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert len(rows) == 103
    assert len({row["product_id"] for row in rows}) == 103
    assert len({row["image_url"] for row in rows}) == 103

    for row in rows:
        path = ROOT / row["relative_path"]
        assert path.is_file()
        assert row["source_image_sha256"] == sha256_path(path)
        assert row["bytes"] == path.stat().st_size
        assert row["media_type"] in {
            "image/jpeg",
            "image/png",
            "image/webp",
        }

    assert first["schema_version"] == "seed-product-images-v1"
    assert first["product_count"] == 103
    assert first["manifest_sha256"] == manifest_digest(first)
```

- [x] **Step 2: 运行测试确认构建器不存在**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest \
  -p no:cacheprovider \
  tests/slice0/test_seed_image_manifest.py -q
```

Expected: collection ERROR，原因是
`scripts.build_seed_image_manifest` 不存在。

- [x] **Step 3: 实现确定性 manifest 构建器**

创建 `scripts/build_seed_image_manifest.py`：

```python
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


JSONL_NAME = "seed_product_images_v1.jsonl"
MANIFEST_NAME = "seed_product_images_v1_manifest.json"
SCHEMA_VERSION = "seed-product-images-v1"
MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def product_image_rows(
    *,
    root: Path,
    seed_dump: Path,
) -> list[dict[str, Any]]:
    columns: list[str] | None = None
    in_products = False
    rows: list[dict[str, Any]] = []

    for raw_line in seed_dump.read_text(
        encoding="utf-8"
    ).splitlines():
        if raw_line.startswith("COPY public.products ("):
            column_text = raw_line.split("(", 1)[1].split(
                ") FROM stdin;",
                1,
            )[0]
            columns = [
                item.strip()
                for item in column_text.split(",")
            ]
            in_products = True
            continue
        if not in_products:
            continue
        if raw_line == r"\.":
            break
        assert columns is not None
        values = next(csv.reader(
            [raw_line],
            delimiter="\t",
            quoting=csv.QUOTE_NONE,
        ))
        if len(values) != len(columns):
            raise ValueError("invalid products COPY row width")
        record = dict(zip(columns, values))
        product_id = int(record["id"])
        image_url = record["image_url"].strip()
        if not image_url.startswith("/static/images/products/"):
            raise ValueError(
                f"invalid product image URL: {product_id}"
            )
        relative_path = f"app{image_url}"
        image_path = root / relative_path
        if not image_path.is_file():
            raise FileNotFoundError(
                f"missing product image: {product_id}"
            )
        media_type = MEDIA_TYPES.get(
            image_path.suffix.lower()
        )
        if media_type is None:
            raise ValueError(
                f"unsupported image type: {product_id}"
            )
        rows.append({
            "product_id": product_id,
            "image_url": image_url,
            "relative_path": relative_path,
            "media_type": media_type,
            "bytes": image_path.stat().st_size,
            "source_image_sha256": sha256_path(image_path),
        })

    rows.sort(key=lambda item: item["product_id"])
    if len(rows) != 103:
        raise ValueError(
            f"expected 103 product images, got {len(rows)}"
        )
    if len({item["product_id"] for item in rows}) != 103:
        raise ValueError("duplicate product ID")
    if len({item["image_url"] for item in rows}) != 103:
        raise ValueError("duplicate product image URL")
    return rows


def build_seed_image_manifest(
    *,
    root: Path,
    seed_dump: Path,
    output_dir: Path,
) -> dict[str, Any]:
    rows = product_image_rows(
        root=root,
        seed_dump=seed_dump,
    )
    jsonl_text = "\n".join(
        canonical_json(row)
        for row in rows
    ) + "\n"
    jsonl_path = output_dir / JSONL_NAME
    atomic_write(jsonl_path, jsonl_text)

    source_digest_text = "\n".join(
        (
            f"{row['product_id']}\t"
            f"{row['source_image_sha256']}"
        )
        for row in rows
    )
    manifest_base = {
        "schema_version": SCHEMA_VERSION,
        "products_file": JSONL_NAME,
        "product_count": len(rows),
        "seed_dump_sha256": sha256_path(seed_dump),
        "products_sha256": hashlib.sha256(
            jsonl_text.encode("utf-8")
        ).hexdigest(),
        "source_images_sha256": hashlib.sha256(
            source_digest_text.encode("utf-8")
        ).hexdigest(),
    }
    manifest = {
        **manifest_base,
        "manifest_sha256": hashlib.sha256(
            canonical_json(manifest_base).encode("utf-8")
        ).hexdigest(),
    }
    atomic_write(
        output_dir / MANIFEST_NAME,
        canonical_json(manifest) + "\n",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--seed-dump",
        type=Path,
        default=Path("data/seed_dump.sql"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/canonical"),
    )
    args = parser.parse_args()
    manifest = build_seed_image_manifest(
        root=args.root.resolve(),
        seed_dump=args.seed_dump.resolve(),
        output_dir=args.output_dir.resolve(),
    )
    print(canonical_json(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 4: 运行图片 manifest 测试**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest \
  -p no:cacheprovider \
  tests/slice0/test_seed_image_manifest.py -q
```

Expected: `1 passed`

- [x] **Step 5: 生成正式图片源 manifest**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  scripts/build_seed_image_manifest.py \
  --root . \
  --seed-dump data/seed_dump.sql \
  --output-dir data/canonical
```

Expected:

- `product_count` 为 103
- 103 个 product ID 唯一
- 103 个 image URL 唯一
- 不访问网络、数据库或模型

- [x] **Step 6: 重跑测试并提交**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest \
  -p no:cacheprovider \
  tests/slice0/test_seed_image_manifest.py \
  tests/slice0/test_canonical_assets.py -q
git add \
  scripts/build_seed_image_manifest.py \
  tests/slice0/test_seed_image_manifest.py \
  data/canonical/seed_product_images_v1.jsonl \
  data/canonical/seed_product_images_v1_manifest.json
git diff --cached --check
git commit -m "feat: add deterministic seed image manifest"
```

Expected: `2 passed`

## Task 3: 建立资产总账

**Files:**
- Create: `docs/audits/slice0/asset_ledger.csv`

- [x] **Step 1: 写入已审计资产记录**

创建 CSV，字段固定为：

```csv
asset_id,category,source_path,target_or_status,sha256,source_git_state,night_action,runtime_policy
canonical_products,data,data/canonical/core_products_v1.jsonl,data/canonical/core_products_v1.jsonl,0ba95df8c38d39f5bc0d73a32c318b157903abb64778c3e7b0acebfb75e95734,untracked_in_fresh,commit_exact,runtime_source
canonical_manifest,data,data/canonical/core_products_v1_manifest.json,data/canonical/core_products_v1_manifest.json,e0430a244af451a3fa73642295c4a79128e1622dfeed19ff8140eda9f2df0c69,untracked_in_fresh,commit_exact,runtime_integrity
review_decisions,data,data/canonical/shadow_review_v1/review_decisions.jsonl,data/canonical/shadow_review_v1/review_decisions.jsonl,12b0e1f82df3509ad8886af68a04ddcc62b28f3d3a5c72f4496ea22708fe50e9,untracked_in_fresh,commit_exact,runtime_source
review_manifest,data,.tmp_user_download_audit/shadow_review_v1/review_decisions_manifest.json,data/canonical/shadow_review_v1/review_decisions_manifest.json,999be8b3238176ed57cab47d2fa7db30ed76a2840908bc9c2d52c06a3ec7f633,untracked_in_old,copy_exact,runtime_integrity
seed_dump,data,data/seed_dump.sql,reference_only,ae45bbb513868619e578f63f252fff549ad62289aba0d474e2ae65aa754bc386,tracked_in_fresh,verify_only,not_runtime_schema
seed_images,data,app/static/images/products,tracked_103_files,08f761a16d41db4d04355245ec107bc456154ac8bf60939a0268e4ced8fa45e7,tracked_in_fresh,build_source_manifest,runtime_image_source
knowledge_docs,knowledge,data/knowledge_docs,quarantine,9a4eaacd6a88f996c52db8c68f1df4e713f4fdcc8a856d6798b1cf02f555101a,tracked_in_fresh,verify_only,not_production_rag
frontend_chat,product_ui,app/static/chat.html,preserve_baseline,3064d7753fcfbc33be5d300c70ad395542b066c76bfd574162a4c4955d250bec,modified_in_old,record_only,protected_asset
chat_api,transport,app/api/v1/chat.py,rebase_contract,a07e7433b3b676ffff375aebd46466d9a79205c9c0d4168ee721c9333bdb530c,modified_in_old,record_only,no_direct_copy
ranking_kernel,pure_kernel,app/services/deterministic_ranking.py,preserve_later,4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f,untracked_in_old,record_only,decision_owned
shadow_evidence,offline_tool,app/services/v2/shadow_evidence,preserve_later,0553057800cc79b1c06453b26da901856d6daccad43c401ba87d384c9e31b6fa,untracked_in_old,record_only,never_runtime_import
session_runtime,infrastructure,app/services/session_runtime.py,extract_later,399a299553524e53a566d1bea7be4c159f70458e96e4f213e75378cd0a8afdc1,untracked_in_old,record_only,extract_cache_and_lock
ocr_service,adapter,app/services/ocr.py,extract_parser_later,48dfbc4aacb4cb61dcad72424dba60e409b80a429409e7799d087039dbe0032c,modified_in_old,record_only,no_direct_copy
guide_scaffold,obsolete_scaffold,app/guide/check_boundaries.py,quarantine,05538019abe0314499b8e8e06925af71b7d6fd3557bcdd556c093a6654071aba,untracked_in_fresh,do_not_commit,encodes_old_architecture
```

- [x] **Step 2: 验证 CSV**

Run:

```bash
python3 -c '
import csv
from pathlib import Path
p = Path("docs/audits/slice0/asset_ledger.csv")
rows = list(csv.DictReader(p.open(encoding="utf-8")))
assert len(rows) == 14
assert len({row["asset_id"] for row in rows}) == 14
assert all(len(row["sha256"]) == 64 for row in rows)
print("asset-ledger-ok")
'
```

Expected: `asset-ledger-ok`

## Task 4: 固化前端与测试资产基线

**Files:**
- Create: `docs/audits/slice0/frontend_contract_baseline.md`
- Create: `docs/audits/slice0/test_asset_map.csv`

- [x] **Step 1: 写前端合同基线**

文档必须明确：

```markdown
# Frontend Contract Baseline

## Protected Sources

- `app/static/chat.html`
  - SHA-256: `3064d7753fcfbc33be5d300c70ad395542b066c76bfd574162a4c4955d250bec`
- `app/api/v1/chat.py`
  - SHA-256: `a07e7433b3b676ffff375aebd46466d9a79205c9c0d4168ee721c9333bdb530c`

## Preserved Behaviors

- SSE 增量文本
- start/stage/intent/decision_process/answer_contract
- clarify/chips
- products/comparison/routine/citations/pitfalls
- message/error/end
- 商品卡与结构化面板
- 会话快照与同会话串行保护
- 安全 DOM、URL 和公开错误脱敏
- 最多 4 张图片的预览持久化

## Known Multi-Image Gap

当前前端会逐张请求识图，再把每张图的候选摊平成一个
`image_results` 列表。它没有保留 `image_id -> candidates`
的边界，因此不能支持可靠的“第一张/第二张”比较。

新合同必须改为 server-owned `ImageBundle`，但夜间不修改前端。

## Night Policy

本文件只记录基线。夜间禁止修改上述两个 protected source。
```

- [x] **Step 2: 写测试资产映射 CSV**

```csv
cluster,current_evidence,target_slice,migration_action,night_policy
decision_evidence,300_passed,0_1_3,extract_contract_tests,run_offline
session_ocr,64_passed,0_2_4,extract_pure_primitives,run_offline
transport_sse,69_passed,0_1_2,preserve_behavior_tests,run_offline
token_image_storage,73_passed,0_2,preserve_contract_tests,run_offline
data_build_scripts,44_passed,0,preserve_reproducibility,run_offline
intent_compiler,80_passed,1_4,extract_validation_and_merge,run_offline
frontend_xss,173_passed_plus_5_subtests,0_1_2,preserve_browser_contract,run_offline
image_contract,67_passed,2_3_5,preserve_contract_not_implementation,record_existing
llm_cache,7_failed_4_passed,1,rewrite_from_contract,record_expected_failure
golden_fixtures,17_files,1_3_4,keep_scenarios_not_old_snapshots,inventory_only
```

- [x] **Step 3: 验证基线文件**

Run:

```bash
python3 -c '
import csv
from pathlib import Path
front = Path("docs/audits/slice0/frontend_contract_baseline.md")
assert "ImageBundle" in front.read_text(encoding="utf-8")
rows = list(csv.DictReader(
    Path("docs/audits/slice0/test_asset_map.csv").open(
        encoding="utf-8"
    )
))
assert len(rows) == 10
assert {row["cluster"] for row in rows} >= {
    "decision_evidence",
    "image_contract",
    "llm_cache",
}
print("baseline-docs-ok")
'
```

Expected: `baseline-docs-ok`

## Task 5: 重跑离线证据门禁

**Files:**
- Create: `docs/audits/slice0/test_evidence.csv`

所有旧仓库测试命令必须包含：

```text
PYTHONDONTWRITEBYTECODE=1
V2_DISABLE_LLM=1
PYTHONHASHSEED=0
-p no:cacheprovider
```

- [x] **Step 1: 运行决策与审核工具专项**

Run from `/Users/bytedance/Desktop/xiaoro-shopping-master`:

```bash
PYTHONDONTWRITEBYTECODE=1 V2_DISABLE_LLM=1 PYTHONHASHSEED=0 \
.venv/bin/pytest -p no:cacheprovider -q \
  tests/test_task19_deterministic_ranking_red.py \
  tests/test_decision_field_contracts_red.py \
  tests/test_candidate_evaluator_red.py \
  tests/test_v2_dynamic_facet_contract.py \
  tests/test_v2_dynamic_facet_serialization.py \
  tests/test_v2_facet_source_authorization.py \
  tests/test_v2_ingredient_provenance_facets.py \
  tests/test_v2_shadow_evidence_contracts.py \
  tests/test_v2_shadow_evidence_classifier.py \
  tests/test_v2_shadow_evidence_ledger.py \
  tests/test_v2_shadow_evidence_review.py \
  tests/test_v2_shadow_evidence_artifacts.py \
  tests/test_v2_shadow_evidence_adapters.py \
  tests/test_v2_shadow_canonical_snapshot.py \
  tests/test_canonical_decision_reader_red.py
```

Expected: `300 passed`

- [x] **Step 2: 运行会话、OCR、传输和安全专项**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 V2_DISABLE_LLM=1 PYTHONHASHSEED=0 \
.venv/bin/pytest -p no:cacheprovider -q \
  tests/test_phase7_session_cache_lifecycle_red.py \
  tests/test_phase7_session_concurrency_red.py \
  tests/test_ocr_service.py \
  tests/test_phase7_session_ownership_red.py \
  tests/test_v2_sse_frontend_state_red.py \
  tests/test_v2_public_error_sanitization_red.py \
  tests/test_v2_api_image_context.py
```

Expected: `112 passed`

- [x] **Step 3: 运行数据、意图和前端专项**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 V2_DISABLE_LLM=1 PYTHONHASHSEED=0 \
.venv/bin/pytest -p no:cacheprovider -q \
  tests/test_v2_shadow_evidence_cli.py \
  tests/test_canonical_decision_reader_red.py \
  tests/test_intent_constraints_red.py \
  tests/test_shadow_decision_pipeline_red.py \
  tests/test_v2_typed_evaluation_runtime_bridge_red.py \
  tests/test_phase7_frontend_xss_red.py
```

Expected: `165 passed`

- [x] **Step 4: 记录 LLM cache 已知失败，不修复**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 V2_DISABLE_LLM=1 PYTHONHASHSEED=0 \
.venv/bin/pytest -p no:cacheprovider -q \
  tests/test_task20_llm_cache_red.py
```

Expected: `7 failed, 4 passed`

结果不同则只记录，不修改实现。

- [x] **Step 5: 写测试证据 CSV**

字段固定为：

```csv
run_id,scope,command_class,passed,failed,status,notes
slice0_decision_evidence,decision_and_evidence,offline_pytest,300,0,pass,asset_classification_only
slice0_session_transport,session_ocr_transport_security,offline_pytest,112,0,pass,combined_selected_suite
slice0_data_intent_frontend,data_intent_frontend,offline_pytest,165,0,pass,combined_selected_suite
slice0_llm_cache,llm_cache_contract,offline_pytest,4,7,known_failure,do_not_fix_overnight
```

如果夜间重跑结果与上述基线不同，CSV 写入真实结果并把状态改为 `regression`，随后停止依赖该结果的任务。

- [x] **Step 6: 验证旧仓库状态未变化**

Run from old repository:

```bash
git status --porcelain=v1 | shasum -a 256
```

Expected:

```text
be35dbe626b26a65c8cff09d594aba2e4540f9f8f9e55a3d5fe0a1783c9f4d8c
```

不一致则停止循环。

## Task 6: 晨间交接与最终本地提交

**Files:**
- Create: `docs/audits/slice0/morning_handoff.md`
- Modify: `docs/superpowers/plans/2026-08-06-slice0-overnight-loop.md`

- [x] **Step 1: 写晨间交接**

先运行：

```bash
git log --format='- `%h` %s' 1998393..HEAD
git status --short --branch
git -C /Users/bytedance/Desktop/xiaoro-shopping-master \
  status --porcelain=v1 | shasum -a 256
```

然后按真实输出写入以下内容：

```markdown
# Slice 0 Morning Handoff

## Completed

- 固化 103 条 Canonical 商品和 1234 条审核决定。
- 补齐审核决定 manifest 并验证内部 SHA。
- 生成 103/103 种子图片源 JSONL 和 manifest。
- 生成资产总账、前端合同基线和测试资产映射。
- 重跑夜间离线测试并写入 CSV 证据。

## Commits

使用 `git log --format='- `%h` %s' 1998393..HEAD` 的真实输出。

## Evidence

- `data/canonical/core_products_v1.jsonl`
- `data/canonical/shadow_review_v1/review_decisions.jsonl`
- `data/canonical/shadow_review_v1/review_decisions_manifest.json`
- `data/canonical/seed_product_images_v1.jsonl`
- `data/canonical/seed_product_images_v1_manifest.json`
- `docs/audits/slice0/asset_ledger.csv`
- `docs/audits/slice0/frontend_contract_baseline.md`
- `docs/audits/slice0/test_asset_map.csv`
- `docs/audits/slice0/test_evidence.csv`

## Deferred

- 现有未跟踪 `app/guide/` 骨架编码旧架构，未提交。
- 高价值纯内核和 `shadow_evidence` 尚未重归位。
- 知识文档仍处于隔离待审核状态。
- LLM cache 保持已知 7 failed / 4 passed，未修复。

## Decisions Needed

- 白天确认如何替换当前过时的 `app/guide/` 空骨架和边界脚本。

## Workspace State

- 新仓库：写入最终 `git status --short --branch`。
- 旧仓库：只读，状态 SHA 必须为 `be35dbe626b26a65c8cff09d594aba2e4540f9f8f9e55a3d5fe0a1783c9f4d8c`。
```

如果任一任务被 deferred，必须从 Completed 移到 Deferred，并附原始失败命令。

- [x] **Step 2: 完整验证新资产**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest \
  -p no:cacheprovider \
  tests/slice0/test_canonical_assets.py \
  tests/slice0/test_seed_image_manifest.py -q
python3 -c '
import csv
from pathlib import Path
for name in ("asset_ledger.csv", "test_asset_map.csv", "test_evidence.csv"):
    path = Path("docs/audits/slice0") / name
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert rows, name
evidence = list(csv.DictReader(
    Path("docs/audits/slice0/test_evidence.csv").open(
        encoding="utf-8"
    )
))
assert {row["status"] for row in evidence} <= {
    "pass",
    "known_failure",
}
print("slice0-evidence-ok")
'
git diff --check
```

Expected:

- `2 passed`
- `slice0-evidence-ok`
- `git diff --check` 无输出

- [x] **Step 3: 检查暂存白名单**

Run:

```bash
git status --short
```

允许存在但禁止暂存：

```text
?? app/guide/
```

允许提交：

```text
docs/audits/slice0/**
docs/superpowers/plans/2026-08-06-slice0-overnight-loop.md
```

- [x] **Step 4: 提交夜间审计证据**

Run:

```bash
git add \
  docs/audits/slice0 \
  docs/superpowers/plans/2026-08-06-slice0-overnight-loop.md
git diff --cached --check
git commit -m "docs: record slice 0 overnight audit"
```

- [x] **Step 5: 最终状态检查**

Run:

```bash
git status --short --branch
git log -4 --oneline --decorate
```

Expected:

- 分支仍为 `rebuild`
- 没有 push
- `app/guide/` 仍未跟踪且未修改
- 夜间任务只产生本计划列出的本地提交

## 4. Loop Progress

- `2026-08-06 plan`: 正式架构设计已批准。夜间范围复审完成。
- `2026-08-06 audit`: 新仓库已有 103 张已跟踪种子图，和旧仓库同名文件 103/103 字节一致。
- `2026-08-06 audit`: 新仓库已有 22 篇已跟踪知识文档，和旧仓库 22/22 字节一致；继续隔离待审核。
- `2026-08-06 audit`: Canonical 103 条和审核决定 1234 条 SHA 正确，但尚未跟踪，且缺审核 manifest。
- `2026-08-06 audit`: 当前未跟踪 `app/guide/check_boundaries.py` 使用旧架构目录，夜间禁止提交。
- `2026-08-06 guard`: 旧仓库基线 HEAD 为 `8658e191c05e208b2939aa37fb1ee170b2784e4f`，状态 SHA 为 `be35dbe626b26a65c8cff09d594aba2e4540f9f8f9e55a3d5fe0a1783c9f4d8c`。
- `2026-08-06 task-1`: Canonical 红测因缺少审核 manifest 按预期失败；补齐 SHA `999be8b3...` 后 `1 passed`。本地提交 `4fd3b36 data: preserve canonical decision assets`。
- `2026-08-06 task-2`: 图片 manifest 红测因构建器不存在按预期报错；实现后 `2 passed`。生成 103 条源图片记录，manifest SHA `f41e52c2...`，来源图片聚合 SHA `6b253e68...`。本地提交 `e965e92 feat: add deterministic seed image manifest`。
- `2026-08-06 task-3`: 资产总账写入 14 个唯一资产 ID，所有记录均有 64 位 SHA，验证输出 `asset-ledger-ok`。
- `2026-08-06 task-4`: 前端基线明确 protected sources、SSE 行为和 `image_results` 扁平化缺口；测试资产映射包含 10 个集群，验证输出 `baseline-docs-ok`。
- `2026-08-06 task-5`: 离线证据门禁结果为 `300/112/165 passed`；LLM cache 保持已知 `7 failed / 4 passed`。旧仓库状态 SHA 仍为 `be35dbe...`，未发生写入。
- `2026-08-06 task-6`: 晨间交接已生成；新资产测试 `2 passed`，CSV 验证输出 `slice0-evidence-ok`，`git diff --check` 无输出。
- `2026-08-07 close`: 审计证据提交 `5cd50bd`；完成审计再次得到 `2 passed` 和 `completion-artifacts-ok`。分支仍为 `rebuild`，`origin/main` 仍为 `7cb6b25`，不存在 `origin/rebuild`，未执行 push。`app/guide/` 保持未跟踪且未进入提交。
