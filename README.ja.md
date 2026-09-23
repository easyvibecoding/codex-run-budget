# Codex Run Budget

**Codex の Task とサブエージェントで共有するトークン予算のガードレールと、ローカルの使用状況表示。**

[English](README.md) · [繁體中文](README.zh-Hant.md) · [简体中文](README.zh-Hans.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Deutsch](README.de.md) · [Français](README.fr.md) · [Español](README.es.md) · [Português](README.pt.md)

Codex Run Budget は、親 Task とそのサブエージェントが 1 つの予算を共有するローカル Codex プラグインです。ターンごとの使用量記録、範囲を指定した Task レポート、アカウントのクォータ観測、任意のワークフローおよび `codex exec` アクティビティ表示も提供します。予算判断は Python と SQLite の決定的な規則で行い、レポートの表示だけでは予算を開始しません。

## 主な機能

- **共有予算：**親 Task の `session_id` を実行キーとし、サブエージェントを集計します。STEER と HALT は対応する hook 境界で適用します。
- **使用量記録とレポート：**自動ターンカード、個別 Task、エージェントツリー、明示した期間の観測値を確認できます。証拠が足りない場合は部分的または不明の状態を保持します。
- **クォータとアクティビティ：**Codex ネイティブのアカウントクォータを読み取り、必要に応じてワークフローやプロジェクト単位の `codex exec` を観測します。アカウントの割合は Task 単位の請求額ではありません。
- **ローカルとプライバシー：**台帳は許可されたカウンター、状態、時刻、ハッシュ化した識別子のみを保存します。プロンプト、コマンド、ツール本文を意図的に保存しません。実行時に必要なのは Python 3.10+ の標準ライブラリだけです。

## クイックスタート

```sh
codex plugin marketplace add https://github.com/easyvibecoding/codex-run-budget
codex plugin add codex-run-budget@codex-run-budget
```

Codex CLI の `/hooks` でプラグインの hook を確認して信頼し、**新しい Task** を開始します。Task メッセージの先頭に次を置きます。

```text
run-budget:start tokens=100k

Implement the feature and run the relevant checks.
```

状態確認は `run-budget:status`、操作は `run-budget:halt reason="operator pause"`、`run-budget:resume tokens=200k`、`run-budget:off` を使います。[全コマンドと例](README.md#commands-by-task) · [設計と規則](docs/DESIGN.md)。

## 適用範囲と制限

Codex はすべてのモデル要求の前にプラグイン hook を公開していません。hosted tools がローカル tool hook を通らない場合もあります。使用量カウンターの到着が操作後になるため、HALT の観測前に 1 ターンで予算を超える可能性があります。これはガードレールであり、厳密な課金計測、超過ゼロ、あらゆる操作の遮断を保証しません。[実機検証と制限](docs/VALIDATION.md)。

[英語版の詳細 README](README.md) · [ドキュメント一覧](docs/README.md) · [言語設定](docs/LOCALIZATION.md) · [セキュリティ](SECURITY.md)

独立したコミュニティプロジェクトであり、OpenAI または Microsoft の製品ではありません。MIT © EasyVibeCoding contributors。
