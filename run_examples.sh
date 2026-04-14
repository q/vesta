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

run "title with bookend tiles" \
  "uv run vesta.py render --input testdata/metrics.json --template data --title 'DAILY METRICS' --preview-only"

run "title + subtitle time" \
  "uv run vesta.py render --input testdata/metrics_styled.json --template data --title 'DAILY METRICS' --title-color violet --subtitle time --valign center --preview-only"

run "kv 2-col layout (home)" \
  "uv run vesta.py render --input testdata/home.json --columns 2 --preview-only"

run "kv 2-col with title and subtitle (home)" \
  "uv run vesta.py render --input testdata/home.json --columns 2 --title 'HOME' --subtitle time --preview-only"

run "server metrics with color indicators" \
  "uv run vesta.py render --input testdata/server.json --template data --valign center --align center --explain --preview-only"

run "stocks table" \
  "uv run vesta.py render --input testdata/stocks.json --template data --preview-only"
