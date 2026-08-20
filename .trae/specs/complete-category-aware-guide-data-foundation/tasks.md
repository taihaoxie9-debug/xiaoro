# Tasks

- [x] Task 1: 冻结 Phase 3A 基线与审计身份
  - [x] SubTask 1.1: 核验 `rebuild@a29d727`、工作区干净和 focused 52 项通过
  - [x] SubTask 1.2: 冻结保护路径树和排序 SHA
  - [x] SubTask 1.3: 记录 opening audit 的 2 个 P1、1 个 P2 和证据路径
  - [x] SubTask 1.4: 创建 category-data 审计 ledger 和 progress

- [x] Task 2: 建立六个严格品类画像
  - [x] SubTask 2.1: 新增 CategoryProfile 严格枚举
  - [x] SubTask 2.2: 将 39 种 Canonical 原始品类完整唯一映射
  - [x] SubTask 2.3: 未知新品类 fail-closed，不默认 skincare
  - [x] SubTask 2.4: 保持现有 sunscreen/serum taxonomy 行为兼容

- [x] Task 3: 建立分品类字段和 capability 合同
  - [x] SubTask 3.1: 定义通用字段与六类专属字段
  - [x] SubTask 3.2: 定义字段 value type、适用画像、来源优先级
  - [x] SubTask 3.3: 定义 evidence/display/compare/hard_filter/soft_rank
  - [x] SubTask 3.4: 未授权来源只能 evidence 或 quarantine
  - [x] SubTask 3.5: unknown/conflict/not_applicable 不产生 winner 或分数

- [x] Task 4: 扩展六类理解和任务规划
  - [x] SubTask 4.1: 扩展 TopicCode 和最长别名优先解析
  - [x] SubTask 4.2: 精华水/眼部精华归 skincare，不误归 serum
  - [x] SubTask 4.3: 底妆、彩妆、洁面、香水进入 Guide task plan
  - [x] SubTask 4.4: 现有修护精华功效门保持兼容
  - [x] SubTask 4.5: 澄清文案准确列出当前支持画像

- [x] Task 5: 实现批准品类事实资产 loader
  - [x] SubTask 5.1: 定义 ApprovedCategoryFact 和 manifest
  - [x] SubTask 5.2: 验证 hash、排序、唯一性、产品归属和字段适用性
  - [x] SubTask 5.3: 禁止绝对路径、raw HTML 和未批准候选进入生产资产
  - [x] SubTask 5.4: 完成重复、冲突、篡改和跨品类反例

- [x] Task 6: 实现品类事实 pending 候选构建
  - [x] SubTask 6.1: 接受 source manifest、HTML、OCR JSON 和结构化资料
  - [x] SubTask 6.2: 生成内容寻址 candidate ID
  - [x] SubTask 6.3: 执行字段专属 normalization、去重和 conflict 记录
  - [x] SubTask 6.4: 未授权来源进入 quarantine
  - [x] SubTask 6.5: 输入顺序不影响输出字节和 hash
  - [x] SubTask 6.6: 自动化输出不得包含 approved_fact

- [x] Task 7: 实现显式人工决定 promotion
  - [x] SubTask 7.1: 要求 reviewer、reviewed_at、decision 和 reason
  - [x] SubTask 7.2: 拒绝未知 candidate、重复决定和产品/画像错绑
  - [x] SubTask 7.3: 临时文件自校验后原子替换生产资产
  - [x] SubTask 7.4: promotion 失败保持旧资产字节不变

- [x] Task 8: 建立 12 个试点覆盖矩阵
  - [x] SubTask 8.1: 固定六画像各两个试点 ID
  - [x] SubTask 8.2: approved known 值必须有 source refs
  - [x] SubTask 8.3: 无批准来源字段保持 unknown
  - [x] SubTask 8.4: 输出每个画像 approved/unknown/conflict 统计
  - [x] SubTask 8.5: 重复构建资产和报告字节稳定
  - [x] SubTask 8.6: 没有新批准决定时允许 fact_count=0，且 reader 正常加载

- [x] Task 9: 将批准品类事实接入 Guide ports
  - [x] SubTask 9.1: 新增 CategoryFactPort 和严格 reader
  - [x] SubTask 9.2: Catalog 投影 category_profile 和 authorized facts
  - [x] SubTask 9.3: 决策只读 hard_filter/soft_rank safe 字段
  - [x] SubTask 9.4: 展示只读 display safe 字段
  - [x] SubTask 9.5: 比较只读 compare safe 且无冲突字段
  - [x] SubTask 9.6: 未批准 candidate 无法改变卡片和 winner

