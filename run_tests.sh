#!/bin/bash
# テスト実行スクリプト

# 仮想環境のアクティベートがある場合はコメントを外す
# source venv/bin/activate

# 開発用パッケージをインストール
# pip install -r requirements.txt
# pip install -r requirements-dev.txt

# pytestでテスト実行
# 環境変数でログレベルを一時的に上書きできるようにする
LOG_LEVEL=${LOG_LEVEL:-INFO}
python -m pytest "$@" --log-cli-level=$LOG_LEVEL

# カバレッジレポートの場所を表示
echo -e "\nHTMLカバレッジレポートの場所: $(pwd)/htmlcov/index.html"
