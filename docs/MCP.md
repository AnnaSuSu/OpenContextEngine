# MCP 接入

OpenContextEngine 使用官方 TypeScript MCP SDK 的 stdio transport，提供两个工具：

- `search_code(directory_path, query, budget=4000, freshnessWaitMs=30000)`：检索指定仓库的当前源码，返回文件路径、原始行号、证据片段和索引版本。
- `index_status(directory_path)`：查看项目索引是否就绪、变动文件数、向量复用量和最近一次更新错误。

实现使用 [官方 SDK 的 stdio 与工具注册接口](https://ts.sdk.modelcontextprotocol.io/server)。

默认自动工作区模式下，两个工具都需要助手传入项目绝对路径 `directory_path`。模型调用在配置的远程向量和重排服务执行，不需要额外的 GPT 接口。

## 一个客户端直接使用

先按 [Quickstart](QUICKSTART.md) 安装并运行 `open-context-engine setup`。以下示例适用于接受 `mcpServers` JSON、且能通过 `PATH` 找到 CLI 的客户端；Codex 的 TOML 和绝对路径写法见[客户端配置说明](QUICKSTART.md#client-setup-notes)。

```json
{
  "mcpServers": {
    "open-context-engine": {
      "command": "open-context-engine",
      "args": ["mcp"]
    }
  }
}
```

配置优先级为：进程环境变量 → `setup` 保存的用户配置 → OpenContextEngine 源码目录的 `.env`。不会读取被检索项目的 `.env`。索引默认在 `~/.cache/opencontextengine/<仓库路径哈希>/`，也可附加 `--state /outside/repository/index`。

默认不固定项目。助手首次传入一个项目路径时，服务按需启动该项目的本机 HTTP worker，使用动态端口和认证密钥；后续请求复用 worker 和索引。同一 MCP 会话可以搜索多个项目。首次索引在后台进行，搜索等待索引同步；可以先调用 `index_status` 查看进度。

如需固定一个项目，在 `args` 中追加 `"--root", "/absolute/path/to/your-repository"`。此时工具可以省略 `directory_path`；如果提供，必须指向同一个项目。

关闭客户端、stdin EOF 或发送终止信号时，关联 worker 会退出。stdout 只发送 MCP 协议，日志写入 stderr。

## 多个客户端共用仓库

这是可选的源码安装方式。同一索引目录只允许一个写入者；多个客户端要同时搜索同一仓库时，可先从 OpenContextEngine 源码目录启动一个独立常驻服务：

```sh
# .env 中配置 OCE_API_KEY，至少 24 字符
npm run serve-retrieval -- --root /absolute/path/to/your-repository --port 23505
```

每个 MCP 客户端改用以下命令，并设置相同的服务密钥：

```json
{
  "command": "open-context-engine",
  "args": ["mcp", "--connect"],
  "env": {
    "OCE_BASE_URL": "http://127.0.0.1:23505",
    "OCE_API_KEY": "replace-with-at-least-24-random-characters"
  }
}
```

`--connect` 只连接服务，工具参数应省略 `directory_path`，关闭 MCP 不会停止共享服务。连接远程 worker 时使用 HTTPS 或明确的本机 SSH 转发。MCP 的搜索工具要求服务使用 `--root` 启动的实时索引，不会把旧的冻结评测索引当成当前工作区。

## 编辑时的行为

正常保存文件即可；无需手动重建或先提交 Git。默认每秒检测一次变化，合并 300 毫秒内的连续编辑。搜索还会主动核对当前文件哈希：

1. 已同步：直接检索完整版本。
2. 正在更新：在 `freshnessWaitMs` 内等待，默认 30 秒，最大 120 秒。大型初次索引可先调用 `index_status` 查看状态。
3. 解析/模型失败、等待超时、查询期间源码变化：工具返回 `isError: true` 和明确原因，Agent 可以查看状态或重试。

只处理已保存的文件；新代码若尚未保存，索引无法读取。默认排除规则、模型变更、持久缓存删除及结构重分析范围见[自动更新说明](LIVE_INDEX.md)。

## 验证

以下命令面向源码开发和维护，需先安装开发依赖及测试用 Python 环境。

```sh
npm test
OCE_GO_BINARY=/path/to/go .venv/bin/python -m unittest discover -s tests -p '*_test.py'
# 下面会调用已配置的真实远程模型，并在 .pilot-state/mcp-smoke 下保存结果
node scripts/smoke-mcp.mjs --auto-workspace
```

自动测试使用官方 MCP 客户端进行真实 stdio 握手、工具发现、输入校验、保存后检索及更新失败测试；模型端使用确定性协议桩，仅用于检查服务行为。

2026-10-04（北京时间）另外完成一次真实远程模型冒烟：首次建索引并查询、修改 Python 文件后只编码 1 个片段并复用 2 个片段、删除 JS 文件后移除相应证据、关闭并重启 MCP 后恢复同一索引版本。完整记录见 [MCP 冒烟结果](eval/results/mcp-live-smoke-20261004.json)。它验证使用链路和更新正确性，不是召回质量基准。含索引等待的这三次查询耗时分别为 3.61、5.29、3.74 秒，不能与预建索引的检索延迟直接比较。
