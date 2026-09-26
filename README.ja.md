# Codex Run Budget

**Codex の Task とサブエージェントで共有するトークン予算のガードレールと、ローカルの使用状況表示。**

[English](README.md) · [繁體中文](README.zh-Hant.md) · [简体中文](README.zh-Hans.md) · [日本語](README.ja.md)

![Codex Run Budget のソーシャルプレビュー：親 Task とサブエージェントで一つの予算を共有](assets/social-preview.png)

Codex Run Budget は、**親 Task とそのサブエージェントが一つの予算を共有**するためのローカル Codex プラグインです。ターンごとの自動利用記録、対象を指定した使用量レポート、Codex ネイティブのアカウントクォータの観測、任意のワークフローおよび `codex exec` アクティビティ表示も提供します。予算判断には Python と SQLite の台帳による決定的な規則を使います。レポートや観測機能を使うだけでは予算は開始されません。

本プロジェクトは、[Microsoft TokenOps](https://commandline.microsoft.com/tokenops-real-time-run-scoped-cost-control-ai-agents/) の実行単位のガバナンスという考え方に着想を得た独立したコミュニティプロジェクトです。OpenAI または Microsoft の製品ではなく、課金メーターでも超過ゼロの保証でもありません。実行時には Python 3.10+ と標準ライブラリのみが必要です。

[クイックスタート](#クイックスタート) · [機能](#機能) · [目的別コマンド](#目的別コマンド) · [適用範囲と制限](#適用範囲と制限) · [ドキュメント](#ドキュメント)

## クイックスタート

このリポジトリの Codex marketplace からインストールします。

```sh
codex plugin marketplace add https://github.com/easyvibecoding/codex-run-budget
codex plugin add codex-run-budget@codex-run-budget
```

Codex CLI で `/hooks` を開き、プラグインの hook 定義を確認して信頼した後、**新しい Task** を開始します。インストール済み、または有効化済みのプラグインでも、hook が信頼されていない場合や変更されている場合はスキップされることがあります。

共有予算を開始するには、**Task メッセージの先頭**に制御行を置きます。

```text
run-budget:start tokens=100k

機能を実装し、関連するチェックを実行してください。
```

上限は親 Task のセッションツリー全体に適用されます。予算を開始すると新しい監査 epoch が作られ、以前の epoch の履歴は残ります。少なくとも一回のモデルリクエスト全体をまかなえる上限を設定してください。すべてのモデルリクエストの前に hook があるわけではありません。

```text
run-budget:status
run-budget:halt reason="operator pause"
run-budget:resume tokens=200k
run-budget:off
```

`resume tokens=` は観測済みの使用量を上回る新しい絶対上限を設定します。メッセージの後半で引用された制御行はコマンドとして動作しません。[制御構文、ポリシー順序、状態](docs/DESIGN.md) · [予算実行の確認](#予算実行の確認)。

予算が有効でない場合も、自動使用量カードは既定で有効です。対象となるサブエージェントは自分のページにカードを表示でき、親 Task のカードには観測された子孫の小計が別に表示されます。両方の表示には、同じハッシュ化された `@selector` が付きます。子のカードには直接の親を表示し、自身と子孫の使用量を区別します。親子関係に矛盾がある場合は未確認のままにします。[ターンごとの記録](docs/AUTO_REPORTS.md)。

## 機能

| 領域 | 内容 | 適用範囲 |
| --- | --- | --- |
| 実行全体の共有予算 | 親 Task の `session_id` と一つの SQLite 台帳を使い、親と子の hook を処理します。トークン、ツール、エージェント、実行中の処理、繰り返し、出力にガードを適用し、STEER の後に HALT を行います。 | 対応する hook 境界でのみ適用されます。 |
| ターンごとの自動記録 | 親 Task と対象となるサブエージェントは、それぞれのページに終了前のカードを表示でき、Stop／SubagentStop 記録を保存します。回数を限定した完了確認で別の改訂版も保存できます。 | 各カードはその時点のスナップショットです。カウンターや系統の証拠が不足する場合は部分的または不明のままです。 |
| 対象を指定した Task レポート | 一つの Task、そのエージェントツリー、または明示した期間を選び、観測済みトークン、過去の設定、キャッシュ読み取り比率、設定変更の兆候を表示します。 | 複数 Task にまたがる期間は明示的な範囲指定が必要です。レポートは予算を開始しません。 |
| ネイティブのクォータ表示 | アカウントクォータと保存済みスナップショット、ローカル Task の設定履歴、日付付きのレート、Standard/Fast クレジットのシナリオを読み取ります。 | アカウントの割合や推定クレジットは Task の費用や実際の請求額ではありません。 |
| 診断 | 指定したローカルトランスクリプトを監査し、対象数を限定した最近の Task を調査し、カーソル付きで明示的なワークフロー観測を記録します。 | 観測結果は、プロセスの稼働、作業の完了、継続的な監視を意味しません。 |
| プロジェクトの exec アクティビティ | 一つの作業ディレクトリで追加の `codex exec` セッションを一覧表示または監視します。任意のランチャーは一時的な起動記録を残せます。 | exec 起動の使用量はネイティブの子エージェント系統および共有予算台帳とは別です。 |
| 実験的なペアプロジェクトレビュー | ユーザーが Codex プロジェクトの正確なルートを名前付きペアとして登録します。信頼済みの `Stop` hook は相手のプロジェクトでレビュー Task を開き、後の要約転送のため二つの Task を結び付けられます。一つのプロジェクトを複数のペアに含めることもできます。 | 全体とペアごとにスイッチがあります。定期ポーリングはなく、リモートだけの変更には後のペア Task または手動スキャンが必要です。 |
| 署名付きランタイム更新 | 発行者が署名した互換性のあるランタイムと CLI の変更を新しい Task に適用し、既存 Task は固定済みの版を使い続けます。 | 新しい hook、エントリ、鍵、プラグイン構造には通常のインストールと信頼確認が必要です。 |

この README は四言語で提供します。人が読むカード、レポート、メニュー、要約には九言語が同梱されています。コマンド、JSON、ステータスコード、ネイティブの名前、モデル ID は翻訳しません。[多言語対応](docs/LOCALIZATION.md)。

## 目的別コマンド

以下のコマンドはリポジトリの checkout から実行します。インストール済みプラグインのディレクトリから実行する場合は `python3 scripts/run_budget.py` を使ってください。[ガイドの一覧](docs/README.md)。

### 予算実行の確認

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py list
python3 plugins/codex-run-budget/scripts/run_budget.py show latest --json
python3 plugins/codex-run-budget/scripts/run_budget.py events latest
```

台帳にはカウンター、ポリシー判断、時刻、ハッシュ化された系統キーを保存します。プロンプトやツール本文は意図的に保存しません。[設計](docs/DESIGN.md) · [セキュリティ](SECURITY.md)。

### 自動記録の確認と制御

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py auto-report status
python3 plugins/codex-run-budget/scripts/run_budget.py auto-report list
python3 plugins/codex-run-budget/scripts/run_budget.py auto-report disable
python3 plugins/codex-run-budget/scripts/run_budget.py auto-report enable
```

明示的な無効設定はアップグレード後も残ります。300 秒を超えるターンだけを含めるには `auto-report enable --threshold-seconds 300` を使います。既定のしきい値はゼロです。`SubagentStart` は子自身の Task とターンを識別してカードを作り、`SubagentStop` は子の記録を確定するとともに、祖先のカードに使う範囲を限定した証拠を保存します。Stop が最終使用量レコードの保存より先に発生する場合、レポート専用 worker はそのターンの完了を確認して別の改訂版を保存できます。元の記録と終了前カードは変更しません。互換性のある署名付きランタイム更新では Run Budget の既存の `SubagentStart` hook 定義は変わらず、ネイティブの信頼状態は維持されます。更新後のランタイムを読み込むには新しい Task が必要です。[記録のライフサイクル](docs/AUTO_REPORTS.md)。

### 対象の Task とエージェントを報告

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py report
python3 plugins/codex-run-budget/scripts/run_budget.py report tasks --limit 10
python3 plugins/codex-run-budget/scripts/run_budget.py report task --windows 24h
python3 plugins/codex-run-budget/scripts/run_budget.py report agents
python3 plugins/codex-run-budget/scripts/run_budget.py report tree --thread TASK_SELECTOR --windows 24h
python3 plugins/codex-run-budget/scripts/run_budget.py report window --all-tasks --windows 5h
```

引数なしの `report` はスキャンせずにメニューを表示します。`task` と `window` の既定対象は現在の Task です。`report task` は、対象がサブエージェントでもその Task だけを選びます。`agents` はメタデータ表示で、親 Task を指定した `tree` は子孫の使用量を明示的に含みます。子自身の合計が親のツリー小計に含まれる場合があるため、二つを足さないでください。複数 Task の分析には `--all-tasks` と期間の指定が必要です。レポートは非公開の Markdown、HTML、JSON として保存できます。`--full` を指定しない短い CLI 出力にはファイルへのリンクだけが表示されます。Codex では同梱の `usage-task`、`usage-agents`、`usage-window` skill も利用できます。0.18.0 のレポートには、期間ごとのキャッシュ読み取り比率、リクエスト数、観測されたモデル・推論強度・サービス階層の変更が加わりました。キャッシュミスの原因は推測しません。[範囲と証拠](docs/REPORTS.md)。

### ネイティブのアカウントクォータを読む

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py meter --no-save
python3 plugins/codex-run-budget/scripts/run_budget.py meter snapshot
python3 plugins/codex-run-budget/scripts/run_budget.py meter report
python3 plugins/codex-run-budget/scripts/run_budget.py meter tasks --days 1
python3 plugins/codex-run-budget/scripts/run_budget.py meter rates
python3 plugins/codex-run-budget/scripts/run_budget.py meter estimate --days 1
```

`meter` はサインイン済み Codex アカウントの接続を使ってネイティブのクォータを読み取ります。`--no-save` はスナップショットを保存しません。`tasks` は新たなクォータ照会を行わず、範囲を限定したローカル履歴を要約します。`rates` は日付付きの参考情報です。`estimate` は Standard/Fast トークンクレジットの仮定に基づくシナリオで、実際の請求ではありません。ネイティブの割合はアカウント全体の値であり、トークン合計から個別 Task に割り当てることはありません。[クォータと操作](docs/METER.md) · [測定の仕組み](docs/METER_MECHANICS.md)。

### アクティビティを調べる

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py survey
python3 plugins/codex-run-budget/scripts/run_budget.py audit /path/to/synthetic-rollout.jsonl
python3 plugins/codex-run-budget/scripts/run_budget.py workflow
python3 plugins/codex-run-budget/scripts/run_budget.py workflow observe --thread TASK_SELECTOR
python3 plugins/codex-run-budget/scripts/run_budget.py exec-activity list --project "$PWD"
```

`survey` は対象数を限定した最近のローカル Task を読み取ります。`audit` は明示されたトランスクリプトのパスだけを読み取ります。`workflow-observe` skill は作業の説明から正確な Task を特定し、非公開で読み取り専用の変更レポートを作成できます。`workflow observe` の既定対象は現在の Task です。子孫エージェントを含めるには `--include-agents` を使い、その後の比較には返された `--after` カーソルを使います。これらの観測はデーモンや定期的な自動処理を起動しません。`exec-activity watch` はフォアグラウンドでのみ動きます。`exec-activity run` は指定した Codex 呼び出しを実行する任意のランチャーです。[最近の Task 調査](docs/SURVEY.md) · [監査](docs/AUDIT.md) · [ワークフロー観測](docs/WORKFLOW_OBSERVATIONS.md) · [Exec アクティビティ](docs/EXEC_ACTIVITY.md)。

### ペアプロジェクトの変更をレビューする

```sh
python3 plugins/codex-run-budget/scripts/paired_review.py pair --id web-api /path/to/web /path/to/api
python3 plugins/codex-run-budget/scripts/paired_review.py feature on
python3 plugins/codex-run-budget/scripts/paired_review.py enable web-api
python3 plugins/codex-run-budget/scripts/paired_review.py pairs
python3 plugins/codex-run-budget/scripts/paired_review.py scan
```

この実験的な機能は、新規インストールと新規登録ペアでは既定で無効です。ペアごとにカーソル、保留中のレビュー、一対一の Task の結び付けを持ちます。信頼済みの `Stop` hook は現在のプロジェクトを含む有効なペアを確認します。`main` に新しい変更範囲があれば、Codex App を通して相手のプロジェクトに読み取り専用のレビュー Task を要求します。その後の Stop は短い要約を同じ Task に転送し、転送のループを防ぎます。手動の `scan` はリモートだけの変更をキューに入れますが、モデルを起動しません。既存の設定済みペアは以前の状態と有効・無効の設定を保ちます。[Run Budget と Usage Reports の固有契約](docs/CROSS_REPO_REVIEW.md) · [設定、スイッチ、復旧](docs/PAIRED_REVIEW_AUTOMATION.md)。

### インストール済みソフトウェアを確認・変更する

```sh
python3 plugins/codex-run-budget/scripts/run_budget.py updates check --refresh --cwd "$PWD"
python3 plugins/codex-run-budget/scripts/publisher_updates.py status
```

`updates check` はインストール済み**パッケージ**のバージョンとネイティブ hook の信頼状態を読み取ります。発行者コマンドは現在有効な**署名付きランタイム**のバージョンを読み取ります。インストール済みプラグインのディレクトリでは `on`、`off`、`update`、`rollback` も使えます。通常の互換性のある署名付きランタイム更新は hook 定義を維持します。構造的な変更には通常のプラグイン更新、`/hooks` の確認、新しい Task が必要です。そのようなパッケージ更新が必要なときは保持用ヘルパーが古いキャッシュ版を保護します。[署名付き更新](docs/SIGNED_UPDATES.md) · [信頼状態の通知](docs/UPDATE_NOTICES.md) · [安全なアップグレード](docs/UPGRADE_SAFETY.md)。

## 適用範囲と制限

Governor は観測済みのトランスクリプトカウンターを照合し、SQLite トランザクション内で決定的なポリシーを適用します。親 Task の `session_id` が共有実行キーです。hook の再試行と並行するエージェントの受け入れは冪等です。設定可能な start 行は `tokens`、`warn`、`block_agents`、`tools`、`agents`、`inflight`、`output`、`repeat_steer`、`repeat_halt`、`fail` に対応します。不明または重複したオプションは拒否します。[設定と適用順序](docs/DESIGN.md) · [信頼性の強化](docs/HARDENING.md)。

`UserPromptSubmit` は新しいユーザーターンをブロックできます。HALT が観測された後、`PreToolUse` は対応するローカルツール呼び出しをブロックできます。Codex はすべてのモデルリクエストの前にプラグイン hook を公開していません。Hosted tools はローカルツール hook を通らない場合があります。トランスクリプトのトークンカウンターがモデルやツールの動作後に届く場合があるため、台帳が HALT を観測する前に一つのターンで上限を超える可能性があります。出力の検査は実行後に行われ、副作用を取り消せません。HALT が観測されると、resume または off まで、後続の対応する呼び出しと新しいターンは拒否されます。これはガードレールであり、すべての操作の仲介、厳密な課金計測、超過ゼロを保証するものではありません。[インストール済み環境での証拠と制限](docs/VALIDATION.md)。

## プライバシーとローカルデータ

状態は既定で `~/.codex/run-budget/` に保存されます。別の非公開ディレクトリを使うには `CODEX_RUN_BUDGET_HOME` を設定します。台帳はプロンプト、コマンド、ツール本文、トランスクリプト本文を意図的に記録しません。許可されたカウンター、状態、時刻、ハッシュ化された識別子のみを保持します。非公開の人間向けレポートにはネイティブの Task 名とエージェント名が表示される場合があります。実際のエクスポートは Git に追加しないでください。予算ガバナンスとオフライン診断はレポートをアップロードしません。ネイティブのクォータ表示は既存の Codex アカウント接続を使います。署名付き更新は公開 release のファイルを取得します。[セキュリティポリシー](SECURITY.md)。

## ドキュメント

[ドキュメント一覧](docs/README.md)には、使用ガイド、測定値の意味、更新と信頼の操作、アーキテクチャ、日付付きの検証記録をまとめています。[コントリビューション](CONTRIBUTING.md)には検査と合成テストデータを記載しています。[変更履歴](CHANGELOG.md)にはバージョンを記録しています。

MIT © EasyVibeCoding contributors。[先行事例と謝辞](NOTICE.md) · [サードパーティーの通知](THIRD_PARTY_NOTICES.md)。
