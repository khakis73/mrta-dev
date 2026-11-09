#!/bin/sh
# .node-version に固定した Node を、uv の仮想環境(.venv)に導入する。
# グローバルの Node には依存しない。以降は `uv run node` / `uv run npm` で使う。
set -eu
cd "$(dirname "$0")/.."

want="v$(cat .node-version)"
uv sync --locked
if [ "$(uv run --no-sync node --version 2>/dev/null || true)" = "$want" ]; then
  echo "Node $want は導入済み"
  exit 0
fi
uv run --no-sync nodeenv --python-virtualenv --prebuilt --force --node="$(cat .node-version)"
uv run --no-sync node --version
