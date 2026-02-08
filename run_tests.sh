#!/bin/bash
# テスト実行スクリプト

# pytestでテスト実行
# 環境変数でログレベルを一時的に上書きできるようにする
LOG_LEVEL=${LOG_LEVEL:-INFO}
uv run python -m pytest "$@" --log-cli-level=$LOG_LEVEL

# カバレッジレポートの場所を表示
echo -e "\nHTMLカバレッジレポートの場所: $(pwd)/htmlcov/index.html"
