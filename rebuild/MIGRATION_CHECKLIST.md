# 真资产搬运清单（从旧仓库 → 新地板）

> 已废弃，禁止按本清单整批搬 Python 文件。正式资产政策见
> `docs/superpowers/specs/2026-08-06-xiaoro-clean-growth-architecture-design.md`。
> 新口径为“资产迁入、纯内核封存、高价值逻辑拆后重生、旧实现参考”。

> 旧仓库 = `/Users/bytedance/Desktop/xiaoro-shopping-master`（你现在的工作区，不动它）
> 新地板 = 本副本，以远程可跑 demo 为底
> 原则：**只搬"数据 + typed 合同 + 新前端 + 测试"，agent/presenter/意图三套/freeze 脚手架一律不搬。**

---

## 🟢 A. 必搬（真资产，不可再生 / 已验证）

### A1. 审核数据（最高优先，命根子）
- [ ] `data/canonical/core_products_v1.jsonl`         (103 商品, sha 0ba95df8…)
- [ ] `data/canonical/core_products_v1_manifest.json` (三方 sha 对齐)
- [ ] `.tmp_user_download_audit/shadow_review_v1/review_decisions.jsonl` (1234 决策, sha 12b0e1f8…)
- [ ] `.tmp_user_download_audit/shadow_review_v1/review_decisions_manifest.json`
- 说明：搬进来后，运行时路径要从 `.tmp_...` 收编到 `data/`（旧代码这里是临时路径依赖，是个已知债）。

### A2. typed 决策合同（做对了的架构骨头 → domain/decision + domain/catalog）
- [ ] `app/services/v2/decision_contracts.py`
- [ ] `app/services/v2/decision_fields.py`
- [ ] `app/services/v2/candidate_evaluator.py`
- [ ] `app/services/v2/ranker.py`                  （稳定排序，已验证）
- [ ] `app/services/v2/retrieval_constraint_policy.py`
- [ ] `app/services/v2/budget_constraint_parser.py`
- [ ] `app/services/v2/numeric_boundaries.py`

### A3. 字段授权 / canonical 读取（→ domain/catalog + infrastructure）
- [ ] `app/services/v2/facet_registry.py`
- [ ] `app/services/v2/product_facets.py`
- [ ] `app/services/v2/canonical_product_reader.py`
- [ ] `app/services/v2/canonical_consumer_adapters.py`
- [ ] `app/services/v2/shadow_evidence/`（整个目录，审核数据的生产工厂）
- [ ] 各 `*_facets.py`（claim/safety/texture/usage/mechanism/ingredient_*/qa_review）—— 按需

### A4. 新版前端（你改过的，比远程新）
- [ ] `app/static/chat.html`   (本地 6527 行 > 远程 5846 行)
- [ ] `app/api/v1/chat.py`      (本地 731 行 > 远程 321 行)
- 说明：这两个直接覆盖副本里的旧版。

### A5. 测试（59687 行验证，别丢）
- [ ] `tests/` 里针对 canonical / decision / ranker / facet 的测试文件
- 说明：搬 A2/A3 时，对应测试一起搬，保住验证。

---

## 🟡 B. 不搬，重写（思路有价值，形态错了 —— 在新地板按六层重写）

- `app/services/v2/agent.py`         (4957 行 God Object) → 拆成 application/ 编排
- `app/services/v2/presenter.py`     (6633 行) → 拆成 response/ + presentation/
- `app/services/v2/followup_*.py`    (十几个碎片) → 收敛进 domain/intent 的 followup 解析
- `app/services/v2/turn_parser.py` + `intent_classifier.py` → 重写为 intent/（代码槽位 + 大模型意图）
- 旧 `app/services/agent.py` / `intent.py` / `decision*.py`（V1）→ 不搬

## 🔴 C. 不搬，丢弃（垃圾 / 无关脚手架）

- `0`、`0,`（空文件）
- `app/services/v2/semantic_intent_retriever.py`（字面 n-gram 伪语义层，已定性砍掉）
- `app/services/v2/semantic_embedding_intent.py`（在线 embedding，一期不用；三期再议）
- `app/services/v2/v1_freeze_contract.py`（3865 行 freeze 审计脚手架，与导购无关）
- 各种 `docs/audits/overnight-*.md`、`.trae/specs/execute-root-cause-repair-program/`（Ralph 过程产物）

---

## 搬运顺序（等你点头，一步步来，不一次全搬）

1. A1 数据 → 先搬命根子，验 sha 一致
2. A4 前端 → 覆盖旧 demo 前端，确认能起
3. A2+A3+A5 → typed 合同 + 测试，跑测试确认绿
4. B → 按六层逐层重写（这是主要工作量）
5. C → 全程不碰，留旧仓库里当参考
