# JavaScript 与 Go 结构解析

2026-10-04。新增 `.js`、`.jsx`、`.mjs`、`.cjs` 和 `.go` 结构适配，沿用代码单元、召回、重排和预算选择接口。配置、脚本及其他语言继续使用文本保底。

JavaScript 复用固定版本 `typescript@5.9.3` 的 Compiler API，支持 ESM、CommonJS、JSX、函数与方法，并在同一虚拟文件集合中绑定 JS/TS 导入和调用。跨 JS/TS 的关系重新映射到统一 ID；动态接收者和未知回调保留未解析记录。物理 CR/LF 行号与编译器字符偏移分别处理，Unicode 分隔符不会挪动引用位置。参见 [allowJs 官方说明](https://www.typescriptlang.org/tsconfig/allowJs.html)。

Go 使用官方 `go/parser` 提取函数、接收者方法、类型、语句边界和同符号续片；可通过 `languageOptions.go.mode="types"` 启用 `go/types`，绑定快照内的跨包函数、具体接收者方法、泛型调用和类型引用。默认 `languageOptions.go.mode="syntax"` 使用基础语法绑定。局部同名回调、接口动态分发及快照外实现保留未解析记录。源码片段保持完整行、无重叠，并覆盖全部非空源码。参考 [Go parser 文档](https://pkg.go.dev/go/parser)。

## 使用

`npm ci` 提供 JS/TS 解析器。Go 索引需要 Go 1.22+，本轮验证版本为 Go 1.27.1；可通过 `REPONERVE_GO_BINARY` 指定可执行文件。解析辅助程序只编译本项目的标准库实现，不编译或执行被分析仓库，不下载其依赖。辅助程序缓存按源码与工具链版本隔离。

```sh
export REPONERVE_GO_BINARY=/path/to/go/bin/go
python3 scripts/prepare-source.py /path/to/repository --output /tmp/snapshot.json
python3 scripts/inspect-source.py /path/to/repository --snapshot /tmp/snapshot.json --output /tmp/structure.json
```

## 验证

36 项 Python 测试、23 项 Node 测试通过，覆盖 ESM/CommonJS、混合 JS/TS 调用、Go 接收者与遮蔽、重复平台函数、语法错误、长函数、Unicode/CRLF 和完整源码覆盖。Click、HTTPX、Zod 原有 2,333 个单元逐字段一致。

自动纳入全部合格文件，验证 Cobra 64 个文件、Commander 215 个文件及原 esbuild 321 个文件；结构单元分别为 846、1,090、11,295。详见[结构检查记录](results/js-go-structure-20261004.json)。Cobra 和 Commander 固定版本及各四道中英文问题在查询前冻结于 `eval/js-go-v1/`；文本/结构对照由 `scripts/roadmap/structure.py` 执行，答案仅在本地评分。

Go 基础解析中，esbuild 的 `api.Context` 和 `ctx.Watch` 都是未解析调用。类型检查已把 `api.Context` 连接到 `pkg/api/api.go` 的定义；`ctx.Watch` 的接收者是接口，仍保留未解析状态。

## 文本与结构的真实对照

保持原完整子问题重排引擎不变，对每个问题交替运行文本保底与结构解析，共 64 次查询。以下只隔离结构解析的影响，未混入新快速引擎的收益。

| 仓库 | 每种模式查询数 | 文本覆盖率 | 结构覆盖率 | 文本/结构完整查询 |
| --- | ---: | ---: | ---: | ---: |
| Cobra | 8 | 80.83% | 85% | 4 / 4 |
| Commander | 8 | 100% | 100% | 8 / 8 |
| esbuild | 16 | 81.25% | 81.25% | 12 / 13 |

Cobra 帮助处理的中英文证据增加，但英文上下文继承少一项；esbuild 平台依赖写回的中英文漏项补齐，中文 Make 测试入口退步。结构信息有收益，也会改变召回与选择，不能用解析关系数量代替逐题质量。源码、行号、预算和响应哈希均通过验证。全部记录见[逐题对照](results/js-go-retrieval-20261004.json)。

## 编译器绑定与配置

`go/types` 仅从已验证的快照加载包，不运行仓库、下载模块或启动 LSP 服务。模块路径优先读取快照内根目录的 `go.mod`，也可显式提供；没有模块声明时使用 `snapshot` 作为内部名称。类型分析模式的默认构建目标为 `linux/amd64`、关闭 CGO、无额外构建标签；文件仍全部可检索，类型绑定只使用该目标中的非测试 Go 文件。缺少外部包时保留仍能证明的本地绑定，每个文件最多记录 20 条诊断；重复声明的包不生成任意选择的绑定。默认目标可在快照中配置：

```json
{"languageOptions":{"go":{"mode":"types","modulePath":"example.com/project","goos":"linux","goarch":"amd64"}}}
```

`goos` 支持 linux/darwin/windows/freebsd，`goarch` 支持 amd64/arm64/386/arm。目标配置、工具链版本及两份辅助程序源码参与索引身份。嵌套模块和快照外依赖不自动加载。依据为 [Go types 官方 API](https://pkg.go.dev/go/types)。

新增六项类型绑定测试覆盖别名导入、跨包构造与接收者、泛型、嵌入方法、接口/回调拒绝、平台选择、缺失依赖和重复声明；合计 42 项 Python 与 23 项 Node 测试通过。Cobra/esbuild 的源码切片完全保持不变，只有关系和诊断变化，因此复用相同文档的索引向量进行后续对照。

## 最终组合与默认选择

快速检索加基础结构解析，在新语料的最终结果如下。对照为上节的原完整子问题重排加文本保底；两项改动共同影响结果。

| 仓库 | 原文本覆盖率 | 最终默认覆盖率 | 最终默认中位耗时 | 最终默认完整查询 |
| --- | ---: | ---: | ---: | ---: |
| Cobra | 80.83% | 87.5% | 2.027 s | 5/8 |
| Commander | 100% | 100% | 2.767 s | 8/8 |
| esbuild | 81.25% | 84.38% | 2.426 s | 13/16 |

同一快速引擎下启用类型关系，Cobra 覆盖率由 87.5% 提升至 91.67%，完整查询 5→6；esbuild 覆盖率由 84.38% 降至 81.25%，完整查询仍为 13。前者补齐英文帮助处理，后者丢失中文 watch 生命周期原本找到的一半证据。因此默认保留 `syntax`，需要更精确的静态关系时显式启用 `types`。这轮没有针对题目补规则。

共 56 次最终组合/类型对照全部完成，源码、行号、哈希和预算检查通过；类型模式的所有索引向量均按原始文档复用，新增 embedding 请求为零。配置默认值确定后，又验证显式类型模式生成的全部单元与已评测单元一致，默认语法模式的检索字段也一致。结果与默认选择见[最终对照记录](results/go-types-20261004.json)。这些小样本来自源码编写的开发题，仍保留逐题漏项。