- [x] Task 10: 实现评论候选重建和原子 promotion
  - [x] SubTask 10.1: 从原始 HTML 重建 pending/quarantine 候选
  - [x] SubTask 10.2: 稳定 ID 继续绑定 item、完整 HTML hash 和 8 位 ordinal
  - [x] SubTask 10.3: PII、营销、Q&A 和跨 SKU 内容进入 quarantine
  - [x] SubTask 10.4: 只有显式人工决定可以进入批准资产
  - [x] SubTask 10.5: 原子生成 JSONL、manifest 和审计机器块
  - [x] SubTask 10.6: 用脱敏 fixture 复验构建确定性，并保持原 6 条批准来源
  - [x] SubTask 10.7: 原始 HTML 不可用时只记录历史 336/111，不声明本轮真实重跑

- [x] Task 11: 正式集成六类 HTTP/SSE/前端
  - [x] SubTask 11.1: runtime composition 锁定 category fact manifest
  - [x] SubTask 11.2: owner matrix 只扩展已通过浏览器的品类
  - [x] SubTask 11.3: 六类正式 SSE 保持单终态和 typed events
  - [x] SubTask 11.4: 六类商品卡严格使用后端 ID 和顺序
  - [x] SubTask 11.5: 前端只显示 typed category facts，不解析答案猜字段
  - [x] SubTask 11.6: Guide 内部错误不回退 legacy
  - [x] SubTask 11.7: 新增 category profile normal/adversarial 浏览器门禁

- [x] Task 12: 完成全量验证与最终审计
  - [x] SubTask 12.1: focused category/data/tooling 全绿
  - [x] SubTask 12.2: Guide full 和 runtime full 全绿
  - [x] SubTask 12.3: compileall、双 boundary 和 diff check 通过
  - [x] SubTask 12.4: 保护路径 diff 为 0，排序 SHA 不变
  - [x] SubTask 12.5: normal/adversarial/category/review/image/consultation 浏览器通过
  - [x] SubTask 12.6: 执行唯一 `FINAL-CATEGORY-DATA-AUDIT`
  - [x] SubTask 12.7: 确认 finding 先 RED 后单 writer 修复
  - [x] SubTask 12.8: 修复后重跑正常门禁，不重复 full-file audit

- [x] Task 13: 最终收口
  - [x] SubTask 13.1: 核对 39/39 映射和六画像字段矩阵
  - [x] SubTask 13.2: 核对 12 试点 approved/unknown/conflict 证据
  - [x] SubTask 13.3: 核对评论批准数量和重建证据
  - [x] SubTask 13.4: 完成 final handoff、audit ledger 和 progress
  - [x] SubTask 13.5: 确认 tasks/checklist 全勾选后才标记 COMPLETE
  - [x] SubTask 13.6: 确认工作区干净
  - [x] SubTask 13.7: 确认未 push、未部署、未切流

- [x] Task 14: 绑定候选解析与已校验来源字节: 修复 source hash 校验后再次按路径读取形成的竞态，确保候选内容只能来自计算 `source_sha256` 的同一份字节；增加源文件在校验后被替换的 RED/GREEN。

- [x] Task 15: 补齐品类事实 promotion 的提交后故障原子性: 注入 manifest swap 后目录 fsync 失败时，不得以失败返回同时改变生产 manifest；增加旧资产字节保持不变的 RED/GREEN。

- [x] Task 16: 修复带修饰语的并列品类否定: `不考虑防晒以及平价香水` 等表达不得恢复后一个已被否定的品类或路由到该品类推荐；补充理解、task planning 和正式路由回归。

- [x] Task 17: 非法品类 payload 必须在状态提交前拒绝: typed category payload 校验失败时，不得推进 conversation version 或写入 feedback target；补充浏览器级状态不变断言。

- [x] Task 18: 保持追问、修订和图片卡片的品类事实展示: 所有携带 category facts 的正式卡片响应必须提供可校验画像，前端不得因 intent 缺少 category_profile 静默跳过品类事实；补充真实追问/修订/图片浏览器回归。

