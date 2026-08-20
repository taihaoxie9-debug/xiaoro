# Progress

## 2026-08-12 恢复基线 checkpoint

- **证据边界**：本 checkpoint 只采用当前 Git 主线、`tasks.md`、
  `checklist.md`、`docs/audits/guide-closure/audit_ledger.csv`、冻结
  baseline manifest、已保存 RED 和当前只读 hash 复算；历史 Agent 自报不作为
  权威 verifier 结果。本轮未执行正式审计。
- **主线**：`rebuild` HEAD 为
  `b20a714c0bde21bd500228b94bcb67c79f5c52fe`。Tasks 1–5、7、9、10
  完成；Task 6.1–6.4 完成。Task 6.5–6.7 和 Tasks 8、11、12、13
  未完成，整体状态保持 INCOMPLETE。
- **唯一正式审计**：固定 profile 为 `guide-closure-full-file-v1`，固定 audit
  key 为
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`。
  append-only ledger 只有该 key 的一条记录，`real_invocations=1`；未创建新
  audit key。
- **Task 6 RED 与候选边界**：现有 RED 记录 128 个冻结 case 中 21 个 case
  的 semantic port 调用为 0；该证据同时记录了空 conversation snapshot 和
  evaluator 将独立预计算 merger/TaskPlan 与顶层 stream 混合，故这 21 个 case
  仍需按闭合 operation proof、普通语义和不可信 gate 状态分类，不能全部定性为
  生产缺陷。`guide-task6-real-gate` 候选
  `e3e123a3199c0366b322762a2ebafc7dfaa4e600` 以主线 `b20a714` 为
  merge-base、领先 4 个提交，且不是当前 HEAD 的祖先，因此尚未集成；本
  checkpoint 不声明该候选 PASS。
- **Key 状态**：主线程已证 `GUIDE_LLM_API_KEY=MISSING`；本 checkpoint
  未读取、打印或搜索 Key 值。真实双模型 A/B 仍被 fresh Key 阻塞。
- **保护资产 hash**：当前只读复算与冻结值一致：Canonical 103 商品 aggregate
  `ef446aede0dcc0e92be1c8a1ff922154611eb0e11474e5e26d5dc57f2c768d0f`；
  6 条批准评论 aggregate
  `4a370d27e64d1affa49c03c2ebc21d51f652cdca162626a75249dafc8ce438b7`；
  category facts `fact_count=0` aggregate
  `1a3640fe3c40337a5c87bb405a6e6116ae2fd77935ca86b3bf7f5d9e3dfff53c`；
  deterministic ranking SHA-256
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`。
- **发布状态**：本恢复 checkpoint 未 push、未 deploy、未切换生产流量；
  baseline manifest 的 `push_deploy_traffic_switch=false`。

## 2026-08-12 Task 6.4a-c 集成 checkpoint（非最终 Round summary）

- **逐提交集成**：从 clean 主线 `cf77738d33f7442072f00e1f01403dcd84796300`
  按 direct-parent 顺序零冲突 cherry-pick：
  `fdc19334663b4ea6605c39e9b4ad5f8cb4d09090` ->
  `de8215f6551d1e93f998bf4f835679ff777f0443`，
  `f39d252659085978fe12367508d3cfb478a6fa9e` ->
  `0b6a8522d779f924eb8fc3c9d188498f27869b77`，
  `59330657f22550c5775ba263ed11c64da981f555` ->
  `7a42012d05677331dafc1bbdd39e9412488f6eb0`。集成 HEAD 与冻结
  `5933065` 的 Git tree 和三个 stable patch ID 逐一一致。
- **唯一权威 verifier**：
  `/tmp/xiaoro-task6-e2e-v2-verifier-5933065/report.md` 对冻结
  `59330657f22550c5775ba263ed11c64da981f555` 判定 PASS，
  `P0/P1/P2=0`。权威冻结证据为 Guide full `6905 passed`（1 warning）、
  runtime full `217 passed`、focused `3810 passed`；本主线未重复这些长全量。
- **路由证据**：model vertical 与 production routing 已按模块、入口和测试分离；
  可信 SQLite snapshot 通过真实 `TextRecommendationOrchestrator.stream`
  验证 `14/14` 普通开放语义恰好调用一次 semantic，先前错误卡片的 `7/7`
  case 均闭合且无 selection，model vertical 的 `128/128` 冻结 proposal
  均恰好消费一次。
- **主线最小门禁**：Task 6/production targeted smoke 为 `93 passed`；
  architecture + runtime import 双 boundary 在完整本地 verifier 环境为
  `25 passed`；`compileall(app, tools, tests/guide)`、`app.guide`
  boundary checker、range/worktree/index `git diff --check` 和保护路径
  range diff 均通过。预设 runtime venv 的 FastAPI 源文件缺失导致首次 runtime
  import boundary 环境失败，隔离重跑通过，未因此修改仓库代码。
- **保护资产**：Canonical aggregate
  `ef446aede0dcc0e92be1c8a1ff922154611eb0e11474e5e26d5dc57f2c768d0f`
  （103 商品）；6 条批准评论 aggregate
  `4a370d27e64d1affa49c03c2ebc21d51f652cdca162626a75249dafc8ce438b7`；
  category facts aggregate
  `1a3640fe3c40337a5c87bb405a6e6116ae2fd77935ca86b3bf7f5d9e3dfff53c`
  （`fact_count=0`）；deterministic ranking
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`，
  均与冻结 manifest 一致。
- **审计、Key 与发布边界**：正式 full-file audit 调用总数仍为 `1`，本轮未调用
  正式审计、未创建新 audit key；未读取、打印或搜索 `GUIDE_LLM_API_KEY`。
  Task 6 主项及 6.5–6.7 保持未完成，真实双模型 A/B 和 hard gates 未宣称通过；
  未进入 Task 8，未 push、未 deploy、未切换生产流量。

## Round 4

- **Session summary**：本轮从恢复 checkpoint `cf77738` 继续；唯一权威
  verifier 对旧候选 `e3e123a` 给出 P1 拒绝，问题在最早失败责任层完成修复，
  提交映射为 `de8215f`、`0b6a852`、`7a42012`，最终 docs checkpoint 为
  `d9fa365`。
- **验证证据**：targeted、focused、Guide full、runtime full 分别为
  `93/3810/6905/217 passed`；production routing 普通开放语义 `14/14`、
  先前错误卡片闭合无 selection `7/7`、model vertical 冻结 proposal
  `128/128` 均通过，Task 6.4a-c 完成。
- **审计与保护资产**：唯一正式 audit invocation 仍为 `1`，无 repeat；
  Canonical、6 条批准评论、category facts 与 deterministic ranking 的保护
  hash 均与冻结值一致。
- **外部硬门**：Key 仅记录状态 `MISSING`，未读取、打印、搜索或记录真实值；
  真实 V4-Flash/V3.2 A/B 是当前唯一外部硬门。
- **顺序与发布边界**：Task 8、11、12、13 均未提前进入；本轮未 push、未
  deploy、未切换生产流量。

## Round 5

- **恢复与冻结**：已恢复并完整读取权威文档；冻结 SHA 为
  `3553cfdab9987bd36a85c4ff6f78bcf2d47103fd`。编辑前 worktree clean，
  且当前提交是 `b20a714c0bde21bd500228b94bcb67c79f5c52fe` 的合法后继。
- **唯一权威 verifier**：冻结 SHA 的定向验证结果为
  `55 passed in 20.59s`，本轮未重复运行测试。
- **审计纪律**：固定 audit key 为
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`；
  `invocation=1`、`repeat=0`，本轮未执行正式 full-file audit。
