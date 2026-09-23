# Codex Run Budget

**为 Codex Task 和子代理提供共享 token 预算护栏及本地用量信息。**

[English](README.md) · [繁體中文](README.zh-Hant.md) · [简体中文](README.zh-Hans.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Deutsch](README.de.md) · [Français](README.fr.md) · [Español](README.es.md) · [Português](README.pt.md)

Codex Run Budget 是在本地运行的 Codex 插件，让一个父 Task 及其所有子代理共用同一份预算。它还提供每轮用量记录、限定范围的 Task 报告、账户额度观察，以及可选的工作流和 `codex exec` 活动视图。预算决策由 Python 和 SQLite 按确定性规则执行；查看报告不会自动启动预算。

## 主要功能

- **共享预算：**以父 Task 的 `session_id` 标识一次运行，汇总子代理，并在受支持的 hook 边界执行 STEER 和 HALT。
- **用量记录与报告：**查看自动生成的每轮卡片、单个 Task、代理树或明确指定时间范围内的观测数据；证据缺失时保留部分或未知状态。
- **账户额度与活动：**读取 Codex 原生账户额度，并按需观察工作流和项目范围的 `codex exec` 活动。账户百分比不是单个 Task 的费用。
- **本地与隐私：**预算账本只保存允许的计数、状态、时间和哈希标识，不刻意保存 prompt、命令或工具内容。运行时仅需 Python 3.10+ 标准库。

## 快速开始

```sh
codex plugin marketplace add https://github.com/easyvibecoding/codex-run-budget
codex plugin add codex-run-budget@codex-run-budget
```

在 Codex CLI 的 `/hooks` 中检查并信任插件 hook，然后启动**新的 Task**。在 Task 消息的开头加入：

```text
run-budget:start tokens=100k

Implement the feature and run the relevant checks.
```

使用 `run-budget:status` 查看状态，或用 `run-budget:halt reason="operator pause"`、`run-budget:resume tokens=200k`、`run-budget:off` 控制预算。[完整命令与示例](README.md#commands-by-task) · [设计与规则](docs/DESIGN.md)。

## 执行边界

Codex 并未在每次模型请求之前提供插件 hook；hosted tools 也可能绕过本地工具 hook。用量计数可能在操作后才到达，因此单轮可能在观测到 HALT 前超过预算。这是护栏，而非精确计费、零超额或通用拦截机制。[安装环境验证与限制](docs/VALIDATION.md)。

[英文完整 README](README.md) · [文档索引](docs/README.md) · [语言说明](docs/LOCALIZATION.md) · [安全政策](SECURITY.md)

本项目是独立社区作品，并非 OpenAI 或 Microsoft 产品。MIT © EasyVibeCoding contributors。
