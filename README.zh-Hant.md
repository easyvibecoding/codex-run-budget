# Codex Run Budget

**為 Codex Task 與子代理提供共用 token 預算護欄及本機用量資訊。**

[English](README.md) · [繁體中文](README.zh-Hant.md) · [简体中文](README.zh-Hans.md) · [日本語](README.ja.md)

![Codex Run Budget 社群預覽圖：父 Task 與子代理共用一份預算](assets/social-preview.png)

Codex Run Budget 是在本機運作的 Codex 外掛，讓**一個父 Task 與其子代理共用同一份預算**。它也提供自動回合紀錄、指定範圍的用量報告、Codex 原生帳號額度觀測，以及選用的工作流程與 `codex exec` 活動檢視。預算判斷由 Python 與 SQLite 帳本依確定性規則執行；報告與觀測功能本身不會啟動預算。

本專案是獨立社群作品，受到 [Microsoft TokenOps](https://commandline.microsoft.com/tokenops-real-time-run-scoped-cost-control-ai-agents/) 執行範圍治理概念啟發。它不是 OpenAI 或 Microsoft 產品，也不是計費儀表或零超額保證。執行時只需 Python 3.10+ 與標準函式庫。

[快速開始](#快速開始) · [功能](#功能) · [依任務選擇指令](#依任務選擇指令) · [執行與限制](#執行與限制) · [文件](#文件)

## 快速開始

從本 repository 的 Codex marketplace 安裝：

```sh
codex plugin marketplace add https://github.com/easyvibecoding/codex-run-budget
codex plugin add codex-run-budget@codex-run-budget
```

在 Codex CLI 開啟 `/hooks`，檢查並信任外掛的 hook 定義，接著開始**新的 Task**。已安裝或啟用的外掛若有未受信任或已變更的 hook，Codex 可能略過那些 hook。

要啟動共用預算，請在 **Task 訊息的最開頭**加入控制行：

```text
run-budget:start tokens=100k

實作功能並執行相關檢查。
```

預算上限涵蓋父 Task 的整個 session 樹。啟動預算會建立新的稽核 epoch，並保留之前的 epoch 紀錄。請設定至少足以涵蓋一次完整模型請求的上限；並非每次模型請求前都有 hook。

```text
run-budget:status
run-budget:halt reason="operator pause"
run-budget:resume tokens=200k
run-budget:off
```

`resume tokens=` 設定新的絕對上限，且必須高於已觀測用量。訊息後段引用的控制行不會啟動指令。[控制語法、政策順序與狀態](docs/DESIGN.md) · [檢查預算執行紀錄](#檢查預算執行紀錄)。

即使沒有啟動預算，自動用量卡預設仍會顯示。[回合紀錄](docs/AUTO_REPORTS.md)。

## 功能

| 範圍 | 功能 | 邊界 |
| --- | --- | --- |
| 共用執行預算 | 以父 Task 的 `session_id` 與同一份 SQLite 帳本處理父 Task 及子代理的 hook；對 token、工具、代理、執行中作業、重複呼叫與輸出套用護欄，先 STEER 再 HALT。 | 僅在受支援的 hook 邊界執行。 |
| 自動回合紀錄 | 可在結束前顯示行內用量卡，並在本機儲存 Stop 紀錄；有限次的完成檢查可另存後續修訂。 | 行內卡是當下快照；缺少的證據仍標為部分資料。 |
| 指定範圍的 Task 報告 | 選擇單一 Task、其代理樹或明確指定的時間範圍；顯示已觀測 token、歷史設定、快取讀取占比與設定變動訊號。 | 跨 Task 的時間範圍須明確指定；報告不會啟動預算。 |
| 原生額度儀表 | 讀取帳號額度與已儲存快照、本機 Task 設定歷史、附日期的費率，以及 Standard/Fast 額度情境。 | 帳號百分比與估算額度不是 Task 費用或實際帳單。 |
| 診斷 | 稽核指定的本機逐字紀錄、調查有界限的近期 Task 群，並用游標記錄明確要求的工作流程觀測。 | 觀測不代表程序仍在執行、工作已完成或持續監控。 |
| 專案 exec 活動 | 列出或監看單一工作目錄內額外的 `codex exec` session；選用的啟動器可記錄暫時性的呼叫紀錄。 | exec 呼叫用量與原生子代理譜系、共用預算帳本分開。 |
| 實驗性配對專案審查 | 使用者登錄具名的 Codex 專案根目錄配對。受信任的 `Stop` hook 可在另一專案開啟審查 Task，並綁定兩個 Task 以供後續摘要轉送。一個專案可屬於多組配對。 | 全域與每組配對各有開關；沒有定時輪詢。只有遠端發生的變更，需等後續配對 Task 或手動掃描。 |
| 簽章執行環境更新 | 為新 Task 啟用相容且由發布者簽章的執行環境與 CLI 變更；現有 Task 繼續使用原本釘選的版本。 | 新 hook、入口、金鑰或外掛結構仍須照一般安裝與信任流程處理。 |

本 README 提供四種語言。人可閱讀的卡片、報告、選單與摘要內建九種語言；指令、JSON、狀態碼、原生名稱與模型 ID 保持原樣。[語系說明](docs/LOCALIZATION.md)。

## 依任務選擇指令

以下指令從 repository checkout 執行。若在已安裝的外掛目錄，改用 `python3 scripts/run_budget.py`。[完整指南索引](docs/README.md)。

### 檢查預算執行紀錄

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py list
python3 plugins/codex-run-budget/scripts/run_budget.py show latest --json
python3 plugins/codex-run-budget/scripts/run_budget.py events latest
```

帳本保存計數、政策決策、時間及經雜湊處理的譜系識別碼；不刻意保存 prompt 或工具內容。[設計](docs/DESIGN.md) · [安全](SECURITY.md)。

### 讀取或控制自動紀錄

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py auto-report status
python3 plugins/codex-run-budget/scripts/run_budget.py auto-report list
python3 plugins/codex-run-budget/scripts/run_budget.py auto-report disable
python3 plugins/codex-run-budget/scripts/run_budget.py auto-report enable
```

明確設定為停用會在升級後保留。若只想納入超過 300 秒的回合，使用 `auto-report enable --threshold-seconds 300`；預設門檻為零。Stop 可能早於最終用量紀錄寫入；僅處理報告的 worker 可檢查該回合是否完成，並另存一份修訂。原本的 Stop 檔案與結束前卡片保持不變。[紀錄生命週期](docs/AUTO_REPORTS.md)。

### 報告指定 Task 與代理

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py report
python3 plugins/codex-run-budget/scripts/run_budget.py report tasks --limit 10
python3 plugins/codex-run-budget/scripts/run_budget.py report task --windows 24h
python3 plugins/codex-run-budget/scripts/run_budget.py report agents
python3 plugins/codex-run-budget/scripts/run_budget.py report tree --thread TASK_SELECTOR --windows 24h
python3 plugins/codex-run-budget/scripts/run_budget.py report window --all-tasks --windows 5h
```

單獨執行 `report` 只會顯示選單，不會掃描。`task` 與 `window` 預設指向目前 Task；`agents` 是中繼資料檢視，`tree` 才明確納入後代代理用量。跨 Task 分析須指定 `--all-tasks` 與時間範圍。報告可儲存私有的 Markdown、HTML 或 JSON；除非指定 `--full`，簡短 CLI 輸出只會連到檔案。在 Codex 中，也可使用內建的 `usage-task`、`usage-agents`、`usage-window` skill。0.18.0 版報告新增各時間範圍的快取讀取占比、請求數，以及已觀測到的模型、推理強度或服務層級變動，不推斷快取未命中的原因。[範圍與證據](docs/REPORTS.md)。

### 讀取原生帳號額度

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py meter --no-save
python3 plugins/codex-run-budget/scripts/run_budget.py meter snapshot
python3 plugins/codex-run-budget/scripts/run_budget.py meter report
python3 plugins/codex-run-budget/scripts/run_budget.py meter tasks --days 1
python3 plugins/codex-run-budget/scripts/run_budget.py meter rates
python3 plugins/codex-run-budget/scripts/run_budget.py meter estimate --days 1
```

`meter` 透過已登入的 Codex 帳號連線讀取原生額度；`--no-save` 不儲存快照。`tasks` 摘要有界限的本機歷史，不會重新查詢額度。`rates` 是附日期的參考資料；`estimate` 是 Standard/Fast token 額度的假設情境，並非實際扣款。原生額度百分比屬於整個帳號，絕不從 token 總數分攤到單一 Task。[額度儀表與控制](docs/METER.md) · [測量機制](docs/METER_MECHANICS.md)。

### 調查活動

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py survey
python3 plugins/codex-run-budget/scripts/run_budget.py audit /path/to/synthetic-rollout.jsonl
python3 plugins/codex-run-budget/scripts/run_budget.py workflow
python3 plugins/codex-run-budget/scripts/run_budget.py workflow observe --thread TASK_SELECTOR
python3 plugins/codex-run-budget/scripts/run_budget.py exec-activity list --project "$PWD"
```

`survey` 讀取有界限的近期本機 Task 群；`audit` 只讀取明確提供的逐字紀錄路徑。`workflow-observe` skill 可從工作描述解析到確切 Task，並產生私有、唯讀的變更報告。`workflow observe` 預設觀測目前 Task；納入後代代理需使用 `--include-agents`，之後比較可用回傳的 `--after` 游標。這些觀測都不會啟動 daemon 或定期自動化。`exec-activity watch` 只在前景執行；`exec-activity run` 是選用的啟動器，會執行指定的 Codex 呼叫。[近期調查](docs/SURVEY.md) · [稽核](docs/AUDIT.md) · [工作流程觀測](docs/WORKFLOW_OBSERVATIONS.md) · [Exec 活動](docs/EXEC_ACTIVITY.md)。

### 審查配對專案變更

```sh
python3 plugins/codex-run-budget/scripts/paired_review.py pair --id web-api /path/to/web /path/to/api
python3 plugins/codex-run-budget/scripts/paired_review.py feature on
python3 plugins/codex-run-budget/scripts/paired_review.py enable web-api
python3 plugins/codex-run-budget/scripts/paired_review.py pairs
python3 plugins/codex-run-budget/scripts/paired_review.py scan
```

此實驗性功能在新安裝及新登錄配對時預設關閉。每組配對有各自的游標、待審查項目及一對一 Task 綁定。受信任的 `Stop` hook 檢查啟用且包含目前專案的配對；`main` 出現新變更範圍時，會透過 Codex App 要求另一專案開啟唯讀審查 Task。後續 Stop 會將簡短摘要轉送到同一個已綁定 Task，並避免回音。手動 `scan` 只會將遠端變更排入待辦，不會喚醒模型。既有配對保留先前狀態與啟用設定。[Run Budget 與 Usage Reports 的特定契約](docs/CROSS_REPO_REVIEW.md) · [設定、開關與復原](docs/PAIRED_REVIEW_AUTOMATION.md)。

### 檢查或變更已安裝軟體

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py updates check --refresh --cwd "$PWD"
python3 plugins/codex-run-budget/scripts/publisher_updates.py status
```

`updates check` 讀取已安裝的**套件**版本與原生 hook 信任狀態。發布者指令讀取目前啟用的**簽章執行環境**版本；在已安裝的外掛目錄中也接受 `on`、`off`、`update` 與 `rollback`。例行相容的簽章更新會保留 hook 定義。結構變更仍須經過一般外掛更新、`/hooks` 檢查及新 Task 流程；若必須更新套件，保留輔助程式會保護舊快取版本。[簽章更新](docs/SIGNED_UPDATES.md) · [信任提醒](docs/UPDATE_NOTICES.md) · [升級安全](docs/UPGRADE_SAFETY.md)。

## 執行與限制

Governor 在 SQLite transaction 內對齊已觀測的逐字紀錄計數並執行確定性政策。父 Task 的 `session_id` 是共用執行識別碼；hook 重試及並行代理准入具有冪等性。可設定的 start 控制行支援 `tokens`、`warn`、`block_agents`、`tools`、`agents`、`inflight`、`output`、`repeat_steer`、`repeat_halt` 與 `fail`；未知或重複選項會被拒絕。[設定與執行順序](docs/DESIGN.md) · [可靠性強化](docs/HARDENING.md)。

`UserPromptSubmit` 可阻擋新的使用者回合；觀測到 HALT 後，`PreToolUse` 可阻擋受支援的本機工具呼叫。Codex 並未在每次模型請求前提供外掛 hook；hosted tools 可能略過本機工具 hook。逐字紀錄中的 token 計數可能在模型或工具動作後才到達，因此帳本觀測到 HALT 前，單一回合仍可能超出預算。輸出檢查發生在執行後，無法撤銷副作用。一旦觀測到 HALT，後續受支援的呼叫及新回合會遭拒，直到 resume 或 off。這些是護欄，不是通用攔截、精確計費或零超額保證。[已安裝環境的證據與限制](docs/VALIDATION.md)。

## 隱私與本機資料

狀態預設存於 `~/.codex/run-budget/`；可用 `CODEX_RUN_BUDGET_HOME` 指向其他私有目錄。帳本不刻意記錄 prompt、指令、工具內容或逐字紀錄本文，只保存允許的計數、狀態、時間戳及經雜湊處理的識別碼。私有的人類可讀報告可能顯示原生 Task 與代理名稱；請勿將實際匯出檔加入 Git。預算治理及離線診斷不會上傳報告。原生額度儀表使用既有的 Codex 帳號連線；簽章更新會取得公開 release 檔案。[安全政策](SECURITY.md)。

## 文件

[文件索引](docs/README.md) 整理使用指南、測量語意、更新與信任控制、架構及附日期的驗證。[貢獻指南](CONTRIBUTING.md) 列出檢查與合成測試資料。[變更紀錄](CHANGELOG.md) 記錄版本。

MIT © EasyVibeCoding contributors。[先前技術與致謝](NOTICE.md) · [第三方聲明](THIRD_PARTY_NOTICES.md)。
