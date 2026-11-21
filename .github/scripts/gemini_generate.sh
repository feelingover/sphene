#!/usr/bin/env bash
# Gemini API でテキストを生成し、標準出力に書き出す。
# 失敗時（APIキー未設定・HTTPエラー・不正なレスポンス）はフォールバック文を出力する。
#
# Usage: gemini_generate.sh <prompt> <fallback>
# Env:
#   GEMINI_API_KEY  Gemini API キー（未設定ならフォールバック）
#   GEMINI_MODEL    使用モデル（デフォルト: gemini-4-hydrogen）
set -uo pipefail

PROMPT="$1"
FALLBACK="$2"
MODEL="${GEMINI_MODEL:-gemini-4-hydrogen}"

fallback() {
  echo "❌ $1 フォールバックを使います。" >&2
  printf '%s\n' "$FALLBACK"
  exit 0
}

[[ -n "${GEMINI_API_KEY:-}" ]] || fallback "GEMINI_API_KEY が未設定。"

PAYLOAD=$(jq -n --arg text "$PROMPT" '{contents: [{parts: [{text: $text}]}]}') \
  || fallback "リクエストの組み立てに失敗。"
RESPONSE_FILE=$(mktemp)
trap 'rm -f "$RESPONSE_FILE"' EXIT

HTTP_CODE=$(curl -sS -o "$RESPONSE_FILE" -w '%{http_code}' --max-time 60 \
  "https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent" \
  -H "x-goog-api-key: ${GEMINI_API_KEY}" \
  -H 'Content-Type: application/json' \
  -X POST \
  -d "$PAYLOAD") || fallback "Gemini API への接続に失敗。"

if [[ "$HTTP_CODE" != "200" ]]; then
  echo "Response: $(head -c 1000 "$RESPONSE_FILE")" >&2
  fallback "Gemini API がエラーを返した (Status: $HTTP_CODE)。"
fi

TEXT=$(jq -er '[.candidates[0].content.parts[]?.text // empty] | join("") | select(length > 0)' \
  "$RESPONSE_FILE" 2>/dev/null) || fallback "レスポンスから本文を取り出せなかった。"

echo "✅ Gemini (${MODEL}) で生成できた！" >&2
printf '%s\n' "$TEXT"
