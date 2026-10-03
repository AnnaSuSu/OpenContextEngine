"""Render the frozen comparison tables from scored runs."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
data=json.loads((ROOT/'docs/eval/results/expanded-comparison-20261003.json').read_text())
pct=lambda value:f'{value*100:.2f}%'
sec=lambda value:f'{value/1000:.2f}'
lines=['# 跨仓库首查评测：Click、HTTPX、Zod','',
'2026-10-03；冻结版本 `expanded-v1`。新增 30 道自然语言任务、95 项源码证据；每题中英文各一次，每个系统 60 次，共 120 次查询。以下不合并此前用于开发调参的 Django 十题。','',
'> 诊断勘误：HTTPX 文件上传的两条 50% 记录仅缺函数间空白行，业务证据已完整返回。本文保留冻结口径，原因及统一诊断重算见[漏项诊断](EXPANDED_DIAGNOSIS.md)。Zod 解析入口仍是真实漏检。','',
'## 4,000 token 主指标','',
'必需证据覆盖率：每个事实要求全部标准源码行被真实返回；先在题内等权，再在仓库内和仓库间等权。完整召回率要求该查询找齐所有标注事实。','',
'| 仓库 | RepoNerve 中文 | ACE 中文 | RepoNerve 英文 | ACE 英文 |','| --- | ---: | ---: | ---: | ---: |']
for repo in ['click','httpx','zod']:
 es={e['system']:e for e in data['entries'] if e['repo']==repo}
 lines.append('| '+repo+' | '+' | '.join(pct(es[sys]['summary']['4000'][lang]['coverage']) for lang in ['zh','en'] for sys in ['reponerve','ace'])+' |')
lines+=['| 总体 | '+' | '.join(pct(data['systems'][sys]['summary']['4000'][lang]['coverage']) for lang in ['zh','en'] for sys in ['reponerve','ace'])+' |','',
'| 总体指标 | RepoNerve | ACE |','| --- | ---: | ---: |']
for title,key in [('证据覆盖率（中英合并）','coverage'),('完整召回率','completeRecall')]:
 lines.append('| '+title+' | '+' | '.join(pct(data['systems'][s]['summary']['4000']['all'][key]) for s in ['reponerve','ace'])+' |')
lines+=['| 找齐全部证据的查询 | '+' | '.join(str(data['systems'][s]['summary']['4000']['all']['completeCount'])+'/60' for s in ['reponerve','ace'])+' |',
'| 成功查询 | 60/60 | 60/60 |',
'| 客户端查询中位耗时 | '+' | '.join(sec(data['systems'][s]['latency']['medianMs'])+' 秒' for s in ['reponerve','ace'])+' |',
'| 客户端查询 P95 | '+' | '.join(sec(data['systems'][s]['latency']['p95Ms'])+' 秒' for s in ['reponerve','ace'])+' |','',
f"60 组成对查询中，RepoNerve 覆盖率胜 / 平 / 负为 **{data['pairs']['wins']} / {data['pairs']['ties']} / {data['pairs']['losses']}**。中文与英文来自相同 30 道任务，不能当作 60 个独立样本。中位数取中间两值平均，P95 使用 nearest-rank。",'',
'## 结果解读与明确漏项','',
'在本轮冻结的 4,000 token 口径下，RepoNerve 总体领先 4.44 个百分点，优势来自 Click 与 HTTPX；Zod 中英文平均 86.67%，低于 ACE 的 88.75%。ACE 查询中位约快 1.75 倍。新语言已经走通同一架构，但检索质量仍有局部短板。','',
'- Zod `safe-parsing` 中英文：RepoNerve 0%，ACE 100%。原始上下文返回了多种类型内部校验片段，却没有覆盖标准要求的解析入口、上下文构造和结果包装。',
'- HTTPX `multipart-upload` 中英文：冻结评分为 RepoNerve 50%、ACE 100%，后续查明只缺两个空白行；业务代码已完整返回，详见诊断勘误。',
'- Zod `tagged-union` 中文：RepoNerve 66.67%，ACE 100%，遗漏标签映射构造。',
'- RepoNerve 还漏了部分 Cookie、代理匹配、解码与原子写入证据；并非所有漏项都输给 ACE，逐题列表在机器可读汇总中。','',
'ACE 原始返回平均约 5,461 token，原始证据覆盖率 94.58%；RepoNerve 平均约 3,631 token，覆盖率 90.14%。等预算主指标说明本轮 RepoNerve 的有限上下文保留效果较好，不能据此说其总体候选召回更全。要区分召回、重排和预算选择的贡献，仍需单独消融。','',
'本轮完成后只做评分与源码核验，没有针对这些漏项改参数或重跑挑选成绩。','',
'## 范围与冻结条件','',
'| 仓库与版本 | Commit | 源码文件 | RepoNerve 片段 |','| --- | --- | ---: | ---: |']
for repo in ['click','httpx','zod']:
 s=json.loads((ROOT/f'eval/expanded-v1/{repo}/snapshot.json').read_text());e=next(e for e in data['entries'] if e['repo']==repo and e['system']=='reponerve')
 lines.append(f"| {repo} {s['tag']} | `{s['commit']}` | {len(s['files'])} | {e['indexing']['units']} |")
lines+=['','两组使用同一生产源码子集：Click `src/click`、HTTPX `httpx`、Zod `src`，排除测试、示例、benchmark、文档和依赖。52 个文件共 826,815 字节。题目不直接提供文件名或函数名；中文/英文顺序按题交替。',
'',
'配置在查询前冻结：`batched-dag-v4`、`structural-units-v2`、Qwen3-Embedding-4B、Qwen3-Reranker-4B、两轮批量重排（批大小 32，批次 token 预算 8192），无跨查询缓存。Python/TypeScript 共用同一检索主流程；所有模型在远程 GPU 上推理。ACE 使用 `@augmentcode/auggie-sdk@0.2.0` 的 `DirectContext.search`。未增加 Agent 或外部查询改写。',
'',
'ACE 请求 `maxOutputLength: 40000`，归档其实际返回值；两个系统的结果均保留原始顺序，用 `cl100k_base` 计量 4,000 token 上限，包含路径和行号；超限时截断并丢弃末尾不完整行。没有根据标准答案挑选片段。RepoNerve 在线就按 4,000 token 选择。',
'',
'源码、题目、答案和引擎均记录 SHA256。题目和标准证据由 Codex 阅读源码后、查询前编写；本轮未根据输出修订答案或调整引擎。这是新仓库上的内部扩展验证，不是第三方独立标注、盲测或公开保留集。三个库较小且知名，不能外推到大型陌生项目。',
'',
'## 延迟与索引','',
'两个系统都从同一台 Mac 发起请求，每个系统内部串行；两个系统的执行时间有重叠，后端互相独立。RepoNerve 经认证 SSH 转发，ACE 访问官方 API；硬件、部署与输出长度不同，因此耗时是本次部署体验，不是算法隔离实验。索引和查询分开计时，模型已常驻；没有并发或模型冷启动测量。','',
'| 仓库 | RepoNerve 查询中位 / P95（秒） | ACE 查询中位 / P95（秒） | RepoNerve 首次索引（秒） | ACE 上传及索引（秒） |','| --- | ---: | ---: | ---: | ---: |']
for repo in ['click','httpx','zod']:
 es={e['system']:e for e in data['entries'] if e['repo']==repo};a=es['ace'];r=es['reponerve']
 lines.append(f"| {repo} | {sec(r['latency']['medianMs'])} / {sec(r['latency']['p95Ms'])} | {sec(a['latency']['medianMs'])} / {sec(a['latency']['p95Ms'])} | {sec(r['indexing']['indexingMs'])} | {sec(a['indexing']['elapsedMs'])} |")
lines+=['',
'RepoNerve 首次建索引后曾因新部署缺少 TypeScript 编译器而重启，补齐固定版本依赖后复用 Python 索引并完成 Zod；此过程发生在正式查询之前，没有改变冻结算法。表中 RepoNerve 使用索引元数据保留的首次构建耗时。ACE 三个仓库均报告所有文件为 newlyUploaded。索引时延包含不同服务的上传、轮询等过程，不可直接解释为解析或 GPU 性能差。',
'',
'## 补充预算与输出检查','',
'| 输出前缀预算 | RepoNerve 覆盖率 | ACE 覆盖率 |','| --- | ---: | ---: |']
for budget in ['2000','4000','8000']:
 lines.append('| '+budget+' | '+' | '.join(pct(data['systems'][s]['summary'][budget]['all']['coverage']) for s in ['reponerve','ace'])+' |')
lines+=['',
'2,000/8,000 均为同一原始响应的离线前缀评分；RepoNerve 的原始请求预算仍是 4,000，因此 8,000 档不能称为两个系统各自按 8,000 token 检索的结果。',
'',
'| 原始输出诊断 | RepoNerve | ACE |','| --- | ---: | ---: |']
lines+=['| 原始响应平均 token | '+' | '.join(f"{data['systems'][s]['rawTokens']['mean']:.1f}" for s in ['reponerve','ace'])+' |',
'| 原始响应证据覆盖率 | '+' | '.join(pct(data['systems'][s]['rawCoverage']) for s in ['reponerve','ace'])+' |',
'| 与冻结源码不一致的编号行 | '+' | '.join(str(data['systems'][s]['rawInvalidNumberedLines']) for s in ['reponerve','ace'])+' |','',
'ACE 的 6 处编号行不一致全部是实际响应末尾被字符上限截断的半行，均未得分；4,000 token 主指标两组均为 0 处不一致。这不能解释为生成了 6 处虚构源码。',
'',
'原始响应长度不同，所以原始覆盖率仅作诊断，不能替代等预算主指标。未标注的代码不自动算无关，未测量完整精确率；ACE 未返回可用于核算的计费数据，不推算费用。',
'',
'## 归档与复核','',
'- 冻结输入：`eval/expanded-v1/{click,httpx,zod}`，引擎冻结：`eval/expanded-v1/engine-freeze.json`。',
'- [机器可读汇总](results/expanded-comparison-20261003.json) 包含逐题差值、漏项、报告/评分哈希及原始运行目录。',
'- [完整性核验](results/expanded-audit-20261003.json) 核对冻结文件、源码、远程索引身份、引擎哈希、120 份原始响应及 RepoNerve 的预算/无查询缓存状态。',
'- 运行：`node scripts/expanded/ace.mjs click|httpx|zod` 和 `node scripts/expanded/reponerve.mjs click|httpx|zod`；前者会访问订阅 API，后者需要已授权的远程服务与 SSH 转发。',
'- 离线评分：`node scripts/expanded/score.mjs RUN_DIRECTORY`；汇总：`node scripts/expanded/summarize.mjs SIX_RUN_DIRECTORIES`；审计：`python3 scripts/expanded/audit.py SIX_RUN_DIRECTORIES`。',
'',
'原始运行目录：','']
lines += [f"- `{e['run']}`" for e in data['entries']]
(ROOT/'docs/eval/EXPANDED_EVAL.md').write_text('\n'.join(lines)+'\n')
