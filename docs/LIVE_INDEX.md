# 工作区索引与自动更新

常驻服务支持任意本地仓库的已保存文件。首次接入建立完整索引；后续按文件内容哈希检测变化，复用未变代码块的 embedding，后台构建新版本后一次切换。无需先提交 Git。

## 独立服务运行（源码安装）

当前支持 macOS / Linux，需要 Node.js 22.14+、Python 3.10+、Git；含 Go 文件时还需要 Go 编译器。模型使用配置的远程 embedding 和 reranker，不在本机加载模型。普通 MCP 用户按 [Quickstart](QUICKSTART.md) 安装并运行 `open-context-engine setup`，无需单独启动本节的 HTTP 服务。

```sh
npm ci
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# .env 中设置模型渠道和 OCE_API_KEY（至少 24 字符）
npm run serve-retrieval -- --root /absolute/path/to/repository --port 23505
```

npm 安装使用 `setup` 创建并保存的 Python 环境。源码运行可用 `OCE_PYTHON` 指定解释器；未指定时会查找源码目录的 `.venv` 等兼容路径，最后尝试 `python3`。Go 编译器可用 `OCE_GO_BINARY` 指定；选择 Go 类型分析使用 `OCE_LANGUAGE_OPTIONS='{"go":{"mode":"types"}}'`。默认仍是语法结构模式。

索引默认存放在 `~/.cache/opencontextengine/<仓库路径哈希>/`，可通过 `--state /outside/repository/index` 指定；已有安装会自动复用旧缓存目录。状态目录必须在源码目录之外，避免索引自己的输出。同一状态目录只允许一个写入进程。停止服务后删除整个状态目录即可清除源码副本和向量；历史向量会持续保留，以复用分支切换前的内容。

HTTP 服务命令 `serve-retrieval` 不传 `--root` 时保留原有冻结索引模式，供旧评测和服务使用。

MCP 启动命令 `npm run mcp` 不传 `--root` 时使用自动工作区模式：Agent 每次调用 `search_code` 或 `index_status` 都传入绝对路径 `directory_path`，首次访问启动独立的项目进程和索引，后续复用。多个项目的进程会保持运行，客户端断开时统一停止。路径按真实目录规范化，符号链接不会启动重复进程；并发首次访问同一项目只启动一次。进程退出后，下次访问会重新启动并读取持久索引。自动模式的 `--state` 是缓存基目录，各项目使用独立路径哈希子目录。

MCP 的 `--root` 继续固定一个项目，并拒绝切换到其他目录；`--connect` 继续连接已有服务，不接受 `directory_path`。模型配置优先级为进程环境变量 → `setup` 保存的用户配置 → OpenContextEngine 源码目录的 `.env`，不读取目标项目的 `.env`。

## 更新规则

- 默认每秒扫描一次 Git 跟踪文件及未被忽略的新文件；非 Git 目录按同样的文本准入规则扫描。以已保存到磁盘的内容为准，不读取编辑器未保存缓冲区。
- 连续变化合并 300 毫秒后再构建，可用 `OCE_POLL_SECONDS`、`OCE_DEBOUNCE_SECONDS` 调整。
- 新增、修改、删除、重命名、`git switch`、`git pull` 都通过内容差异处理。删除文件的片段和引用不会进入新版本。
- 文本文件按文件复用解析结果。Python、JS/TS、Go 的结构关系可能跨文件，当前保守地重分析发生变化的整个语言组；其他语言组复用。JS/TS 共享一组，Go 模块路径配置变化也会刷新解析。尚未实现编译器级的最小依赖失效范围。
- embedding 缓存键包含模型渠道、模型名、维度、修订号和完整的实际模型输入。仅行号变化而输入未变时复用向量；重命名改变了路径输入时重新编码。修改关系但模型输入未变，也无需重新编码。
- `EMBEDDING_MODEL`、`OCE_EMBEDDING_DIMENSIONS` 或渠道变化会使用新的向量缓存身份。相同模型名对应的权重更新时，增加 `OCE_EMBEDDING_REVISION`。历史评测使用 Qwen3-Embedding-4B / 1024 维；配置时必须填写实际服务返回的维度，不应直接沿用评测值。其他模型需支持当前源码检索输入格式并另行评测。
- 索引文件先写入独立版本目录，再原子替换版本指针；请求使用固定的内存版本。模型失败、语法错误或编辑过程中内容变化都不会覆盖正在使用的完整版本。

这是一种自动轮询增量同步，不是文件系统事件监听；大型仓库的扫描和结构重分析成本仍需单独验证。

## 查询一致性

`POST /search` 接受 `query`、`budget`、`trace` 和可选 `freshnessWaitMs`（默认 30 秒，最大 120 秒）。每次查询先扫描当前源码，等待对应索引；检索完成后再次核验文件哈希。成功结果带 `index.identity` 和 `freshness: verified-after-search`。

若源码在查询期间变化、更新失败或超过等待时间，返回 HTTP 503 和明确的索引状态，不返回旧源码作为当前结果。源码可能在响应之后继续被修改，Agent 编辑前仍应读取目标文件。

`GET /status` 使用与搜索相同的 Bearer 认证，返回 `starting / updating / ready / failed`、当前版本、变动文件数、复用量和最近错误类型。状态反映最近一次后台观察；搜索会额外主动检查。`GET /healthz` 只表示进程存活，不代表索引已就绪。

新增回归覆盖新增/修改/删除/重命名、行号变化的向量复用、分支内容恢复、持久缓存、跨文件引用刷新、空仓库、构建中修改、失败恢复、语法错误阻断旧结果及单写入者约束。
