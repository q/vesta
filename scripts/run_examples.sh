#!/usr/bin/env bash
set -e

run() {
  echo "--- $1 ---"
  shift
  bash -c "$*"
  echo
}

run "text (inline)" \
  "echo '\"hello world\"' | uv run vesta.py render"

run "text (file)" \
  "uv run vesta.py render --input testdata/text.json"

run "key/value dict (inline)" \
  "echo '{\"temp\": \"72F\", \"wind\": \"12mph\"}' | uv run vesta.py render --template kv"

run "key/value dict (file)" \
  "uv run vesta.py render --input testdata/kv.json --template kv"

run "CSV table" \
  "uv run vesta.py render --input testdata/table.csv"

run "JSON table" \
  "uv run vesta.py render --input testdata/table.json"

run "JSON table (edge-to-edge, --align left)" \
  "uv run vesta.py render --input testdata/table2.json --align left"

run "metrics (plain)" \
  "uv run vesta.py render --input testdata/metrics.json"

run "metrics with color indicators (file)" \
  "uv run vesta.py render --input testdata/metrics_styled.json --valign center --align center --timestamp --explain"

run "note profile" \
  "uv run vesta.py render --input testdata/metrics_note.json --profile note"

run "json output" \
  "echo '\"hello world\"' | uv run vesta.py render --json-only"

run "title with bookend tiles" \
  "uv run vesta.py render --input testdata/metrics.json --title 'DAILY METRICS'"

run "title + subtitle time" \
  "uv run vesta.py render --input testdata/metrics_styled.json --title 'DAILY METRICS' --title-color violet --subtitle time --valign center"

run "kv (valign center)" \
  "uv run vesta.py render --input testdata/kv.json --template kv --valign center"

run "kv 2-col layout (home)" \
  "uv run vesta.py render --input testdata/home.json --columns 2"

run "kv 2-col with title and subtitle (home)" \
  "uv run vesta.py render --input testdata/home.json --columns 2 --title 'HOME' --subtitle time"

run "weather (2-col centered)" \
  "uv run vesta.py render --input testdata/weather.json --columns 2 --align center --valign center"

run "server metrics with color indicators" \
  "uv run vesta.py render --input testdata/server.json --valign center --align center --explain"

run "auto color by field name (change/delta/diff)" \
  "uv run vesta.py render --input testdata/autodetect.json --explain"

run "signed values + suppressed tile (_style)" \
  "uv run vesta.py render --input testdata/budget.json --explain"

run "range gradient, both directions (_style range object)" \
  "uv run vesta.py render --input testdata/health.json --explain"

run "stocks table" \
  "uv run vesta.py render --input testdata/stocks.json"

run "color tiles + escape sequences" \
  "uv run vesta.py render --input testdata/colors.txt --valign center"