- **Key 与外部硬门**：`GUIDE_LLM_API_KEY` 只记录 `MISSING`；真实
  V4-Flash/V3.2 A/B 是进入 Task 8 的唯一前置，当前无非 Key 可行动缺口。
- **顺序与发布边界**：未提前进入 Task 8；本轮未 push、未 deploy、未切换
  生产流量。
- **本轮变更范围**：仅变更 `progress.md`，未修改 `tasks.md` 或
  `checklist.md`。

## Round 6

- **冻结与 provenance**：冻结 SHA 为
  `40f61e04bdce703df43726b11a9c9f37c56b4bc3`；唯一 authoritative
  read-only verifier 对该 SHA 的 provenance 核对 PASS：分支为 `rebuild`、
  worktree clean，且 `b20a714c0bde21bd500228b94bcb67c79f5c52fe`
  是其祖先。
- **漂移核对**：`3553cfd..HEAD` 只有一个 `progress.md` 状态提交，无代码、
  `tasks.md`、`checklist.md` 或 audit ledger 漂移。
- **审计纪律**：audit key 固定为
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`；
  `formal invocation=1`、`repeat=0`，无新 audit key。
- **Key 边界**：`GUIDE_LLM_API_KEY` 仅记录 `MISSING`，未读取、打印或搜索
  其值。
- **任务顺序**：Task 6.5–6.7 是 Task 8 的唯一前置，且当前无非 Key 可行动
  缺口，因此未进入 Task 8。真实任务未完成，故未修改 `tasks.md` 或
  `checklist.md`。
- **测试与发布边界**：本轮未运行 `pytest` 或长测试；未 push、未 deploy、
  未切换生产流量。

## Round 7

- **冻结与权威核验**：冻结 SHA 为
  `44acdcf138327cde281b858102d39358818b3c36`；authoritative verifier
  判定 PASS：编辑前 worktree clean，且 `b20a714` 是其祖先。
- **漂移与审计**：`40f61e0..44acdcf` 仅有 `progress.md` 漂移；audit key
  固定为 `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`，
  `invocation=1`、`repeat=0`。
- **唯一阻塞与任务顺序**：`GUIDE_LLM_API_KEY=MISSING`；Task 6.5–6.7
  是 Task 8 的唯一前置，Tasks 8、11、12、13 均未提前进入，当前无其他不依赖
  Key 的行动项。
- **旧 Agent 状态处置**：旧 Agent 状态看似 running，但系统 close 返回
  `no agent found`；进程检查未发现 `pytest` 或长测试。该现象仅按旧 Agent
  状态残留记录，不定性为代码问题。
- **测试与发布边界**：本轮未运行 `pytest` 或长测试；未 push、未 deploy、
  未切换生产流量。

## Round 8

- **冻结与权威核验**：authoritative verifier 针对
  `34b8a6d60054412905e4afa98fe8cfcc2e547fb1` 判定 PASS；`rebuild`
  worktree clean，且 `b20a714` 是其祖先。
- **审计纪律**：audit key 固定为
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`；
  `invocation=1`、`repeat=0`。
- **唯一阻塞**：`GUIDE_LLM_API_KEY=MISSING`，仅记录状态、未读取值；
  Task 6.5–6.7 是 Task 8 唯一未满足前置，无其他不依赖 Key 的缺口。
- **执行边界**：本轮未运行 `pytest`、browser 或 network；进程中无
  `pytest`、`playwright` 或 `uvicorn`；未进入 Tasks 8、11、12、13。
- **发布边界**：本轮未 push、未 deploy、未切换生产流量。

## Round 9

- **冻结与权威核验**：authoritative verifier 针对冻结 SHA
  `4eb817067ecbabd049a20d8c62d52c65eb5b1420` 判定 PASS；`rebuild`
  worktree clean，且 `b20a714c0bde21bd500228b94bcb67c79f5c52fe`
  是其祖先。
- **审计纪律**：audit key 固定为
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`；
  `formal invocation=1`、`repeat=0`，本轮未执行正式 audit。
- **唯一阻塞与任务顺序**：`GUIDE_LLM_API_KEY=MISSING`，仅记录状态且禁止
  读取值；Task 6.5–6.7 和 Tasks 8、11、12、13 仍未完成，无其他不依赖
  Key 的行动缺口，未提前进入后续任务。
- **测试与进程边界**：本轮未运行长测试、browser 或 network；权威核验确认
  无 `pytest`、`playwright` 或 `uvicorn` 长任务。
- **发布边界**：本轮未 push、未 deploy、未切换生产流量。

## Round 10

- **冻结与权威核验**：authoritative verifier 针对冻结 SHA
  `b43056ef2d04c85e161b8111dfc832dfde602d3a` 判定 PASS；`rebuild`
  worktree clean，且 `b20a714c0bde21bd500228b94bcb67c79f5c52fe`
  是其祖先。
- **审计纪律**：audit key 固定为
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`；
  `formal invocation=1`、`repeat=0`，本轮无新 audit。
- **唯一阻塞**：`GUIDE_LLM_API_KEY=MISSING`，仅记录状态、未读取值；
  Task 6.5–6.7 是 Task 8 的唯一未满足前置，无其他非 Key 行动项。
- **测试与进程边界**：无 `pytest`、`playwright`、`uvicorn` 或 A/B
  遗留进程；本轮未运行长测试、browser 或 network。
- **任务与发布边界**：未进入 Tasks 8、11、12、13；未 push、未 deploy、
  未切换生产流量。
- **本轮变更范围**：文件变更只有 `progress.md`。

## Round 11

- **冻结与权威核验**：authoritative verifier 对冻结 SHA
  `8753092b8fab694c3a0218a29e60ec2c1ddb7855` 判定 PASS；`rebuild`
  worktree clean，且 `b20a714` 是其祖先。
- **漂移范围**：`b43056e..8753092` 仅有 `progress.md` 的 Round 10 漂移。
- **审计纪律**：audit key 固定为
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`；
  `formal invocation=1`、`repeat=0`，本轮未执行正式 audit。
- **Key 边界**：`GUIDE_LLM_API_KEY=MISSING`，本轮只检查状态，未读取或打印值。
- **进程与执行边界**：无 `pytest`、`playwright`、`uvicorn` 或
  `intent_model_ab` 遗留进程；本轮未运行 `pytest`、browser 或 network。
- **唯一阻塞与续跑点**：Task 6.5–6.7 是 Task 8 唯一未满足前置，没有其他
  Key 无关行动项。为避免无意义长等待，连续外部阻塞达到阈值后停止空转；
  Key 恢复后从 Task 6.5 继续。
- **发布边界**：本轮未 push、未 deploy、未切换生产流量。

## Round 12

- **冻结与权威核验**：authoritative verifier 对冻结 SHA
  `6552eee6a1d402108bcc0c4793550c770a5d35eb` 判定 PASS；分支为
  `rebuild`、编辑前 worktree clean，且 `b20a714` 是其祖先。
- **审计纪律**：audit key 固定为
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`；
  `formal invocation=1`、`repeat=0`，本轮未执行正式 audit。
- **Key 与进程边界**：`GUIDE_LLM_API_KEY=MISSING`，本轮只检查状态；
  无 `pytest`、`playwright`、`uvicorn` 或 `intent_model_ab` 遗留进程。
- **唯一前置与任务顺序**：真实 V4-Flash/V3.2 A/B 是唯一前置，当前未进入
  Tasks 8、11、12、13。
