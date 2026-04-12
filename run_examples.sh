#!/usr/bin/env bash
set -e

run() {
  echo "--- $1 ---"
  shift
  eval "$@"
  echo
}

run "text (inline)" \
  "echo '\"hello world\"' | uv run vesta.py render --preview-only"

run "text (file)" \
  "uv run vesta.py render --input testdata/text.json --preview-only"

run "key/value dict (inline)" \
  "echo '{\"temp\": \"72F\", \"wind\": \"12mph\"}' | uv run vesta.py render --template kv --preview-only"

run "key/value dict (file)" \
  "uv run vesta.py render --input testdata/kv.json --template kv --preview-only"

run "CSV table" \
  "uv run vesta.py render --input testdata/table.csv --preview-only"

run "JSON table" \
  "uv run vesta.py render --input testdata/table.json --preview-only"

run "metrics (plain)" \
  "uv run vesta.py render --input testdata/metrics.json --template data --preview-only"

run "metrics with color indicators (file)" \
  "uv run vesta.py render --input testdata/metrics_styled.json --template data --valign center --align center --timestamp --preview-only --explain"

run "note profile" \
  "uv run vesta.py render --input testdata/metrics_note.json --profile note --template data --preview-only"

run "json output" \
  "echo '\"hello world\"' | uv run vesta.py render --json-only"
