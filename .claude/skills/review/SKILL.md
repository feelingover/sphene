---
name: review
description: PRレビュー→修正→push の一気通貫ワークフロー。ユーザーが「PR #XX をレビューして」「/review XX」「レビューして修正をプッシュして」と指示したときに使う。PRの変更ファイルを読み込み、バグ・型安全性・テストカバレッジ・ドキュメントの観点でレビューし、修正を適用してテストパス後にプッシュする。
allowed-tools: Bash, Read, Glob, Grep, Edit, Write, mcp__github__pull_request_read, mcp__serena__find_symbol, mcp__serena__find_referencing_symbols, mcp__serena__search_for_pattern, AskUserQuestion
argument-hint: [pr_number]
model: inherit
---

あなたはPRレビューから修正・プッシュまでを一気通貫で実行する専門スキル。
**レビュー指摘は必ず実際のコードを確認してから出す。** コードを引用せずに指摘しない。

---

## Step 1: PR番号の確認

引数 `$ARGUMENTS` が渡されていればそれをPR番号として使う。
不明な場合は `AskUserQuestion` で確認する。

---

## Step 2: PRの取得と変更ファイルの把握

```bash
gh pr view <PR番号> --json title,body,files,baseRefName,headRefName
gh pr diff <PR番号>
```

PRのタイトル・概要・変更ファイル一覧をユーザーに見せる。

---

## Step 3: 変更ファイルの読み込みとレビュー

変更された全ファイルを `Read` で読み込み、以下の4観点でレビューする。
**各指摘には必ず該当コードを引用し、ファイルパスと行番号を添える。**

### レビュー観点

| 観点 | チェック内容 |
|------|------------|
| **バグ・ロジック** | 境界値、エラーハンドリング漏れ、非同期競合、想定外パスの未考慮 |
| **型安全性** | 型ヒントの欠落・不正確、mypy で検出される問題 |
| **テストカバレッジ** | 変更したコードパスに対応するテストがあるか。未テストの分岐がないか |
| **ドキュメント整合性** | docstring・README・設定コメントが変更後のコードと一致しているか |

重要度でラベルを付ける: `[MUST]` 修正必須 / `[SHOULD]` 推奨 / `[NIT]` 軽微

---

## Step 4: レビュー結果の提示と修正対象の確認

レビュー結果をまとめてユーザーに提示する。
`AskUserQuestion` で「どの指摘を修正する？（全部 / [MUST]のみ / 番号指定）」と確認する。

---

## Step 5: 修正の適用

確認した指摘に対して修正を適用する。

- 修正時は `Edit` ツールを使う
- 関連するテストファイル・フィクスチャも確認し、必要に応じて更新する
- フィーチャーフラグ・環境変数・config のデフォルト値を変更した場合は、`mock_config` を含むテストフィクスチャも忘れず更新する

---

## Step 6: テスト・型チェックの実行と確認

```bash
uv run python -m pytest --tb=short -q
uv run mypy .
```

失敗した場合は **原因を特定して修正し、再実行する**。全パスするまで繰り返す。

テスト結果（パス件数・失敗件数）をユーザーに報告する。

---

## Step 7: プッシュ

テストが全件パスしたら `AskUserQuestion` で「修正をプッシュしていい？」と確認する。

承認を得てから:

```bash
git add -p   # 変更内容を確認しながらステージング
git commit -m "fix: レビュー指摘の修正"
git push
```

---

## Step 8: 完了報告

- 修正した指摘の一覧
- テスト結果（パス件数）
- プッシュ済みブランチ名
- PRのURL

を報告して完了。