- **有界续跑规则**：本轮已读取 A/B 有界方案；未来长任务必须每 30 秒发送
  心跳并设置进程级硬超时，超时后依次 TERM/KILL，再复核相关进程已退出。
- **执行与发布边界**：本轮未运行测试、network 或 browser；未 push、未
  deploy、未切换生产流量。

## Round 13

- **冻结与权威核验**：authoritative verifier 对冻结 SHA
  `0e45b636f5d9206d734a332ba6df16ab05c63951` 判定 PASS；分支为
  `rebuild`、编辑前 worktree clean，且 `b20a714` 是其祖先。
- **审计纪律**：audit key 固定为
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`；
  `formal invocation=1`、`repeat=0`，本轮未执行正式 audit。
- **Key 与进程边界**：`GUIDE_LLM_API_KEY=MISSING`，仅检查并记录状态；
  无 `pytest`、`playwright`、`uvicorn` 或 `intent_model_ab` 遗留进程。
- **唯一阻塞与任务顺序**：Task 6.5–6.7 因 Key 阻塞，并依赖性阻塞
  Tasks 8、11、12、13；当前无其他 Key 无关行动项。
- **有界续跑规则**：为避免卡顿，本轮未运行测试、network 或 browser；
  未来长任务每 30 秒发送心跳并设置进程级硬超时，超时后依次 TERM/KILL，
  再复核相关进程已退出。
- **发布边界**：本轮未 push、未 deploy、未切换生产流量。

## Round 14

- **冻结与权威核验**：冻结 SHA 为
  `0d407be751573e619d0331fea1e740eee0bc4a6d`；authoritative verifier
  判定 PASS，分支为 `rebuild`、worktree clean，且 `b20a714` 是其祖先。
- **漂移范围**：`0e45b636..HEAD` 仅包含上一轮 `progress.md` 状态提交。
- **审计纪律**：audit key 固定为
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`；
  `formal invocation=1`、`repeat=0`，本轮未执行 formal audit。
- **Key 与进程边界**：`GUIDE_LLM_API_KEY=MISSING`，本轮仅检查状态；
  无 `pytest`、`playwright`、`uvicorn` 或 `intent_model_ab` 遗留进程。
- **唯一前置与任务顺序**：Task 6.5–6.7 是唯一前置，当前没有其他 Key
  无关行动项；未进入 Tasks 8、11、12、13。
- **执行与续跑边界**：本轮未运行测试、network 或 browser；未来 A/B
  使用每 30 秒心跳和进程级硬超时，超时后依次 TERM/KILL，并复核相关进程
  已退出。
- **发布边界**：本轮未 push、未 deploy、未切换生产流量。

## Round 15

- **冻结与权威核验**：authoritative verifier 对冻结 SHA
  `0f5688718edef1ee67eaaa251a7d5b3c21c0bec2` 判定 PASS；分支为
  `rebuild`、编辑前 worktree clean，且 `b20a714` 是其祖先。
- **漂移与审计纪律**：`0d407be..HEAD` 仅有 `progress.md` 漂移；audit key
  固定为 `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`，
  `invocation=1`、`repeat=0`，无新 audit key，未执行正式 audit。
- **Key、进程与唯一前置**：`GUIDE_LLM_API_KEY=MISSING`，未读取或打印值；
  无 `pytest`、`playwright`、`uvicorn` 或 `intent_model_ab` 遗留进程。
  Task 6.5–6.7 仍是 Task 8 的唯一前置，无其他非 Key 行动项。
- **执行与续跑边界**：本轮未运行测试、network、browser 或 A/B；未来长任务
  每 30 秒发送心跳并设置进程级硬超时，超时后依次 TERM/KILL，并复核相关
  进程已退出。
- **任务与发布边界**：未进入 Tasks 8、11、12、13；未 push、未 deploy、
  未切换生产流量。

## Round 16

- **冻结与权威核验**：authoritative read-only verifier 对冻结 SHA
  `ee90076c7a3d27a4330f1c94a1af56da80f412b9` 判定 PASS；分支为
  `rebuild`、编辑前 worktree clean，且 `b20a714` 是其祖先。
- **漂移与唯一审计纪律**：上一提交到当前仅有 `progress.md` 漂移；audit key
  固定为 `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`，
  `formal invocation=1`、`repeat=0`，本轮未执行 formal audit，未创建新
  audit key。
- **Key 与进程边界**：`GUIDE_LLM_API_KEY=MISSING`，未读取或打印值；无
  `pytest`、`playwright`、`uvicorn` 或 `intent_model_ab` 遗留进程。
- **唯一阻塞与任务顺序**：Task 6.5–6.7 是 Task 8 的唯一未满足前置，当前
  无非 Key 可行动缺口；未提前进入 Tasks 8、11、12、13，未修改
  `tasks.md` 或 `checklist.md`。
- **执行与有界续跑规则**：本轮未运行测试、browser、network 或 A/B；Key
  恢复后从 Task 6.5 继续，长任务每 30 秒发送心跳并设置进程级硬超时，
  超时后依次 TERM/KILL，再复核相关进程已退出。
- **发布边界**：本轮未 push、未 deploy、未切换生产流量。

## Round 17

- **Session summary**：唯一 authoritative read-only verifier 对冻结 SHA
  `39871930588a820a94219509354d09694f0a3110` 判定 PASS；分支为
  `rebuild`、worktree clean，且 `b20a714` 是其祖先。
- **漂移与唯一审计纪律**：`3987193` 相比父提交仅有 `progress.md` 漂移；
  audit key 唯一且固定为
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`，
  `formal invocation=1`、`repeat=0`，本轮未执行 formal audit。
- **Key 与进程边界**：`GUIDE_LLM_API_KEY=MISSING`；无 `pytest`、
  `playwright`、`uvicorn` 或 `intent_model_ab` 遗留进程。
- **唯一阻塞与任务顺序**：Task 6.5–6.7 因 Key 阻塞；未提前进入
  Tasks 8、11、12、13，当前无其他非 Key 行动项。
- **执行与有界长任务规则**：本轮未运行测试、browser 或 network；未来长任务
  每 30 秒发送心跳并设置进程级硬超时，超时后依次 TERM/KILL，再复核相关
  进程已退出。
- **发布边界**：本轮未 push、未 deploy、未切换生产流量。

## Round 18

- **Session summary**：唯一 authoritative verifier 对冻结 SHA
  `6e93087e618bbd5b4f653acaf89c107d383a62fa` 判定 PASS；分支为
  `rebuild`、worktree clean，且 `b20a714` 是其祖先；HEAD 相比父提交仅有
  `progress.md` 漂移。
- **一致性与审计纪律**：独立 checklist consistency verifier 判定 PASS，无虚假
  勾选、无可提前勾选项，未完成项均由现有 Tasks 覆盖；audit key 固定为
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`，
  `formal invocation=1`、`repeat=0`，本轮未执行 formal audit。
- **Key、进程与 Agent 状态**：`GUIDE_LLM_API_KEY=MISSING`，未读取或打印值；
  无 `pytest`、`playwright`、`uvicorn` 或 `intent_model_ab` 遗留进程。跨轮
  显示的 6 个旧 running/pending Agent 中 1 个成功 close，其余 close 均返回
  `no agent found`；进程核验无长任务，判定为状态残留。
- **唯一阻塞与任务顺序**：Task 6.5–6.7 是唯一前置；未提前进入 Tasks 8、11、
  12、13，未修改 `tasks.md` 或 `checklist.md`。
