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
