<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/logo-lockup-dark.svg">
    <img src="assets/brand/logo-lockup.svg" alt="OpenContextEngine" width="660">
  </picture>
  <p><strong>为 AI 编程助手提供精准的代码上下文。</strong></p>
  <p>跨文件查找相关代码，追踪代码之间的联系，让助手的回答有据可查。</p>
  <p>
    <a href="docs/BENCHMARKS.md#seven-method-comparison"><img src="https://img.shields.io/badge/dev_evidence_coverage-94.79%25-23875b?style=flat-square" alt="开发集证据覆盖率：94.79%"></a>
    <a href="docs/BENCHMARKS.md#seven-method-comparison"><img src="https://img.shields.io/badge/median_retrieval-1.73_s-23875b?style=flat-square" alt="检索耗时中位数：1.73 秒"></a>
    <a href="docs/BENCHMARKS.md#engineering-validation"><img src="https://img.shields.io/badge/verified_tests-107-23875b?style=flat-square" alt="107 项已验证测试"></a>
    <a href="docs/QUICKSTART.md"><img src="https://img.shields.io/badge/MCP-stdio-193c34?style=flat-square" alt="通过 stdio 接入 MCP"></a>
  </p>
  <p><a href="#快速开始">快速开始</a> · <a href="docs/BENCHMARKS.md">评测报告</a> · <a href="docs/QUICKSTART.md">MCP 配置</a> · <a href="README.md">English</a> | <strong>简体中文</strong></p>
</div>

OpenContextEngine 是一个**可自行部署、面向 AI 编程助手的代码上下文引擎**。通过 MCP 接入后，助手可以借助它理解陌生代码库、定位实现，以及查找修复问题或开发功能所需的相关代码。

它为你的工作目录建立索引，并跟随已保存的代码变化自动更新。面对自然语言任务，它结合语义检索、关键词检索、代码关系和重排，在指定的上下文预算内返回相关源码片段、文件路径和行号。

## 为什么选择 OpenContextEngine

- **用自然语言查代码。** 描述你要找的行为，检索其实现及跨文件的相关代码。
- **理解代码结构。** 支持 Python、TypeScript、JavaScript 和 Go 的结构分析，其他语言、配置文件和脚本使用文本检索保底。
- **索引跟随代码更新。** 保存修改、删除文件和切换分支后自动同步。复用未变化的向量，更新未完成时保留完整的旧索引。
- **通过 MCP 跨项目使用。** 助手传入项目路径，按需启动并复用索引。`search_code` 检索代码证据，`index_status` 查看同步状态。

## 评测结果

![所需证据覆盖率与实测查询耗时](assets/benchmarks/method-comparison.svg)

**所需证据覆盖率 94.79% · 检索耗时中位数 1.73 秒 · 80 次查询中有 69 次覆盖全部所需证据。** 七种引擎、四个仓库，统一采用 4,000 token 的输出预算。在这组内部开发评测中，OpenContextEngine 保留的所需证据最多。

评测使用可选的批量重排接口。共 40 个基于源码设计的任务，每个任务分别用中文和英文提问。覆盖率衡量源码证据的保留情况，不代表编程助手完成任务的成功率。开源工具记录原生检索耗时，ACE 记录 SDK 客户端调用耗时。[完整对比、配置和逐条查询结果 →](docs/eval/METHOD_COMPARISON.md)

## 快速开始

需要 **macOS 或 Linux**、Node.js 22.14+、Python 3.10+、Git，以及已配置好的向量和重排服务。分析 Go 仓库还需要 Go 1.22+。

通过 npm 安装，展开你所用客户端的教程即可。同一台机器、同一用户下的多个客户端可以共用模型配置。下方链接的详细技术文档目前为英文。

<details open>
<summary><strong>Codex：安装、接入与搜索</strong></summary>

**1. 安装 CLI**

已安装 Codex CLI 后，执行：

```sh
npm install -g open-context-engine
```

**2. 配置模型接口**

```sh
open-context-engine setup
```

