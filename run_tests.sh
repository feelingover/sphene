#!/bin/bash
# テスト実行スクリプト

# 仮想環境のアクティベートがある場合はコメントを外す
# source venv/bin/activate

# 開発用パッケージをインストール
pip install -r requirements.txt
pip install -r requirements-dev.txt

# pytestでテスト実行
pytest "$@"

# カバレッジレポートの場所を表示
echo -e "\nHTMLカバレッジレポートの場所: $(pwd)/htmlcov/index.html"
