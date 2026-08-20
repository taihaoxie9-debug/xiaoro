# 重建架构骨架（对齐飞书文档 revision 34）

> 已废弃，禁止作为实施依据。正式架构见
> `docs/superpowers/specs/2026-08-06-xiaoro-clean-growth-architecture-design.md`。
> 本草案缺少反馈层、轻问诊和多图合同，并错误地把 LLM 限制为只输出意图枚举。

> 事实源：飞书文档《基于 RAG 的多模态电商导购 Agent 方案设计》第 4/5/13 章。
> 核心纪律：**六层解耦，Agent 只做编排，商品事实只来自结构化数据。**

## 目标六层（文档 4.1）

```
用户输入（文本 / 图片）
  ↓
[1] 多模态理解层    intent/  —— 文本槽位(代码) + 图片理解(CLIP/OCR)
  ↓
[2] 意图识别与拆解   intent/  —— 意图分类(大模型) + 槽位(代码字段)
  ↓
[3] RAG 多路召回     catalog/ —— 商品库/内容库/知识库/记忆库
  ↓
[4] Agent 决策       decision/—— 过滤(CandidateEvaluator) + 排序(Ranker) → DecisionResult
  ↓
[5] 结果展示         response/ + presentation/ —— ResponsePlan 决定结构，Renderer 只渲染
  ↓
[6] 数据反馈与优化   infrastructure/ —— 采集点击/加购/反馈
```

## 层职责铁律

| 层 | 目录 | 只能做 | 绝不能做 |
|---|---|---|---|
| 意图 | `domain/intent` | 槽位=代码字段；意图分类=大模型(5选1) | 碰商品事实、编字段 |
| 决策 | `domain/decision` | CandidateEvaluator 过滤 + Ranker 排序 → 唯一 DecisionResult | 读 raw 描述/评论/营销词 |
| 商品 | `domain/catalog` | 只从 canonical 读事实；未知ID fail-closed | 把 raw DB 字段当事实 |
| 响应 | `domain/response` | ResponsePlan 决定 sections/事件 | 选品、改排序、判兼容 |
| 编排 | `application` | 串 parse→retrieve→decide→plan→present | 实现评分/过滤/词表 |
| 基建 | `infrastructure` | Repository/canonical reader/向量/LLM | 业务判断 |
| 展示 | `presentation` | 把 DecisionResult+ResponsePlan 渲染成文本/SSE | 选品、判断 winner |

## 意图层分工（对齐用户已确认的结论）

- **槽位（预算/肤质/成分/指代）** → 代码 + 字段（正则+枚举）。抗改写、可解释。
- **意图分类（5-6类）** → 大模型。唯一能扛"无限说法"的东西。
- **模型也拿不准** → 追问 1~2 句（文档 5.2.4）。
- **向量** → 只用于 catalog 商品召回，**不用于意图判断**。
- **砍掉** → `semantic_intent_retriever` 那个字面 n-gram 伪语义层。

## 一期范围（文档 8.1 / 11.0，先做这些）

文本导购 / 图片找相似 / 图文联合筛选 / 商品对比 / 一轮追问。
**先不做**：重视频、超复杂搭配、全自动长期记忆、过深 Agent 自主规划。

## 三期终态（文档 8.3，架构留接口，暂不实现）

视频找同款 / 整套 Look / 达人内容 / 实时反馈学习。
—— 目标是"加一个服务就能插上"，不是现在写。