- **执行与有界长任务规则**：本轮未运行测试、browser、network、A/B 或正式
  audit；Key 恢复后长任务每 30 秒发送心跳并设置进程级硬超时，超时后依次
  TERM/KILL，再复核相关进程已退出。
- **发布边界**：本轮未 push、未 deploy、未切换生产流量。

## Round 19

- **Session summary**：权威 verifier 对冻结 SHA
  `90c5f4a483e6a1148a643fa3a3ec3eb744927d21` 判定 PASS；工作区 clean，
  `b20a714c0bde21bd500228b94bcb67c79f5c52fe` 是其祖先，父提交为
  `6e93087e618bbd5b4f653acaf89c107d383a62fa`，HEAD 相比父提交的唯一变更
  是上一轮 `progress.md`。
- **唯一审计纪律**：固定 audit key 为
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`；
  `formal invocation=1`、`repeat=0`，无第二个 audit key，本轮未执行正式
  audit。
- **Key、进程与唯一阻塞**：`GUIDE_LLM_API_KEY=MISSING`，仅记录状态；无
  `pytest`、`playwright`、`uvicorn` 或 `intent_model_ab` 进程。
  Task 6.5–6.7 是 Task 8 唯一未满足前置，当前无其他非 Key 行动项。
- **执行与有界长任务规则**：本轮未运行测试、network、browser 或正式 audit；
  未来长任务须每 30 秒发送心跳并设置进程级硬超时，超时后依次 TERM/KILL，
  再复核相关进程已退出。
- **发布边界**：本轮未 push、未 deploy、未切换生产流量。

## Round 20

- **Session summary**：authoritative verifier 对冻结 SHA
  `5982ef584eb98efc3116291d881de98e49937260` 判定 PASS；分支为
  `rebuild`、worktree clean，且 `b20a714` 是其祖先；HEAD 相对父提交只有
  上一轮 `progress.md` 漂移。
- **唯一审计纪律**：固定 audit key 为
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`；
  `formal invocation=1`、`repeat=0`，本轮未执行 audit。
- **Key 与进程边界**：`GUIDE_LLM_API_KEY=MISSING`，且未读取值；无
  `pytest`、`playwright`、`uvicorn` 或 `intent_model_ab` 残留进程。
- **唯一阻塞与任务顺序**：Task 6.5-6.7 是 Task 8 唯一前置，当前无其他非
  Key 行动项；未进入 Tasks 8、11、12、13。
- **执行与未来 A/B 规则**：本轮未运行测试、network 或 browser；未来 A/B
  每 30 秒发送心跳并设置硬超时，超时后依次 TERM/KILL，再复核相关进程已
  退出。
- **发布边界**：本轮未 push、未 deploy、未切流。

## 2026-08-12 定向底层逻辑审计修复 checkpoint

- **审计边界**：从 clean `rebuild` SHA
  `54e9e25484ca56837ee54b345fcf28cdc3f6a0df` 开始，只做 changed-files
  targeted review、RED/GREEN 和机械门禁；未执行 formal full-file audit，
  固定 audit key 不变，`formal invocation=1`、`repeat=0`。
- **最早失败层与修复**：确认两个 major。其一是 confirmed
  session/profile 肤质在 `plan_task()` 后由 application 直接注入，绕过唯一
  merger 和 trace；现已改为代码侧 typed context signals，在 TaskPlan 前由
  `signal_merger` 按 exact > confirmed session > long-term profile 补空。
  普通上一轮 query context 不会污染新的完整推荐，default/unconfirmed 画像不进入。
- **Reference 合同**：`SemanticReference`、`ReferenceDraft`、prompt 和 128
  条人工 expected 冻结集现完整区分 `current_item`、`current_batch`、
  `candidate_ordinal`、`image_ordinal`、`current_topic` 和
  `previous_constraint`；schema 升到 `guide-semantic-intent-v2`，prompt
  升到 `guide-semantic-intent-prompt-v3`，缓存身份随版本自然失效。
- **TDD 与验证**：先观察 context API RED、四项 reference RED 和 prompt
  scope RED，再完成 GREEN。最终 focused 组为 understanding/merger
  `2626 passed`、application/profile `523 passed`、adapter/cache/composition
  `72 passed`、Task 6 gates `55 passed`、architecture boundary
  `22 passed`、最终 prompt/followup 合同 `18 passed`；compileall、
  `app.guide` boundary 和 `git diff --check` 通过。未运行 Guide full、
  整个 `tests/`、browser 或真实网络 A/B。
- **环境说明**：预设 runtime venv 的 `sniffio` 包目录缺少实现文件，导致一次
  AnyIO threadpool 定向测试在进入项目 SQLite 逻辑前环境失败；本 checkpoint
  不把该结果定性为代码回归，也不以它替代既有冻结 state verifier 证据。
- **独立复核**：两名 post-fix read-only verifier 对当前 diff 均判定 PASS，
  原两个 major 已关闭，`P0/P1/P2=0`。exact ordinal 保留 1..9 用于解析后
  越界澄清，semantic ordinal 仍限制 1..4。
- **未完成依赖与发布边界**：`GUIDE_LLM_API_KEY=MISSING`，真实 Task
  6.5–6.7、模型选择和 `model_selection.md` 仍未完成；未进入 Tasks 8、11、
  12、13，未修改旧 `app/services/**`，未 push、未 deploy、未切流。

## Round 1

- **冻结状态与核验**：HEAD 为
  `5b295bb4346198fb98b0806513b6e03721e0e4c9`；分支为 `rebuild`，编辑前
  worktree clean，且 `54e9e25`、`b20a714` 均为其祖先。authoritative
  verifier 与 dependency verifier 均判定 PASS。
- **一致性记录**：`5b295bb` 的 SubTask 2.7、5.9、6.4d 已一致记录。
- **唯一审计纪律**：固定 audit key 为
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`；
  `formal invocation=1`、`repeat=0`，本轮未执行 audit。
- **Key 与进程边界**：`GUIDE_LLM_API_KEY=MISSING`，且未读取值；无
  `pytest`、`playwright`、`uvicorn` 或 `intent_model_ab` 进程。
- **唯一前置与任务顺序**：Task 6.5-6.7 是唯一前置，当前无非 Key 行动项；
  未进入 Tasks 8、11、12、13。
- **执行与长任务规则**：本轮未运行测试、network 或 browser；未来长任务须
  每 30 秒发送心跳并设置硬超时，超时后依次 TERM/KILL，再复核相关进程已退出。
- **发布边界**：本轮未 push、未 deploy、未切流。

## Round 2

- **权威证据**：authoritative verifier 确认分支为 `rebuild`，HEAD 为
  `c4501f922e2ebad28d53daac270e6c974ea99f6b`，worktree CLEAN，且
  `b20a714c0bde21bd500228b94bcb67c79f5c52fe` 是其祖先。
- **审计纪律**：固定 audit key 为
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`；
  `formal invocation=1`、`repeat=0`，无其他 audit key。
- **阻塞与进程**：`GUIDE_LLM_API_KEY=MISSING`，未读取、打印或搜索其值；
  无 `pytest`、`playwright`、`uvicorn` 或 `intent_model_ab` 遗留进程。
  Task 6.5 不可开始，且无其他不依赖 Key 的合法行动项。
- **本轮状态**：无任务完成；未运行测试、network、browser 或 formal audit，
  未进入 Tasks 8、11、12、13。
- **变更与发布边界**：仅修改 `progress.md`；未 push、未 deploy、未切流。

## Round 3

