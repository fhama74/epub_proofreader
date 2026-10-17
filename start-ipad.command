#!/bin/zsh
cd -- "$(dirname -- "$0")"
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python scripts/serve_ipad.py
elif command -v uv >/dev/null 2>&1; then
  exec uv run python scripts/serve_ipad.py
else
  echo '初回セットアップが必要です。READMEの起動手順を確認してください。'
  read '?Enterで閉じます。'
fi