- [x] Task 19: 修复并列连接词后的显式正向转折: `不考虑防晒以及后来还是想买高端香水` 应恢复 fragrance 正向意图，同时保留 `不考虑防晒以及平价香水` 的双重否定；补充 understanding、task planning 和 formal route RED/GREEN。

- [x] Task 20: 延迟 PublicEventCommitConversationState 到已验证终态真正交付: 正式 runtime SSE consumer 取得 start 后取消或断连时不得持久化 conversation state；合法完整消费只提交一次，conversation version 与 feedback target 必须来自同一次已交付终态且不得分叉；覆盖 threadpool/iterator close 的真实运行路径，不能只修测试替身。

- [x] Task 21: 扩展连接词后的明确正向转折: 至少覆盖 `后来还是要买`、`后来还是想要`、`我后来还是想买`、`后来改买`，同时保持 `不考虑防晒以及平价香水` 的双重否定；补充 understanding、task planning 和 formal route RED/GREEN。

- [x] Task 22: 对 products payload 执行整体 typed 等价校验: public products 必须与 typed ProductCard 的确定性完整投影一致，不得引入重复宽松模型；`name`、`price`、`image_url` 等字段的畸形类型必须在事件通过或 conversation state 提交前被拒绝。

- [x] Task 23: 补齐常见并列连接词的品类否定传播: `不考虑防晒并且平价香水`、`不考虑防晒并平价香水`、`不考虑防晒且平价香水` 不得恢复 fragrance 或进入 Guide 推荐；补充 understanding、task planning 和正式 HTTP/SSE RED/GREEN。

- [x] Task 24: 补齐唯一最终审计遗漏的真实 review reader: 将错误的 `app/guide/retrieval/review_evidence_reader.py` 路径更正为运行时实际使用的 `app/guide/retrieval/review_reader.py`，冻结其 blob，并由独立只读审计员完成定向核验；不得重复同 key full-file audit。

- [x] Task 25: 防止新增连接词过度否定明确正向谓词: `不考虑防晒并想买平价香水`、`不考虑防晒并推荐平价香水`、`不考虑防晒且想买平价香水`、`不考虑防晒并且推荐平价香水` 必须恢复 fragrance 正向意图并进入 Guide；补充 understanding、task planning 和正式 HTTP/SSE RED/GREEN，同时保持 Task 23 的纯并列否定语义。

- [x] Task 26: 强化并列连接词后的正向谓词边界: 直接 `想买`、`想要`、`要买`、`推荐`、`改买` 应恢复后一个品类的正向意图；`并不想买`、`并非要买`、`想要避开的香水`、`推荐避雷香水`、`想买但不买香水` 等显式否定不得恢复；最终修订 `不考虑防晒并改买香水但不要香水` 必须以最后否定为准；补充 understanding、task planning 和正式 HTTP/SSE RED/GREEN。

- [x] Task 27: 实现 scope-aware category negation，严格区分属性排除与品类否定: `避开甜腻的香水`、`不要太甜的香水`、`不想要太甜的香水` 必须保留 fragrance 正向品类；`想要避开的香水`、`推荐避雷香水`、`想买但不买香水` 不得恢复 fragrance；`推荐防晒但不推荐防晒` 与 `不考虑防晒并改买香水但最后不推荐香水` 必须以最后品类否定为准；补充 understanding、task planning、owner 以及正式 `/api/v1/chat/message` 和 `/api/v1/chat/stream` 代表性正负矩阵 RED/GREEN。

- [x] Task 28: 区分品类量词/指类词与属性作用域: `不要所有的香水`、`避开全部的香水`、`排除这类的香水`、`拒绝这种香水` 必须保持 fragrance 品类否定且不得进入 Guide，同时 Task 27 的 `避开甜腻的香水`、`不要太甜的香水`、`不想要太甜的香水` 仍保留 fragrance 正向品类；补充 understanding、task planning 和 owner routing RED/GREEN，并将 Task 28 用例纳入稍后统一执行的正式 `/api/v1/chat/message` + `/api/v1/chat/stream` 矩阵。