- **权威证据**：两个已完成 verifier 的结果为本轮权威；冻结 SHA 为
  `843f5c6821a3fc579694e39db8b4c4dd0644effe`，分支为 `rebuild`，
  worktree clean，且 `b20a714c0bde21bd500228b94bcb67c79f5c52fe`
  是其祖先。
- **审计纪律**：audit key 唯一且固定为
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`；
  `formal invocation=1`、`repeat=0`，本轮未执行 formal audit。
- **阻塞与进程**：`GUIDE_LLM_API_KEY=MISSING`，未读取或打印其值；无
  `pytest`、`playwright`、`uvicorn` 或 `intent_model_ab` 进程，且当前无
  不依赖 Key 的合法任务。
- **本轮状态**：未进入 Tasks 8、11、12、13；未运行测试、network 或 browser。
- **变更与发布边界**：仅追加 `progress.md`；未 push、未 deploy、未切流。

## Round 4

- **权威证据**：两名独立代理均对冻结 HEAD
  `a24ed60216f29e71826a30ce7154f7d50a802ae1` 判定 PASS；分支为
  `rebuild`，worktree clean，且
  `b20a714c0bde21bd500228b94bcb67c79f5c52fe` 是其祖先。
- **审计纪律**：audit key 唯一且固定为
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`；
  `formal invocation=1`、`repeat=0`，本轮未执行 audit。
- **Key 与进程边界**：`GUIDE_LLM_API_KEY=MISSING`，仅检查存在性，未读取值；
  无 `pytest`、`playwright`、`uvicorn` 或 `intent_model_ab` 残留进程。
- **阻塞与任务顺序**：Task 6.5-6.7 均阻塞，且无其他不依赖 Key 的合法行动项；
  未进入 Tasks 8、11、12、13。
- **执行与发布边界**：本轮未运行测试、network、browser 或 A/B；未 push、
  未 deploy、未切流。

## Round 6

- **Session summary 与冻结证据**：冻结 HEAD 为
  `d62215032c5bea9e3b7dfe404bba0fed12bc6add`；分支为 `rebuild`，编辑前
  worktree clean，且 `b20a714` 是其祖先。
