# MCP 接入

RepoNerve 使用官方 TypeScript MCP SDK 的 stdio transport，提供两个工具：

- `search_code(query, budget=4000, freshnessWaitMs=30000)`：检索指定仓库的当前源码，返回文件路径、原始行号、证据片段和索引版本。
- `index_status()`：查看当前仓库、索引是否就绪、变动文件数、向量复用量和最近一次更新错误。

实现使用 [官方 SDK 的 stdio 与工具注册接口](https://ts.sdk.modelcontextprotocol.io/server)。模型调用仍在配置的远程服务执行。

## 一个客户端直接使用

先按[工作区索引说明](LIVE_INDEX.md)安装 Node/Python 依赖并配置远程模型。MCP 客户端的配置示例（适用于使用 `mcpServers` 配置项的客户端）：

```json
{
  "mcpServers": {
    "reponerve": {
      "command": "node",
      "args": [
        "/absolute/path/to/RepoNerve/scripts/mcp-reponerve.mjs",
        "--root",
        "/absolute/path/to/your-repository"
      ],
      "env": {
        "REPONERVE_PYTHON": "/absolute/path/to/RepoNerve/.venv/bin/python"
      }
    }
  }
}
```

路径应替换成自己的绝对路径。该入口读取 RepoNerve 根目录的 `.env`，进程环境变量优先。索引默认在 `~/.cache/reponerve/<仓库路径哈希>/`，也可附加 `--state /outside/repository/index`。

客户端启动 MCP 时会自动启动绑定该仓库的本机 HTTP worker，使用动态端口和认证密钥。首次索引在后台进行，MCP 可以立即响应工具发现；搜索会等待索引。关闭客户端、stdin EOF 或发送终止信号时，关联 worker 会退出。stdout 只发送 MCP 协议，日志写入 stderr。

`--root` 是启动时固定的目录，工具参数不能切换仓库。不同仓库可配置不同 MCP 实例。

## 多个客户端共用仓库

同一索引目录只允许一个写入者。多个客户端需要共用时，先启动一个独立常驻服务：

```sh
# .env 中配置 REPONERVE_API_KEY，至少 24 字符
npm run serve-retrieval -- --root /absolute/path/to/your-repository --port 23505
```

每个 MCP 客户端改用以下命令，并设置相同的服务密钥：

```json
{
  "command": "node",
  "args": ["/absolute/path/to/RepoNerve/scripts/mcp-reponerve.mjs", "--connect"],
  "env": {
    "REPONERVE_BASE_URL": "http://127.0.0.1:23505",
    "REPONERVE_API_KEY": "your-service-key"
  }
}
```

`--connect` 只连接服务，关闭 MCP 不会停止共享服务。连接远程 worker 时使用 HTTPS 或明确的本机 SSH 转发。MCP 的搜索工具要求服务使用 `--root` 启动的实时索引，不会把旧的冻结评测索引当成当前工作区。

## 编辑时的行为

正常保存文件即可；无需手动重建或先提交 Git。默认每秒检测一次变化，合并 300 毫秒内的连续编辑。搜索还会主动核对当前文件哈希：

1. 已同步：直接检索完整版本。
2. 正在更新：在 `freshnessWaitMs` 内等待，默认 30 秒，最大 120 秒。大型初次索引可先调用 `index_status` 查看状态。
3. 解析/模型失败、等待超时、查询期间源码变化：工具返回 `isError: true` 和明确原因，Agent 可以查看状态或重试。

只处理已保存的文件；新代码若尚未保存，索引无法读取。默认排除规则、模型变更、持久缓存删除及结构重分析范围见[自动更新说明](LIVE_INDEX.md)。

## 验证

```sh
npm test
REPONERVE_GO_BINARY=/path/to/go .venv/bin/python -m unittest discover -s tests -p '*_test.py'
# 下面会调用已配置的真实远程模型，并在 .pilot-state/mcp-smoke 下保存结果
node scripts/smoke-mcp.mjs
```

自动测试使用官方 MCP 客户端进行真实 stdio 握手、工具发现、输入校验、保存后检索及更新失败测试；模型端使用确定性协议桩，仅用于检查服务行为。

2026-10-04（北京时间）另外完成一次真实远程模型冒烟：首次建索引并查询、修改 Python 文件后只编码 1 个片段并复用 2 个片段、删除 JS 文件后移除相应证据、关闭并重启 MCP 后恢复同一索引版本。完整记录见 [MCP 冒烟结果](eval/results/mcp-live-smoke-20261004.json)。它验证使用链路和更新正确性，不是召回质量基准。含索引等待的这三次查询耗时分别为 3.61、5.29、3.74 秒，不能与预建索引的检索延迟直接比较。
