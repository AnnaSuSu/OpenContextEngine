# RepoNerve

RepoNerve 是面向 AI 编程 Agent 的代码上下文引擎研究项目，目标是在完全可自托管的条件下，根据自然语言任务找全相关代码及其联系，并通过可复现评测与 ACE 及开源方案比较。

项目以开源工程为主，论文是后续可选方向。当前对 Python、TypeScript/TSX、JavaScript/JSX 和 Go 提供结构解析，其他合格文本提供保底检索，模型可自托管。首轮跨仓库冻结评测在 Click、HTTPX、Zod 上新增 30 道中英文配对任务，与 ACE 合计完成 120 次查询，全部成功。4,000 token 下，RepoNerve 总体必需证据覆盖率 **90.14%**，ACE **85.69%**；完整召回率 **80.00% / 66.67%**。查询中位耗时为 **3.76 / 2.15 秒**，ACE 更快。

这轮在两个 Python 库领先，在 TypeScript 的 Zod 上略落后（86.67% / 88.75%）。题目与答案由 Codex 在查询前依据源码编写，配置冻结后没有继续调参；属于内部扩展验证，尚不能证明普遍优于 ACE。范围、漏项、原始输出长度差异及完整记录见[跨仓库评测](docs/eval/EXPANDED_EVAL.md)。此前 Django 开发题及速度实验保留为历史记录，未混入这次成绩。

随后修复了候选重复占位和短函数证据不完整的问题。同一批 60 条查询的开发回归中，覆盖率 **90.14% → 94.03%**，Zod **86.67% → 98.33%**，3 条改善、57 条不变；中位耗时 **3.76 → 4.51 秒**。这是观察漏项后的回归，不能当作新的保留集成绩。实现与全部记录见[候选保留修复](docs/eval/CANDIDATE_RETENTION_FIX.md)。原冻结评分中的空白行误判另有诊断口径，未混入上述收益。

共享整体评分的[最新提速](docs/eval/SHARED_INTENT.md)已通过四仓库 76 条开发回归：各仓库远程中位耗时降至 1.55–2.55 秒，逐题 75 条覆盖不变、1 条改善；常驻入口默认使用 `shared-intent-v4`。

Git 历史实验未观察到准确率增益，已撤掉功能接入，继续使用纯源码检索；[实验结果](docs/eval/GIT_HISTORY.md)和代码归档保留供查阅。

已增加 [JavaScript 与 Go 结构解析](docs/eval/JS_GO.md)，支持 JS/TS 混合绑定、Go 函数与方法边界及有依据的静态关系。

语言适配层与检索流程分离，Python/TypeScript 已通过真实远程索引和同一检索引擎完成本轮对照。其他合格 UTF-8 源码、配置和脚本现可使用[通用文本保底](docs/eval/TEXT_FALLBACK.md)：保留原始行号，共用召回与重排，不生成猜测的语义关系。接口与支持边界见[技术报告](TECHNICAL_REPORT.md#已实现的语言适配边界)。

第一阶段聚焦自然语言语义搜索，例如“找到处理用户登录逻辑的代码”“这个项目的路由是怎么配置的？”。主指标为固定 token 预算下的首查必需证据覆盖率；先保存 ACE 和开源检索器的基线，再做引擎。概念级枚举与 Agent 多轮表现后续单独验证。

## 项目文档

| 文档 | 用途 |
| --- | --- |
| [项目目标](GOALS.md) | 产品边界、自托管要求、评测范围、指标与验收原则 |
| [技术调研与研究方案](TECHNICAL_REPORT.md) | 开源实现、ACE 公开证据、相关论文、候选架构、研究问题与实验路线 |
| [模型接入约定](MODEL_PROVIDERS.md) | 模型分工、已有渠道记录、接入验证和会话隔离 |
| [SDK 接入与试跑](docs/SDK_PILOT.md) | 安装、配置、协议探针、真实 SDK 冒烟及 medium/high 小范围对照 |
| [本次 SDK 试跑结果](docs/SDK_PILOT_RESULTS.md) | 接入成功证据、引用失败、high 超时和协议异常记录 |
| [ACE SDK 接入与检索记录](docs/ACE_PILOT.md) | 认证、三题真实检索结果、运行限制和订阅期内的基线保存顺序 |
| [Django 首轮评测协议](docs/eval/DJANGO_PROTOCOL_V1.md) | 10 道中英文配对题、冻结源码范围、token 预算、源码证据评分和运行命令 |
| [Django ACE 首轮结果](docs/eval/DJANGO_ACE_RESULTS.md) | 两版参考答案成绩、逐题漏项、耗时与原始结果归档 |
| [开源首查对照](docs/eval/OPEN_SOURCE_BASELINES.md) | 三组初步参照、索引范围与远程模型配置 |
| [RepoNerve 原型](docs/eval/REPONERVE_PROTOTYPE.md) | 结构索引、混合召回、关系扩展、预算选择及首轮结果 |
| [候选保留与证据完整性修复](docs/eval/CANDIDATE_RETENTION_FIX.md) | v6 实现、同题 60 次回归及质量/耗时变化 |
| [通用文本保底](docs/eval/TEXT_FALLBACK.md) | 未适配语言、配置和脚本的文本召回，排除策略与混合仓库验证 |
| [Git 历史召回与对照](docs/eval/GIT_HISTORY.md) | 已结束的历史召回实验、对照结果与代码归档 |
| [跨仓库扩展评测](docs/eval/EXPANDED_EVAL.md) | 三个仓库、30 道中英文配对题、冻结配置下与 ACE 的质量和耗时比较 |
| [速度重构与使用方式](docs/eval/REPONERVE_SPEED.md) | 架构取舍、三轮实际客户端延迟、常驻服务与 CLI |
| [Django 参考答案 v1](docs/eval/DJANGO_REFERENCE_V1.md) | Codex 逐题源码核验的 40 个必需事实及对应代码位置 |
| [调研源码版本](docs/research/repositories.json) | 本轮检查的第三方仓库、完整 commit SHA 与源码入口 |
| [Benchmark 与 ACE 对比调研](docs/research/benchmarks.md) | 现有 benchmark 的适用性、可借用的评测方法与 ACE 公开对比现状 |

后续方案讨论和实现以这些文档为起点。目标与评测约束以 `GOALS.md` 为准；技术报告中的候选方案须经实验验证后才能成为确定设计；模型渠道须完成当前接入验证后才能用于正式评测。发现文档冲突时，应明确修订决定并同步相关文档。

本地接入检查依次使用 `npm ci`、配置 `.env`、`npm test`、`npm run probe` 和 `npm run smoke`。开发题准备与运行见 SDK 文档；这些命令会按配置访问模型中转，`npm test` 除外。

## 文档维护

新增技术结论时记录证据来源、版本、适用范围和验证状态。上游更新、模型变更或实验结果与旧判断不一致时，更新相应章节与修订记录。不要把设计建议写成已实现能力，也不要把他人的基准成绩写成 RepoNerve 的结果。
