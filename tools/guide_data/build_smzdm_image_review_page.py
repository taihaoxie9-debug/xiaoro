"""Build a self-contained side-by-side SMZDM image review page."""

from __future__ import annotations

import argparse
import base64
from html import escape
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


def merge_image_review_candidates(
    *,
    image_candidates: Sequence[Mapping[str, object]],
    reviewed_candidates: Sequence[Mapping[str, object]] = (),
) -> tuple[Mapping[str, object], ...]:
    """Merge full reviewed rows with image-only rows by product identity."""
    by_product_id: dict[int, Mapping[str, object]] = {}
    for candidate in (*reviewed_candidates, *image_candidates):
        product_id = candidate.get("canonical_product_id")
        if type(product_id) is not int or product_id < 1:
            raise ValueError(
                "image review candidate product_id must be positive"
            )
        by_product_id.setdefault(product_id, candidate)
    return tuple(
        by_product_id[product_id]
        for product_id in sorted(by_product_id)
    )


def load_current_assets_from_manifest(
    *,
    image_manifest_path: str | Path,
    repo_root: str | Path,
    product_ids: Sequence[int],
) -> dict[int, dict[str, object]]:
    """Load only the Canonical image explicitly mapped to each product ID."""
    root = Path(repo_root).resolve()
    requested_ids = set(product_ids)
    assets: dict[int, dict[str, object]] = {}
    for line in Path(image_manifest_path).read_text(
        encoding="utf-8"
    ).splitlines():
        if not line.strip():
            continue
        row: dict[str, Any] = json.loads(line)
        product_id = row.get("product_id")
        if product_id not in requested_ids:
            continue
        relative_path = row.get("relative_path")
        if not isinstance(relative_path, str) or not relative_path:
            continue
        image_path = (root / relative_path).resolve()
        if not image_path.is_relative_to(root) or not image_path.is_file():
            continue
        assets[product_id] = {
            "product_id": product_id,
            "image_path": relative_path,
            "image_bytes": image_path.read_bytes(),
        }
    return assets


def build_image_review_page(
    *,
    candidates: Sequence[Mapping[str, object]],
    current_assets: Mapping[int, Mapping[str, object]],
    candidate_image_root: str | Path,
    output_path: str | Path,
) -> None:
    root = Path(candidate_image_root)
    cards = [
        _render_card(
            candidate=candidate,
            current=current_assets.get(
                int(candidate["canonical_product_id"])
            ),
            candidate_image=_find_candidate_image(
                root,
                int(candidate["canonical_product_id"]),
            ),
        )
        for candidate in candidates
    ]
    html = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SMZDM 图片候选审核</title>
<style>
:root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont,
  "Segoe UI", sans-serif; }
