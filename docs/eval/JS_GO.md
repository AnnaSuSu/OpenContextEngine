# JavaScript 与 Go 结构解析

2026-10-04。新增 `.js`、`.jsx`、`.mjs`、`.cjs` 和 `.go` 结构适配，沿用代码单元、召回、重排和预算选择接口。配置、脚本及其他语言继续使用文本保底。

JavaScript 复用固定版本 `typescript@5.9.3` 的 Compiler API，支持 ESM、CommonJS、JSX、函数与方法，并在同一虚拟文件集合中绑定 JS/TS 导入和调用。跨 JS/TS 的关系重新映射到统一 ID；动态接收者和未知回调保留未解析记录。物理 CR/LF 行号与编译器字符偏移分别处理，Unicode 分隔符不会挪动引用位置。参见 [allowJs 官方说明](https://www.typescriptlang.org/tsconfig/allowJs.html)。

Go 使用官方 `go/parser` 提取函数、接收者方法、类型、语句边界和同符号续片。基础版本只连接可证明的直接函数调用与唯一的同包函数，局部同名变量、跨包选择器及动态方法不猜测。源码片段保持完整行、无重叠，并覆盖全部非空源码。参考 [Go parser 文档](https://pkg.go.dev/go/parser)。

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

Go 基础解析中，esbuild 的 `api.Context` 和 `ctx.Watch` 仍是未解析调用，构成进一步接入类型检查的具体依据。其中接口方法不能仅凭同名关联到某个实现。