- [x] Task 29: 扩展品类量词同义词并防止属性排除约束静默丢失: `任意的`、`任何的`、`每一种的`、`每一款的`、`一切的` 在 `不要`、`避开`、`排除`、`拒绝` 下必须与 Task 28 既有量词统一，保持 fragrance 品类否定且不得进入 Guide；Task 27 恢复属性排除路由后，`避开甜腻的香水`、`不想要太甜的香水` 必须在现有授权的结构化约束合同中保留排除语义，若当前合同不支持该属性则必须产生明确 uncertainty/clarification，不得假装约束已应用；补充 understanding、task planning 和 owner routing RED/GREEN，并为正式 `/api/v1/chat/message` 与 `/api/v1/chat/stream` 增加 typed evidence。

- [x] Task 30: 禁止 category/unsupported-attribute 已消费文本 span 被 `_parse_exclusions` 二次消费: `避开不含酒精的香水`、`不要不含酒精的香水`、`不想要不含酒精的香水` 及同类无添加属性表达不得反向生成 `ExclusionDraft`/`ExclusionConstraint("酒精")`，并保持 Task 29 的 typed uncertainty/clarification；`不要所有香水` 及 Task 29 品类量词矩阵不得生成 `ExclusionDraft`/`ExclusionConstraint("所有")` 等非领域约束；正常成分排除 `不要含酒精的香水` 仍必须生成酒精 exclusion；补充 understanding、task planning 和 owner routing RED/GREEN，并为正式 `/api/v1/chat/message` 与 `/api/v1/chat/stream` 增加上述三类代表矩阵。

- [x] Task 31: 归一化普通成分排除中的存在谓词: `不要有酒精的香水`、`不要有香精的香水` 必须分别生成准确的 `ExclusionDraft("酒精")`/`ExclusionConstraint("酒精")` 和 `ExclusionDraft("香精")`/`ExclusionConstraint("香精")`，不得保留前导 `有` 或生成 `"有酒精"`/`"有香精"`；参数化回归 `不要含`、`不含`、`不能有`、`无` 四类表达；补充 understanding、task planning、owner routing 和 decision consumer RED/GREEN，证明含目标成分的候选命中 `excluded_exclusion_match` 而非 `excluded_evidence_unknown`，并为正式 `/api/v1/chat/message` 与 `/api/v1/chat/stream` 增加代表性验证。

- [x] Task 32: 阻止外层排除前缀绕过 consumed-span 并反向生成成分排除: 对 `{避开, 不要, 不想要, 排除, 拒绝, 不要有}` × `{不含, 无}` × `{酒精, 香精}` × 明确品类（至少覆盖 `香水`）的完整笛卡尔矩阵，均须保留品类和 `unsupported_attribute_exclusion` typed uncertainty，进入 clarify，且不得生成任何 `ExclusionDraft`/`ExclusionConstraint`；普通 `{不要有, 不要含, 不含, 不能有, 无}` × `{酒精, 香精}` × 明确品类仍须生成裸成分值的准确排除并保持 decision hard exclusion。补充 understanding、task planning、owner routing、decision consumer 的 RED/GREEN，并在正式 `/api/v1/chat/message` 与 `/api/v1/chat/stream` 增加覆盖各维度的 typed 代表用例。

# Task Dependencies

- Task 1 是全部任务的前置条件。
- Task 2 和 Task 3 在 Task 1 后并行。
- Task 4 依赖 Task 2。
- Task 5、Task 6、Task 10 可在 Task 3 合同冻结后并行。
- Task 7 依赖 Task 5 和 Task 6。
- Task 8 依赖 Task 7；没有批准事实时以 unknown 诚实完成。
- Task 9 依赖 Task 3、Task 5 和 Task 8。
- Task 11 依赖 Task 4、Task 9 和 Task 10。
- Task 12 依赖 Task 2–11 全部集成。
- Task 13 依赖 Task 12 通过。
- Task 19 依赖 Task 16。
- Round 5 最终验证依赖 Task 14–19 全部通过。
- Task 20 依赖 Task 17。
- Task 21 依赖 Task 16 和 Task 19。
- Task 22 依赖 Task 17。
- Round 6 最终验证依赖 Task 20–22 全部通过。
- Task 25 依赖 Task 23。
- Round 9 最终验证依赖 Task 23 和 Task 25 全部通过。
- Task 26 依赖 Task 25。
- Task 27 依赖 Task 26。
- Task 28 依赖 Task 27。
- Task 29 依赖 Task 28。
- Task 30 依赖 Task 29。
- Task 31 依赖 Task 30。
- Task 32 依赖 Task 31。