- **唯一审计纪律**：唯一 audit key 为
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`；
  `formal invocation=1`、`repeat=0`，本轮无新 audit。
- **Key 与进程边界**：`GUIDE_LLM_API_KEY=MISSING`，且未读取值；无
  `pytest`、`playwright`、`uvicorn` 或 `intent_model_ab` 进程。
- **唯一阻塞与任务顺序**：Task 6.5-6.7 仍为唯一阻塞；未进入 Tasks 8、11、
  12、13，未修改 `tasks.md` 或 `checklist.md`。
- **A/B 与执行边界**：A/B 有界 runbook 已只读确认但未执行；本轮未运行
  测试、network 或 browser。
- **发布边界**：本轮未 push、未 deploy、未切流。

## 2026-08-12 Task 6.5-6.7 真实 A/B NO-GO checkpoint

- **冻结与范围**：冻结 HEAD 为
  `615b4ac52cd4867581bb05c7fafb96aad3e49272`，分支为 `rebuild`，且
  `b20a714` 是其祖先。本轮只执行 Task 6.5-6.7，未进入 Task 8、未运行
  Task 0 或 formal full-file audit，未修改 `app/services/**`。
- **预检与输入**：Task 6 离线 guard 为 `64 passed in 39.05s`；V4-Flash
  与 V3.2 使用同一 128 条冻结 case、同一 prompt/schema 和参数。
  case manifest 为
  `28d17b3c6e86e5d9c85518ab3b4c731ff4705ea634671c00ba3147c7853443a6`。
- **真实 A/B**：有界 runner 在 45 分钟硬超时内完成，退出码为 `3`。
  V4-Flash 为 `1/128` normalized PASS、`127/128` FAIL，其中 provider
  timeout `126`、semantic mismatch `1`；V3.2 为 `62/128` PASS、
  `66/128` FAIL，其中 timeout `19`、semantic mismatch `47`。
- **硬门**：禁止字段接受和非法输出进入 TaskPlan 均为 `0/128`。
  V4-Flash 的硬约束覆盖、错误选品和 legacy fallback 在 2 个可用行均为
  `0`、126 行 `UNAVAILABLE`；V3.2 在 109 个可用行均为 `0`、19 行
  `UNAVAILABLE`。因此不能宣称 Task 6.6 通过。
- **模型选择与费用**：两模型均失败，机械结论为 `NO-GO`，未选择默认模型，
  禁止 Guide-only cutover。两模型 usage 和实际费用均为 `UNAVAILABLE`；
  V4-Flash latency p50/p95 为 `8043.484917/8136.106375 ms`，V3.2 为
  `5177.5175/8002.69775 ms`。
- **证据与修复判断**：normalized evidence SHA 为
  `e6fb6db1be7bd9a789428f180f79d9ab43ccad441ea445e95cc110354aa28ffb`，
  runtime metrics SHA 为
  `14d5e17c58057c3db213763fd835ec5761d2582fdcc3bde95b7f1b11f24fe6bf`，
  summary SHA 为
  `b954a10478395f2f76c27da4b5e72e507ee2c9887ffbe59dca201d9544365739`，
  三者校验通过。最早失败层为 provider transport 和 semantic proposal，
  未发现 runner/code 缺陷，故未执行 RED/GREEN 修复。
- **保密与进程**：一次性凭据只在指定交互式 PTY 中注入，runner 结束后已在
  同一 PTY 清除并退出；Git 证据只含聚合计数和 hash。runner、pytest、
  browser 和 uvicorn 无残留进程。
- **任务与发布边界**：SubTask 6.5 和 6.7 已完成；SubTask 6.6 与 Task 6
  保持未完成。未改模型配置，未 push、未 deploy、未切流。

## 2026-08-12 Task 6.5-6.7 真实 A/B 第二次 NO-GO checkpoint

- **冻结与范围**：在 clean `rebuild` 冻结提交
  `70a99cdcbc8bd652c51e25f1c90a7b87cf93223b` 上复跑同题真实 A/B；
  本轮只处理 Task 6.5-6.7，未执行 formal audit、未进入 Task 8，未修改
  生产代码、测试或 `app/services/**`。
- **adapter 验证**：Task 6 离线 guard 为 `64 passed`；请求体合同确认
  V4-Flash 与 V3.2 均显式使用 `enable_thinking=false`，并保持
  `temperature=0`、相同 max tokens、prompt/schema 和其余冻结参数。
- **真实 A/B 与完整性**：同一 128 条 case 产生 256 行 normalized result；
  runner 在 45 分钟硬超时内完成，退出码 `3`，未触发 TERM/KILL。
  `SHA256SUMS` 对 normalized、runtime 和 summary 三项均校验通过。
- **V4-Flash**：normalized PASS `52/128`，schema valid `125/128`，
  provider timeout `1`，schema invalid `2`，semantic mismatch `73`，
  critical failure `41`。字段正确数为 goal `105`、topic `120`、concern
  `81`、observation `112`、reference `104`、acts `115`。
- **V3.2**：normalized PASS `51/128`，schema valid `101/128`，
  provider timeout `27`，schema invalid `0`，semantic mismatch `50`，
  critical failure `43`。字段正确数为 goal `81`、topic `93`、concern
  `81`、observation `92`、reference `81`、acts `91`。
- **硬门**：V4-Flash 的 pipeline、错误选品和 legacy 硬门仅
  `125/128` 行可用，V3.2 仅 `101/128` 行可用；可用行的硬约束覆盖、
  错误选品和 legacy fallback 均为 `0`，两模型的 forbidden-field
  acceptance 与 invalid-output TaskPlan invocation 均为 `0/128`，但两模型
  各有 `5` 个 TaskPlan mismatch。部分可用不能满足 Task 6.6。
- **usage、延迟与费用**：官方 usage 与实际费用因不完整行均为
  `UNAVAILABLE`。V4-Flash 的 p50/p95 为
  `1566.608375/3332.361166 ms`，125 个可用 usage 行合计
  `252764` tokens；V3.2 的 p50/p95 为
  `5230.401625/8038.360375 ms`，101 个可用 usage 行合计
  `204996` tokens。
- **证据**：case manifest 为
  `28d17b3c6e86e5d9c85518ab3b4c731ff4705ea634671c00ba3147c7853443a6`；
  normalized evidence 为
  `202ea0044396cb28717aa45c7179fa68b67991c596eec4bbe7b9f2a3043e180e`；
  runtime metrics 为
  `14cc733f6c59eb74c51129f62b8e56ef8858ed642d2b1156dba2c6994c20a2df`；
  summary 为
  `933ef42df39c48e5536ee23c8297d79183667537075b19f2f68c407d7c73ce2b`。
- **结论与边界**：两模型均失败，第二次尝试机械结论仍为 `NO-GO`。
  SubTask 6.6 和 Task 6 主项保持未完成，tasks/checklist 未提前勾选，
  Task 8 未进入。一次性 Key 已在原交互式 PTY 中 unset 后退出；无 runner、
  pytest、browser 或 uvicorn 残留。未提交、未 push、未 deploy、未切流。

## 2026-08-12 Task 6 semantic v3 / prompt v7 freeze checkpoint

- **最早失败层修复**：将候选状态扩至四项并新增显式
  `focused_candidate_ordinal`；只有成功的 ordinal follow-up 写入 focus，
  新候选批次清空 focus，单候选不推断 focus。`ImageBundle` 新增显式
  `focused_image_ordinal`，单图上传仍默认为 `None`，内存和 SQLite CAS
  均可往返，旧 JSON 缺字段按 `None` 读取。
- **typed context**：语义合同升级为 `guide-semantic-intent-v3`，新增候选
  focus、图片数量与 focus，以及闭合的 `active_constraint_kinds`
  (`budget/category/skin/ingredient_exclusion/efficacy`)；resolver 只从可信
  snapshot、ImageBundle 和确认 query context 派生，不暴露商品 ID、事实
  或画像值。
- **prompt 与 repair**：prompt 升级为
  `guide-semantic-intent-prompt-v7`，改为 reference admission、goal
  priority、concern/observation/act admission 矩阵；格式修复请求只携带
  闭合 failure kind/path，不回传首轮模型输出、字段值或错误正文。
- **冻结集**：保留历史
  `semantic_intent_ab_v1.jsonl`，SHA-256 仍为
  `1ccd0d9137b2107e2c88f1f2d7f23de3c0560f3533bd9afeba2b650c055e19fd`；
  新增 128 条同 ID/同顺序的 v2，SHA-256 为
  `65837c47a852b7fb2bc8096fa2df984522d97bfe11ca3ffa437399abe0a97860`。
  expected 仅修改 authority 已裁决的 6 个 case，测试禁止其他 label 漂移。
- **传输参数**：V4-Flash 与 V3.2 的统一默认 timeout 从 8 秒调整为
  12 秒；仍保持相同参数、超时即失败、无 transport retry、分母不变。
- **TDD 与门禁**：candidate focus 聚焦组 `165 passed`；image focus
  聚焦组 `233 passed`；SemanticContext v3 合同 `72 passed`；最终
  semantic/adapter/cache/A-B/routing 组 `1269 passed`，state/focus/
  application/runtime composition 组 `230 passed`。`compileall` 和
  `git diff --check` 通过。
- **安全与边界**：v1 hash 未漂移；Key 扫描未发现用户提供的凭据；无
  pytest、runner、uvicorn 或 browser 残留。Task 6.6 和 Task 6 仍未完成，
  尚未选择默认模型，未进入 Task 8，未运行第二次 formal audit，未 push、
  未 deploy、未切流。

## 2026-08-12 Task 6 第三次真实 A/B 与 failure-path replay checkpoint

- **冻结输入**：clean source SHA 为
  `77a7c58f395fcdf8bfc4f8545bdb578cc9f3f8ab`；使用 v2 的 128 条同题
  case、`guide-semantic-intent-prompt-v7`、
  `guide-semantic-intent-v3`、`enable_thinking=false` 和统一 12 秒
  timeout。未改变 denominator、未增加 transport retry。
- **真实 A/B**：256 行完整生成，runner exit `3`，未触发 45 分钟硬超时。
  `SHA256SUMS` 三项全部通过。V4-Flash 为 `67/128` complete PASS，
  `1` timeout、`60` semantic mismatch；V3.2 为 `73/128` complete PASS，
  `7` timeout、`1` schema invalid、`47` semantic mismatch。两模型均失败
  exact all-case gate，机械结论仍为 `NO-GO`。
- **真实字段统计**：V4 的 goal/topic/concern/observation/reference/acts
  正确数为 `107/120/96/115/106/116`，critical failure `34`；V3.2 为
  `110/108/98/107/104/111`，critical failure `28`。V4/V3.2 的
  TaskPlan mismatch 分别为 `3/4`，均由上游 semantic proposal 错误触发。
- **真实性能与 usage**：V4 p50/p95 为
  `1517.254958/4175.178375 ms`，127 个 usage 可用行合计
  `235092` tokens；V3.2 为 `5377.826375/12002.640792 ms`，120 个
  usage 可用行合计 `224670` tokens。完整 usage 与实际费用继续明确为
  `UNAVAILABLE`。
- **真实证据 hash**：case manifest
  `016c909d71e0f838dd67604ec6f241bdefb7022c69b3cc9c58c602bab1d7482f`；
  normalized
  `2d9892f686148910d82a88d18d2ee5571b95e66a63a7cca4db1c6bf5f4ef3f77`；
  runtime
  `566d5a1d267d8a8361baaa2431af684c89d951c5e19920a1eb67157b19249811`；
  summary
  `e40e1967d9029fe857f612eea4b564709b4dda42be3f93ce5495886c199cd9d3`。
- **failure-path RED/GREEN**：新增 proposal/typed failure 二选一的 gate
  request；provider/schema failure 只以 `semantic=None` 进入 sanitized
  exact-only path，归一化的模型 merger/TaskPlan invocation 保持 `0/0`。
  runner/evaluator/real-entrypoint 相关组 `59 passed`；广泛 tools 收集因
  轻量 venv 缺 `numpy` 在测试执行前停止，不属于本改动回归。
- **pipeline replay**：重用第三次真实 proposal 与 typed failure code，
  不重发网络请求，也不替换真实 latency/usage。256/256 行均可观测；
  hard-constraint override、forbidden acceptance、invalid-output TaskPlan、
  wrong selection 和 legacy fallback 全部为 `0`。replay normalized SHA 为
  `115e835fc0bb89541f724ee3003351d39d68188476dd804ace2c89c6420094a0`，
  summary SHA 为
  `6b7ce63a5fd5d920c1e99508318d512ba6a716059f7098434877e4fd1d789dc4`。
- **任务与安全边界**：SubTask 6.6 及其 checklist 安全项已有 256 行全量
  零计数证据并勾选；因没有模型通过 exact semantic gate，Task 6 主项仍未
  完成，Task 8/11/12/13 均未进入。Key 仅经无回显 PTY 注入，shell 退出时
  已 unset；无 runner、pytest、browser 或 uvicorn 残留。未运行第二次
  formal audit，未 push、未 deploy、未切流。

## 2026-08-13 Guide 三线收口 checkpoint

### 已完成

- `rebuild` 的代码冻结提交为
  `3ebcb0f9e633e40c4ab8b80ab2ea0a19df4f869a`，并包含 `c7fef22`。
- 所有公开 message/stream 只走 Guide；旧公开 chat、V1/V2 Agent、Intent、
  Presenter、conversation owner、专属 Celery importer、脚本和测试已物理
  删除。删除前 importer 为 `101`，删除后 direct/dynamic/string/runtime/
  test/script/background/total 均为 `0`。
- Task 11 独立 verifier 为 `PASS`，P0/P1/P2 均为 `0`；collect 为
  `6894`，targeted 为 `19 passed`，compile 为 `405` 文件且无语法失败，
  双 boundary 为 `0 violations`，保护资产无漂移，工作树干净。
- 两步意图 route/detail 合同、短 Prompt、共享 repair 预算、分阶段缓存、
  v3 projection、唯一 merger 和 32 条 smoke 早停均已实现。离线 smoke 为
  route `32/32`、detail `26/26`。
- 数据恢复覆盖 15 个固定商品和 `201` 个字段状态：
  known `89`、pending `7`、quarantine `19`、unknown `86`。三份锁定 HTML
  为 found `3`、missing `0`、duplicate `0`；未伪造历史 `336/111`。
- 两个数据 verifier 已完成；共同 PASS 为 `0`，所以没有 decision、
  signature 或 promotion。`promotion_invocations=0`，
  `production_fact_count=0`。
- 状态门禁为 `58 passed`，覆盖跨 worker、SQLite CAS、SSE 断流和终态交付。
  focused 已执行到 `5079 passed`，剩余一个失败属于测试解释器依赖拆分。
- 唯一 formal audit 账本仍是表头加一条数据：
  `real_invocations=1`、`repeat=0`，没有换名重跑。

### 当前卡点

- `GUIDE_LLM_API_KEY=MISSING`，因此新的两步 V4-Flash/V3.2 真实 A/B
  未运行，95% route、90% detail 和安全零容忍门禁没有最终证据。
- browser runner 的 `output_io` symlink 竞态连续两次 verifier 失败；
  browser 路径已按止损规则停止，真实 normal/adversarial matrix 未运行。
- 权威测试环境依赖分散：runtime venv 缺 `PyYAML`/`numpy`，系统 Python
  的隔离子进程缺 `FastAPI`。focused/full 路径在同一
  `test_environment.dependency_resolution` 层连续两次失败，已停止第三次
  拼环境盲跑。

### 剩余工作

- 在不回显 Key 的受监管环境运行两步真实 A/B，并应用前 20 条失败率早停。
- 对 browser output ownership 做设计级重置后，再运行真实 normal/
  adversarial/XSS/session-switch/late-event/image matrix。
- 建立单一、可复现的完整测试环境，再运行 focused、Guide full、runtime
  full 和整个 `tests/`。
- 仅当上述门禁全绿后更新最终模型结论和整体状态；数据仍无 2/2 共识，
  不进入 promotion，也不请求逐文件用户审计。

### 预计完成

- 当前状态：`INCOMPLETE`，不得宣称 COMPLETE。
- Key 可用且两个止损路径完成设计级重置后，预计还需 `3-5` 小时完成真实
  A/B、完整测试和浏览器矩阵。未 push、未 deploy、未切生产流量。

## 2026-08-13 Task 15 单解释器可复现测试 Gate 完成 checkpoint

### 已完成

- 两套 fresh rebuild 从同一锁定输入独立建立；路径、resolve 路径和 inode
  均不同，stable identity SHA 均为
  `492ea4992b5bbcd8fd42060db181a783da1f2affa8d6c7e541d8d482e9ea5a57`。
- 四套 suite 记录同一环境身份：focused `5149`（SHA 前缀 `838c`）、
  Guide full/all `6954`（SHA 前缀 `eb80`）、runtime `228`（SHA 前缀
  `6571`）。独立 final verifier 为 `PASS`，无残留进程。
- Task 15 和 SubTask 15.3 已完成并准入 Task 12；Task 12 及其他未验证项
  保持未勾选。

### 当前卡点

- runner 同层第二次出现 `P1`，已按止损规则 `STOP`。
- Key 文件缺失，真实模型门禁不能继续。

### 剩余工作

- 按止损路径解决 runner 的 P1，并在 Key 文件可用后完成 Task 12 剩余的
  模型、浏览器及独立验收门禁；随后再执行 Task 13 最终收口。

### 预计完成

- 两项卡点解除后预计还需 `3-5` 小时；当前整体状态仍为 `INCOMPLETE`。
  未 push、未 deploy。

## 2026-08-13 最终 Python gate checkpoint

- 同一 stable identity 为
  `492ea4992b5bbcd8fd42060db181a783da1f2affa8d6c7e541d8d482e9ea5a57`。
  focused 为 `5147 passed / 2 skipped / 5 warnings`，nodeid SHA 前缀
  `838c`；Guide full 为 `6954 passed / 0 failed / 5 warnings`，nodeid SHA
  前缀 `eb80`；runtime full 为 `228 passed`，nodeid SHA 前缀 `6571`；
  整个 `tests/` 为 `6954 passed / 5 warnings`，nodeid SHA 前缀 `eb80`。
- 四套 Python gate 均无 timeout、TERM、KILL 或残留进程；据此仅完成
  SubTask 12.1、12.2 及对应 checklist 最终验证项，Task 12 总项仍未完成。
- 当前硬卡点：DeepSeek runner 的 evidence/output 层连续第二次 verifier
  `P1`；`0a52cc0` 未集成，且该路径已 `STOP`。安全新 Key 文件仍为
  `MISSING`，因此真实模型和 browser 均未运行。

## 2026-08-13 真实 DeepSeek 32 smoke 与 B 方案设计裁决 checkpoint

### 真实 smoke 三 lane 数字

- 官方 DeepSeek 32 条 smoke（provider `deepseek_official`，`base_url=https://api.deepseek.com`，
  `enable_thinking=false`、`temperature=0`、`max_tokens=128`）三 lane 结果：
  - **两阶段 flash（deepseek-v4-flash）**：route-critical `71.9%`（23/32）、
    detail-key `54.5%`（12/22），`unsafe_task_plan_mismatch=2`，
    `safe_clarification_mismatch=14`，p95 `5315ms`；未过 85% smoke，`passed=false`。
  - **两阶段 pro（deepseek-v4-pro）**：route-critical `56.3%`（18/32）、
    detail-key `50%`（11/22），`unsafe_task_plan_mismatch=1`，
    `safe_clarification_mismatch=17`，p95 `4652ms`；未过，`passed=false`。
  - **单阶段 pro（deepseek-v4-pro，原对照 lane）**：goal `87.5%`、topic `90.6%`、
    concern `87.5%`、observation `90.6%`、reference `93.8%`、acts `90.6%`、
    schema_valid `93.8%`，全字段全对 `24/32=75%`，route-critical `87.5%`（28/32）、
    detail-key `81.25%`（26/32），p95 `3760ms`。安全四硬门
    （hard_constraint_override / forbidden_field / wrong_product / legacy_fallback）
    全部为 `0`，`unsafe_task_plan_mismatch=0`。

### B 方案裁决

- 机械结论：两阶段候选在 DeepSeek V4 上真实不达标（route-critical 均低于 85% 且带
  `unsafe_task_plan_mismatch`）；单阶段 V4-Pro 明显更优且安全硬门干净。
- 采纳 B 方案：把生产候选方向从“两阶段”改为“单阶段 DeepSeek V4-Pro”，两阶段降级为
  对照与历史证据。已同步更新 spec.md「DeepSeek V4 模型门禁」章节、tasks.md
  SubTask 6.16–6.19、checklist.md 真实模型 A/B 段。
- 128 正式门槛保持不变：route≥95% / detail≥90% / 安全硬门=0 / p95≤12s / 全部失败
  fail-closed，且对两阶段与单阶段候选一致，不因候选形态放宽。单阶段 V4-Pro 仍须先过
  32 smoke 再上 128 才能接生产。

### 证据与追溯

- evidence 目录（只读参考，未改）：`/private/tmp/xiaoro-smoke-203441/evidence`，
  含 `summary.json`、`runtime_metrics.json`、`normalized_results.jsonl`、`SHA256SUMS`。
- summary 内 `case_manifest_sha256=016c909d71e0f838dd67604ec6f241bdefb7022c69b3cc9c58c602bab1d7482f`；
  另有 `smoke_manifest_sha256=bdb084ed…`、`stable_evidence_sha256=5034fd93…`。
  费用 `UNAVAILABLE`，`selected_lane=null`、`selected_model=null`。

### 边界声明

- 本次仅改规格三件套（spec.md / tasks.md / checklist.md）并 append 本段 progress，
  未改任何代码、prompt、测试。SubTask 6.16–6.19 与相关 checklist 门槛项仍保持未勾选。
- 尚未选定生产模型（128 门禁未运行），未接生产（production composition 未改动），
  未 push、未部署、未切流。整体状态仍为 `INCOMPLETE`。

## 2026-08-14 Task 18-20 Bounded Closure

### Outcome

- 本轮结论为 `MAIN_CHAIN_GREEN + DATA_GREEN`。文字主链、103 商品数据闭环、
  双 verifier、非空 promotion、post-promotion readiness 和真实 normal browser
  均有当前 HEAD 证据。
- formal audit 保持 `invocation=1`、`repeat=0`，本轮未执行第二次正式全文审计。

### Main Chain

- Task 18 已集成 `7313366` 和 `468be12`。resolved slot、中文预算、模糊预算、
  product mention/code-owned ID、comparison、suitability、knowledge 和 followup
  均有 RED/GREEN 证据。
- 单阶段 DeepSeek V4-Pro 只运行 16 条，配置为 `max_tokens=256`、
  `temperature=0`、`thinking=disabled`、`max_repair=1`。原始 provider 输出为
  core route `83.33%`、false clarification `25%`、provider failure `1`、
  wrong product `2`、legacy fallback `0`、p95 `3054.363ms`；15 条 usage 完整，共
  `37,083` prompt、`1,676` completion、`38,759` total tokens。费用
  `UNAVAILABLE`。证据 SHA 为
  `006814e382b4534b604ceb536d808941b1a4d1d2c792ea48a078fa48d71492da`。
- 未新增模型调用。使用同一 16 条冻结原始 proposal/provider failure 在当前 HEAD
  重放 exact → merger → TaskPlan → retrieval → decision → SSE，得到 core route
  `91.67%`、false clarification `0%`、hard constraint override `0`、
  unsafe TaskPlan `0`、wrong product `0`、legacy fallback `0`、16/16 单终态；
  原 provider failure 由 exact typed clarification 安全恢复。重放证据 SHA 为
  `3d7f48b7bb6e99d37002340da4bff2054aaa40479f6c96a78e05ccc9bb34ce7c`。
- normal browser 在未配置 LLM Key、未注入 semantic fixture 的当前 runtime 中，
  对 `500 内适合油敏肌的防晒` 产生 3 卡，product IDs 为 `55/57/54`，
  clarification `0`、terminal end `1`，page/request/image error 均为 `0`。
  browser evidence SHA 为
  `00f1cec2f1c8f88a4e72eaed2f7cfe5ece44de67221fad63f097e70e91b2b996`，
  screenshot SHA 为
  `1001dfc9ad8907822cfe2c68b74c7d41e462bcf418be7000e0d10a25e5731a77`。

### Data

- Task 19 已集成 `d09cd5c`、`6a0e62b`、`05b64d6`。冻结 inventory
  `64,449`，保存页 `118`，可解析 `109`，参数组 `803`，
  `silently_skipped=0`，Canonical `103`，exact-item `98`，
  alternate-equivalent `3`，source-gap `2`。
- pre-promotion 字段矩阵为 `known=651 / pending=36 / quarantine=5 /
  unknown=687 / not_applicable=1711`。post-promotion 为
  `known=683 / pending=4 / quarantine=5 / unknown=687 /
  not_applicable=1711`，即 known `+32`、pending `-32`。
- 103 商品六状态 readiness 基线为 `IDENTITY_READY=5 /
  RECOMMEND_READY=22 / COMPARE_READY=54 / SUITABILITY_READY=22 /
  FULL_READY=0 / BLOCKED=0`；promotion 后为 `5/22/48/28/0/0`，
  6 商品真实提升到 `SUITABILITY_READY`。重复构建逐字节一致，
  matrix SHA 为
  `d79060957d9af7634feb5c0791b3deed4b18c7b349fef5f42c7a019700433f89`，
  summary SHA 为
  `3fbebcb9cca16c02a31ae53c5f8282f057e34808e8d2791f1ab84b7248f69db8`。
- verifier A/B 均为 `32/32 PASS`，report SHA 分别为
  `7365d36b2f96df520a7f9ce272eee40a5709c58ada453adfef22f1e08b84b26b`
  和
  `11bf5c8aa3a42d0dd9343057ccb4d039795d51b1e553b38c18c7fc70eca9164b`。
  joint decision SHA 为
  `af7a2577d5626e706cb365e4f4e5e3f052a05a7f1bbadde0decd22a3fafc6a89`。
- `promotion_invocations=1`、`production_fact_count=32`，production facts
  SHA 为
  `248d9cdf4cb184d20f6855c472fb0843895c159958f329afeb0df014aaabf53d`，
  manifest logical SHA 为
  `80013240164ace2991c92b519486e72022feec5e6b98807e7e2de5635eae99c1`。
  固定 12 个旧 pilot 仍诚实保持 unknown，没有伪造提升。

### Verification

- changed-files focused `4612 passed`；最终文字链 focused `3118 passed`；
  数据 focused `61 passed`；Guide full `7105 passed`；runtime focused
  `228 passed`；Phase 2 focused `218 passed`；message/stream parity 与
  单终态相关集 `400 passed`；boundary/legacy focused `34 passed`。
- `compileall`、`app/guide` boundary、`app/guide_runtime` import boundary、
  `git diff --check` 均通过；legacy importer 为 `0/454 files`。
- Canonical 保持 `103`；deterministic ranking SHA 保持
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`；
  批准评论保持 `6`，sources SHA 保持
  `22bac50e053a621826c831565b3a18e1df3592049ac35377298bac0ab0536171`。
- 结束审计未发现 pytest、Uvicorn、Playwright/Chromium、DeepSeek runner
  或 8765 监听残留。未运行整个 `tests/`、完整 Phase 2 browser 或正式
  128 模型门禁；未 push、未部署、未切生产流量。
