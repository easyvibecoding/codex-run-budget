# Codex Run Budget

**为 Codex Task 和子代理提供共享 token 预算护栏及本地用量信息。**

[English](README.md) · [繁體中文](README.zh-Hant.md) · [简体中文](README.zh-Hans.md) · [日本語](README.ja.md)

![Codex Run Budget 社交媒体预览图：父 Task 和子代理共享同一份预算](assets/social-preview.png)

Codex Run Budget 是在本地运行的 Codex 插件，让**一个父 Task 及其子代理共享同一份预算**。它也提供自动回合记录、指定范围的用量报告、Codex 原生账号配额观测，以及选用的工作流程和 `codex exec` 活动查看。预算判断由 Python 和 SQLite 账本依确定性规则执行；报告和观测功能本身不会启动预算。

本项目是独立社区作品，受到 [Microsoft TokenOps](https://commandline.microsoft.com/tokenops-real-time-run-scoped-cost-control-ai-agents/) 运行范围治理理念启发。它不是 OpenAI 或 Microsoft 产品，也不是计费工具，也不保证零超额。运行时只需 Python 3.10+ 和标准库。

[快速开始](#快速开始) · [功能](#功能) · [按任务查找命令](#按任务查找命令) · [执行和限制](#执行和限制) · [文档](#文档)

## 快速开始

从本 repository 的 Codex marketplace 安装：

```sh
codex plugin marketplace add https://github.com/easyvibecoding/codex-run-budget
codex plugin add codex-run-budget@codex-run-budget
```

在 Codex CLI 中打开 `/hooks`，检查并信任插件的 hook 定义，接着开始**新的 Task**。已安装或启用的插件若有未受信任或已变更的 hook，Codex 可能跳过那些 hook。

要启动共享预算，请在 **Task 消息的最开头**加入控制语句：

```text
run-budget:start tokens=100k

实现该功能并运行相关检查。
```

预算上限涵盖父 Task 的整个 session 树。启动预算会建立新的审计 epoch，并保留之前的 epoch 记录。请设置至少足以涵盖一次完整模型请求的上限；并非每次模型请求前都有 hook。

```text
run-budget:status
run-budget:halt reason="operator pause"
run-budget:resume tokens=200k
run-budget:off
```

`resume tokens=` 设置新的绝对上限，且必须高于已观测用量。消息后段引用的控制语句不会启动命令。[控制语法、政策顺序和状态](docs/DESIGN.md) · [检查预算执行记录](#检查预算执行记录)。

即使没有启动预算，自动用量卡默认仍会显示。符合条件的子代理可在自己的页面显示用量卡；父 Task 的卡片则单列已观测的后代用量小计。两处以相同的哈希 `@selector` 对应这个子代理。[回合记录](docs/AUTO_REPORTS.md)。

## 功能

| 范围 | 功能 | 边界 |
| --- | --- | --- |
| 共享执行预算 | 以父 Task 的 `session_id` 和同一个 SQLite 账本处理父 Task 及子代理的 hook；对 token、工具、代理、进行中的操作、重复调用和输出应用护栏，先 STEER 再 HALT。 | 仅在受支持的 hook 边界执行。 |
| 自动回合记录 | 父 Task 与符合条件的子代理可各自在自己的页面显示结束前用量卡，并保存 Stop／SubagentStop 记录；有限次的完成检查可另存后续修订。 | 每张卡都是当下快照；计数或谱系证据不足时仍标为部分数据或未知。 |
| 指定范围的 Task 报告 | 选择单一 Task、其代理树或明确指定的时间范围；显示已观测的 token、历史设置、缓存读取占比和设置变动信号。 | 跨 Task 的时间范围须明确指定；报告不会启动预算。 |
| 原生配额仪表 | 读取账号配额和已保存快照、本地 Task 设置历史、注明日期的费率，以及 Standard/Fast 配额情境。 | 账号百分比和估算配额不是 Task 费用或实际账单。 |
| 诊断 | 审计指定的本地会话记录、调查有上限的近期 Task 群，并用游标记录明确要求的工作流程观测。 | 观测不代表程序仍在执行、工作已完成或持续监控。 |
| 项目 exec 活动 | 列出或监看单一工作目录内额外的 `codex exec` session；选用的启动器可记录暂时性的调用记录。 | exec 调用用量和原生子代理谱系、共享预算账本分开。 |
| 实验性配对项目审查 | 用户登记命名的 Codex 项目根目录配对。受信任的 `Stop` hook 可在另一项目开启审查 Task，并绑定两个 Task 以供后续摘要转送。一个项目可属于多组配对。 | 全局和每组配对各有开关；没有定时轮询。仅远程发生的变更需要等待后续配对 Task 或手动扫描。 |
| 签名运行时更新 | 为新 Task 启用兼容且由发布者签名的运行时和 CLI 变更；现有 Task 继续使用原本固定的版本。 | 新 hook、入口、密钥或插件结构仍须照一般安装和信任流程处理。 |

本 README 提供四种语言。供人阅读的卡片、报告、菜单和摘要内建九种语言；命令、JSON、状态码、原始名称和模型 ID 保持原样。[语系说明](docs/LOCALIZATION.md)。

## 按任务查找命令

以下命令从 repository checkout 执行。若在已安装的插件目录，改用 `python3 scripts/run_budget.py`。[完整指南索引](docs/README.md)。

### 检查预算执行记录

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py list
python3 plugins/codex-run-budget/scripts/run_budget.py show latest --json
python3 plugins/codex-run-budget/scripts/run_budget.py events latest
```

账本保存计数、政策决策、时间及经哈希处理的谱系标识符；不刻意保存 prompt 或工具内容。[设计](docs/DESIGN.md) · [安全](SECURITY.md)。

### 读取或控制自动记录

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py auto-report status
python3 plugins/codex-run-budget/scripts/run_budget.py auto-report list
python3 plugins/codex-run-budget/scripts/run_budget.py auto-report disable
python3 plugins/codex-run-budget/scripts/run_budget.py auto-report enable
```

明确设置为停用会在升级后保留。若只想纳入超过 300 秒的回合，使用 `auto-report enable --threshold-seconds 300`；默认阈值为零。`SubagentStart` 以子代理自己的 Task 和回合标识建立卡片；`SubagentStop` 结算其记录，并提供祖先卡片使用的有界证据。Stop 可能早于最终用量记录写入；仅处理报告的 worker 可检查该回合是否完成，并另存修订。原本的记录和结束前卡片保持不变。Run Budget 现有的 `SubagentStart` hook 定义在兼容的签名运行时更新中不变，因此现有原生信任仍有效；新 Task 才会加载更新后的运行时。[记录生命周期](docs/AUTO_REPORTS.md)。

### 报告指定 Task 和代理

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py report
python3 plugins/codex-run-budget/scripts/run_budget.py report tasks --limit 10
python3 plugins/codex-run-budget/scripts/run_budget.py report task --windows 24h
python3 plugins/codex-run-budget/scripts/run_budget.py report agents
python3 plugins/codex-run-budget/scripts/run_budget.py report tree --thread TASK_SELECTOR --windows 24h
python3 plugins/codex-run-budget/scripts/run_budget.py report window --all-tasks --windows 5h
```

单独执行 `report` 只显示菜单，不执行扫描。`task` 和 `window` 默认指向当前 Task；`report task` 只选择该 Task，即使它是子代理。`agents` 是元数据查看；选定父 Task 的 `tree` 才明确包含后代代理用量。子代理自己的总量可能已包含在父 Task 的树形小计，请勿再次相加。跨 Task 分析须指定 `--all-tasks` 和时间范围。报告可保存私有的 Markdown、HTML 或 JSON；除非指定 `--full`，简短 CLI 输出只会连到文件。在 Codex 中，也可使用内建的 `usage-task`、`usage-agents`、`usage-window` skill。0.18.0 版报告新增各时间范围的缓存读取占比、请求数，以及已观测到的模型、推理强度或服务等级变动，不推断缓存未命中的原因。[范围和证据](docs/REPORTS.md)。

### 读取原生账号配额

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py meter --no-save
python3 plugins/codex-run-budget/scripts/run_budget.py meter snapshot
python3 plugins/codex-run-budget/scripts/run_budget.py meter report
python3 plugins/codex-run-budget/scripts/run_budget.py meter tasks --days 1
python3 plugins/codex-run-budget/scripts/run_budget.py meter rates
python3 plugins/codex-run-budget/scripts/run_budget.py meter estimate --days 1
```

`meter` 通过已登录的 Codex 账号连接读取原生配额；`--no-save` 不保存快照。`tasks` 摘要有上限的本地历史，不会重新查询配额。`rates` 是注明日期的参考数据；`estimate` 是 Standard/Fast token 配额的假设情境，并非实际扣款。原生配额百分比属于整个账号，绝不从 token 总数分摊到单一 Task。[配额仪表和控制](docs/METER.md) · [测量机制](docs/METER_MECHANICS.md)。

### 调查活动

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py survey
python3 plugins/codex-run-budget/scripts/run_budget.py audit /path/to/synthetic-rollout.jsonl
python3 plugins/codex-run-budget/scripts/run_budget.py workflow
python3 plugins/codex-run-budget/scripts/run_budget.py workflow observe --thread TASK_SELECTOR
python3 plugins/codex-run-budget/scripts/run_budget.py exec-activity list --project "$PWD"
```

`survey` 读取有上限的近期本地 Task 群；`audit` 只读取明确提供的会话记录路径。`workflow-observe` skill 可从工作描述解析到确切 Task，并生成私有、只读的变更报告。`workflow observe` 默认观测当前 Task；纳入后代代理需使用 `--include-agents`，之后比较可用返回的 `--after` 游标。这些观测都不会启动 daemon 或定期自动化。`exec-activity watch` 只在前景执行；`exec-activity run` 是选用的启动器，会执行指定的 Codex 调用。[近期调查](docs/SURVEY.md) · [审计](docs/AUDIT.md) · [工作流程观测](docs/WORKFLOW_OBSERVATIONS.md) · [Exec 活动](docs/EXEC_ACTIVITY.md)。

### 审查配对项目变更

```sh
python3 plugins/codex-run-budget/scripts/paired_review.py pair --id web-api /path/to/web /path/to/api
python3 plugins/codex-run-budget/scripts/paired_review.py feature on
python3 plugins/codex-run-budget/scripts/paired_review.py enable web-api
python3 plugins/codex-run-budget/scripts/paired_review.py pairs
python3 plugins/codex-run-budget/scripts/paired_review.py scan
```

此实验性功能在新安装及新登记的配对中默认关闭。每组配对有各自的游标、待审查项目及一对一 Task 绑定。受信任的 `Stop` hook 检查已启用且包含当前项目的配对；`main` 出现新变更范围时，会通过 Codex App 要求另一项目开启只读审查 Task。后续 Stop 会将简短摘要转送到同一个已绑定 Task，并防止循环转发。手动 `scan` 只会将远程变更排入待办，不会唤醒模型。既有配对保留先前状态和启用设置。[Run Budget 和 Usage Reports 的特定契约](docs/CROSS_REPO_REVIEW.md) · [设置、开关和恢复](docs/PAIRED_REVIEW_AUTOMATION.md)。

### 检查或更新已安装软件

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py updates check --refresh --cwd "$PWD"
python3 plugins/codex-run-budget/scripts/publisher_updates.py status
```

`updates check` 读取已安装**软件包**的版本和原生 hook 信任状态。发布者命令读取当前启用的**签名运行时**版本；在已安装的插件目录中也接受 `on`、`off`、`update` 和 `rollback`。例行兼容的签名更新会保留 hook 定义。结构变更仍须经过一般插件更新、`/hooks` 检查及新 Task 流程；若必须更新软件包，保留辅助程序会保护旧缓存版本。[签名更新](docs/SIGNED_UPDATES.md) · [信任提醒](docs/UPDATE_NOTICES.md) · [升级安全](docs/UPGRADE_SAFETY.md)。

## 执行和限制

Governor 在 SQLite transaction 内对齐已观测的会话记录计数并执行确定性政策。父 Task 的 `session_id` 是共享执行标识符；hook 重试及并行代理准入具有幂等性。可设置的 start 控制语句支持 `tokens`、`warn`、`block_agents`、`tools`、`agents`、`inflight`、`output`、`repeat_steer`、`repeat_halt` 和 `fail`；未知或重复选项会被拒绝。[设置和执行顺序](docs/DESIGN.md) · [可靠性强化](docs/HARDENING.md)。

`UserPromptSubmit` 可阻挡新的用户回合；观测到 HALT 后，`PreToolUse` 可阻挡受支持的本地工具调用。Codex 并未在每次模型请求前提供插件 hook；hosted tools 可能跳过本地工具 hook。会话记录中的 token 计数可能在模型或工具动作后才到达，因此账本观测到 HALT 前，单一回合仍可能超出预算。输出检查发生在执行后，无法撤销副作用。一旦观测到 HALT，后续受支持的调用及新回合会遭拒，直到 resume 或 off。这些是护栏，不是通用拦截、精确计费或零超额保证。[已安装环境的证据和限制](docs/VALIDATION.md)。

## 隐私和本地数据

状态默认存于 `~/.codex/run-budget/`；可用 `CODEX_RUN_BUDGET_HOME` 指向其他私有目录。账本不刻意记录 prompt、命令、工具内容或会话记录本文，只保存允许的计数、状态、时间戳及经哈希处理的标识符。私有的人类可读报告可能显示原生 Task 和代理名称；请勿将实际导出档加入 Git。预算治理及离线诊断不会上传报告。原生配额仪表使用既有的 Codex 账号连接；签名更新会取得公开 release 文件。[安全政策](SECURITY.md)。

## 文档

[文档索引](docs/README.md) 整理使用指南、测量语义、更新和信任控制、架构及注明日期的验证。[贡献指南](CONTRIBUTING.md) 列出检查和合成测试数据。[变更记录](CHANGELOG.md) 记录版本。

MIT © EasyVibeCoding contributors。[先前技术和致谢](NOTICE.md) · [第三方声明](THIRD_PARTY_NOTICES.md)。
