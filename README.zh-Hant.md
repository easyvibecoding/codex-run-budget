# Codex Run Budget

**為 Codex Task 與子代理提供共用 token 預算護欄及本機用量資訊。**

[English](README.md) · [繁體中文](README.zh-Hant.md) · [简体中文](README.zh-Hans.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Deutsch](README.de.md) · [Français](README.fr.md) · [Español](README.es.md) · [Português](README.pt.md)

Codex Run Budget 是在本機運作的 Codex 外掛，讓一個父 Task 與其所有子代理共用同一份預算。它也提供每回合用量紀錄、指定範圍的 Task 報告、帳號額度觀測，以及選用的工作流程與 `codex exec` 活動檢視。預算判斷由 Python 與 SQLite 以確定性規則執行；閱讀報告本身不會啟動預算。

## 主要功能

- **共用預算：**以父 Task 的 `session_id` 作為執行識別，彙總子代理，並在受支援的 hook 邊界執行 STEER 與 HALT。
- **用量紀錄與報告：**查看自動回合卡、個別 Task、代理樹或明確指定時間範圍的觀測資料；缺少證據時保留部分或未知狀態。
- **帳號額度與活動：**讀取 Codex 原生帳號額度，並依需要觀察工作流程及專案範圍的 `codex exec` 活動。帳號百分比不是單一 Task 的費用。
- **本機與隱私：**預算帳本只保存允許的計數、狀態、時間及雜湊識別，不刻意保存 prompt、指令或工具內容。執行時只需 Python 3.10+ 標準函式庫。

## 快速開始

```sh
codex plugin marketplace add https://github.com/easyvibecoding/codex-run-budget
codex plugin add codex-run-budget@codex-run-budget
```

在 Codex CLI 的 `/hooks` 檢查並信任外掛 hook，接著開始**新的 Task**。在 Task 訊息的最開頭加入：

```text
run-budget:start tokens=100k

Implement the feature and run the relevant checks.
```

使用 `run-budget:status` 查看狀態，或以 `run-budget:halt reason="operator pause"`、`run-budget:resume tokens=200k`、`run-budget:off` 控制預算。[完整指令與範例](README.md#commands-by-task) · [設計與規則](docs/DESIGN.md)。

## 執行邊界

Codex 沒有在每次模型請求前提供外掛 hook；hosted tools 也可能略過本機工具 hook。用量計數可能在動作結束後才到達，因此單一回合可能超過預算才觀測到 HALT。此工具是護欄，並非精確計費、零超額或通用攔截機制。[已安裝環境的驗證與限制](docs/VALIDATION.md)。

[英文完整 README](README.md) · [文件索引](docs/README.md) · [語系說明](docs/LOCALIZATION.md) · [安全政策](SECURITY.md)

本專案為獨立社群作品，並非 OpenAI 或 Microsoft 產品。MIT © EasyVibeCoding contributors。