body { margin: 0; background: #f4f5f7; color: #202124; }
header { padding: 28px 32px 18px; background: #fff; border-bottom: 1px solid #ddd; }
h1 { margin: 0 0 8px; font-size: 24px; }
.note { margin: 0; color: #666; font-size: 14px; }
main { max-width: 1320px; margin: 24px auto; padding: 0 20px 40px; }
.review-card { background: #fff; border: 1px solid #d9dce1; margin-bottom: 24px;
  padding: 20px; }
.card-head { display: flex; justify-content: space-between; gap: 16px;
  align-items: flex-start; border-bottom: 1px solid #e5e7eb; padding-bottom: 14px; }
.title { font-size: 18px; font-weight: 650; margin: 0 0 6px; }
.sub { color: #666; font-size: 13px; }
.status { padding: 5px 9px; border: 1px solid #b8d8bf; color: #216e39;
  background: #f0faf2; font-size: 13px; white-space: nowrap; }
.images { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px; margin-top: 18px; }
.image-panel { border: 1px solid #e1e4e8; background: #fafafa; }
.image-panel h2 { font-size: 14px; margin: 0; padding: 11px 12px;
  background: #fff; border-bottom: 1px solid #e1e4e8; }
.image-wrap { min-height: 320px; display: grid; place-items: center; padding: 16px; }
.image-wrap img { max-width: 100%; max-height: 520px; object-fit: contain;
  background: white; }
.missing { color: #a33; padding: 40px; }
.facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px; margin-top: 18px; }
.fact { padding: 10px 12px; background: #f7f8fa; border: 1px solid #e5e7eb; }
.label { display: block; color: #777; font-size: 12px; margin-bottom: 4px; }
.value { font-size: 13px; overflow-wrap: anywhere; }
@media (max-width: 760px) {
  header { padding: 22px 18px 14px; }
  main { margin-top: 14px; padding: 0 12px 24px; }
  .images, .facts { grid-template-columns: 1fr; }
  .card-head { display: block; }
  .status { display: inline-block; margin-top: 10px; }
}
</style>
</head>
<body>
<header>
  <h1>SMZDM 图片候选审核</h1>
  <p class="note">左侧为当前正式图，右侧为抓取候选图。此页面不执行替换，规格冲突仍需人工裁决。</p>
</header>
<main>
""" + "\n".join(cards) + """
</main>
</body>
</html>
"""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8")


def _render_card(
    *,
    candidate: Mapping[str, object],
    current: Mapping[str, object] | None,
    candidate_image: Path | None,
) -> str:
    product_id = int(candidate["canonical_product_id"])
    title = escape(str(candidate.get("source_title", "")))
    image_review = candidate.get("image_review")
    if not isinstance(image_review, Mapping):
        image_review = {}
    fields = candidate.get("candidate_fields")
    if not isinstance(fields, Mapping):
        fields = {}
    conflicts = candidate.get("existing_asset_conflicts")
    if not isinstance(conflicts, list):
        conflicts = []
    status = escape(str(candidate.get("fact_promotion_status", "unknown")))
    current_src = _current_image_data(current)
    candidate_src = _image_data(candidate_image)
    facts = [
        ("商品 ID", str(product_id)),
        ("来源标题", title),
        ("规格", str(fields.get("net_content", ""))),
        ("SKU 判断", str(image_review.get("sku_match_assessment", ""))),
        ("背景判断", str(image_review.get("background_assessment", ""))),
        ("事实提升", status),
        ("规格冲突", json.dumps(conflicts, ensure_ascii=False)),
        ("来源页", str(candidate.get("source_url", ""))),
        ("图片 hash", str(image_review.get("source_sha256", ""))),
    ]
    fact_html = "".join(
        f'<div class="fact"><span class="label">{escape(label)}</span>'
        f'<span class="value">{escape(value)}</span></div>'
        for label, value in facts
    )
    return f"""
<section class="review-card" data-product-id="{product_id}">
  <div class="card-head">
    <div>
      <p class="title">product_id={product_id} · {title}</p>
      <p class="sub">候选状态：{escape(str(image_review.get("status", "unknown")))}</p>
    </div>
    <span class="status">{status}</span>
  </div>
  <div class="images">
    <div class="image-panel">
      <h2>现有正式图</h2>
      <div class="image-wrap">{current_src or '<div class="missing">没有当前正式图</div>'}</div>
    </div>
    <div class="image-panel">
      <h2>SMZDM 候选图</h2>
      <div class="image-wrap">{candidate_src or '<div class="missing">候选图尚未下载</div>'}</div>
    </div>
  </div>
  <div class="facts">{fact_html}</div>
</section>
"""


def _find_candidate_image(root: Path, product_id: int) -> Path | None:
    product_root = root / "source_images" / str(product_id)
    if product_root.is_dir():
        files = sorted(
            item
            for item in product_root.iterdir()
            if item.is_file()
        )
        if files:
            return files[0]
    files = sorted(
        item
        for item in root.rglob("*")
        if item.is_file() and item.suffix.casefold() in {
            ".jpg", ".jpeg", ".png", ".webp"
        }
    )
    return files[0] if len(files) == 1 else None


def _current_image_data(current: Mapping[str, object] | None) -> str | None:
    if not isinstance(current, Mapping):
        return None
    image_bytes = current.get("image_bytes")
    if not isinstance(image_bytes, bytes) or not image_bytes:
        return None
    suffix = Path(str(current.get("image_path", ""))).suffix.casefold()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "image/png")
    return _data_uri(image_bytes, mime)


def _image_data(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        content = path.read_bytes()
    except OSError:
        return None
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(path.suffix.casefold(), "image/png")
    return _data_uri(content, mime)


def _data_uri(content: bytes, mime: str) -> str:
    encoded = base64.b64encode(content).decode("ascii")
    return f'<img src="data:{mime};base64,{encoded}" alt="">'


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a self-contained SMZDM image review HTML page."
    )
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--review-candidates", type=Path)
    parser.add_argument("--candidate-image-root", type=Path, required=True)
    parser.add_argument(
        "--current-image-manifest",
        type=Path,
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    image_candidates = tuple(
        json.loads(line)
        for line in args.candidates.read_text(encoding="utf-8").splitlines()
        if line
    )
    reviewed_candidates = (
        tuple(
            json.loads(line)
            for line in args.review_candidates.read_text(
                encoding="utf-8"
            ).splitlines()
            if line
        )
        if args.review_candidates is not None
        else ()
    )
    candidates = merge_image_review_candidates(
        image_candidates=image_candidates,
        reviewed_candidates=reviewed_candidates,
    )
    repo_root = Path(__file__).resolve().parents[2]
    assets = load_current_assets_from_manifest(
        image_manifest_path=args.current_image_manifest,
        repo_root=repo_root,
        product_ids=tuple(
            int(candidate["canonical_product_id"])
            for candidate in candidates
        ),
    )
    build_image_review_page(
        candidates=candidates,
        current_assets=assets,
        candidate_image_root=args.candidate_image_root,
        output_path=args.output,
    )
    print(json.dumps({
        "candidate_count": len(candidates),
        "output": str(args.output),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