依次填写向量和重排服务的基础地址、API Key、模型名，以及向量维度。安装向导会自动安装隔离的 Python 依赖并保存配置。默认重排使用普通 `/rerank` 接口。[接口填写示例 →](docs/QUICKSTART.md#2-shared-model-configuration)

**3. 添加 MCP 服务**

```sh
codex mcp add open-context-engine -- open-context-engine mcp
codex mcp get open-context-engine
```

第二条命令用于检查已保存的配置。以上命令要求客户端能通过 `PATH` 找到 `open-context-engine`。桌面端或源码安装请参考[绝对路径配置](docs/QUICKSTART.md#client-setup-notes)。添加后，重启正在运行的 Codex 客户端。

**4. 搜索项目代码**

```sh
cd /path/to/your-project
codex
```

向 Codex 提问：

> 使用 open-context-engine 的 search_code 工具，解释当前项目的核心功能，并指出主要入口、相关文件路径和行号。

Codex 会通过 `directory_path` 传入项目的绝对路径。首次请求会启动索引；如果还在构建，让 Codex 调用 `index_status` 检查进度，待就绪后重试。后续搜索复用索引，保存代码后自动更新。

</details>

<details>
<summary><strong>Claude Code：安装、接入与搜索</strong></summary>

**1. 安装 CLI**

已安装 Claude Code 后，执行：

```sh
npm install -g open-context-engine
```

**2. 配置模型接口**

```sh
open-context-engine setup
```

依次填写向量和重排服务的基础地址、API Key、模型名，以及向量维度。安装向导会自动安装隔离的 Python 依赖并保存配置。如果已经为 Codex 完成配置，可以跳过这一步，直接复用。[接口填写示例 →](docs/QUICKSTART.md#2-shared-model-configuration)

**3. 添加 MCP 服务**

```sh
claude mcp add --transport stdio --scope user open-context-engine -- open-context-engine mcp
```

`--scope user` 让服务在你的各个项目中都可用。如果需要团队共用的项目级配置，在该项目目录运行命令，并将 `--scope user` 改为 `--scope project`。以上命令要求客户端能通过 `PATH` 找到 `open-context-engine`；绝对路径写法见[客户端配置说明](docs/QUICKSTART.md#client-setup-notes)。添加后，重启正在运行的 Claude Code 会话。

**4. 搜索项目代码**

```sh
cd /path/to/your-project
claude
```

输入 `/mcp` 检查连接，然后提问：

> 使用 open-context-engine 的 search_code 工具，解释当前项目的核心功能，并指出主要入口、相关文件路径和行号。

Claude 会通过 `directory_path` 传入项目的绝对路径。首次请求会启动索引；如果还在构建，让 Claude 调用 `index_status` 检查进度，待就绪后重试。后续搜索复用索引，保存代码后自动更新。

</details>

<details>
<summary>其他 MCP 客户端</summary>

[安装并完成初始化](docs/QUICKSTART.md#1-install)后，运行 `open-context-engine mcp-config`，将输出配置转换为客户端支持的格式。对于接受 `mcpServers` JSON 且能通过 `PATH` 找到已安装命令的客户端，可以使用：

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

助手通过 `directory_path` 传入当前项目的绝对路径。如果只搜索固定项目，在 `args` 中追加 `"--root", "/absolute/path/to/your-repository"`。

</details>

[模型配置、问题排查和索引更新机制 →](docs/QUICKSTART.md)

## 进一步了解

[评测报告](https://github.com/AnnaSuSu/OpenContextEngine/blob/main/docs/BENCHMARKS.md) · [原始评测数据](https://github.com/AnnaSuSu/OpenContextEngine/tree/main/docs/eval/results) · [检索引擎源码](https://github.com/AnnaSuSu/OpenContextEngine/tree/main/src/retrieval)

## 许可证

[MIT](LICENSE) © 2026 AnnaSuSu。

## 致谢

感谢 [LINUX DO](https://linux.do/) 社区。
