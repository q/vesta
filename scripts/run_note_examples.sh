#!/usr/bin/env bash
# Note-profile (3 rows × 15 cols) examples.
# The Note has ~1/3 the space of the Flagship, so every row and column matters.
# Run with: bash scripts/run_note_examples.sh
set -e

run() {
  echo "--- $1 ---"
  shift
  eval "$@"
  echo
}

# ── TEXT ──────────────────────────────────────────────────────────────────────
# 3 rows × 15 chars = 45 chars total. Words wrap naturally; short messages center.

run "text: short message (centered by default)" \
  "echo '\"GOOD MORNING\"' | uv run vesta.py render --profile note --preview-only"

run "text: long message wraps across all 3 rows (valign top)" \
  "echo '\"now playing your favorite song\"' | uv run vesta.py render --profile note --valign top --preview-only"

run "text: title costs 1 row — 2 rows left for content" \
  "echo '\"studio b\"' | uv run vesta.py render --profile note --template text --title 'ON AIR' --title-color red --preview-only"

# ── METRICS (auto / render_data for dicts) ────────────────────────────────────
# The auto template routes dicts through render_data → _render_metrics.
# Each entry gets its own row with label left + value right — 3 entries fill the board.
# This is the densest packing available on the Note.

run "metrics: 3 entries fill all 3 rows (most efficient layout for Note)" \
  "uv run vesta.py render --input testdata/metrics_note.json --profile note --preview-only"

run "metrics: color indicators via range-based style (uptime/error/rps)" \
  "uv run vesta.py render --input testdata/note_status.json --profile note --preview-only"

run "metrics: with title — 2 rows left for data" \
  "uv run vesta.py render --input testdata/metrics_note.json --profile note --title 'ENV' --title-color orange --preview-only"

run "metrics: 4 entries — 4th silently clipped (3-row limit)" \
  "echo '{\"a\": 1, \"b\": 2, \"c\": 3, \"d\": 4}' | uv run vesta.py render --profile note --preview-only"

run "metrics: large numbers compact (\$1.28M, 28.5K)" \
  "echo '{\"revenue_curr\": 1284399, \"visits\": 28542}' | uv run vesta.py render --profile note --preview-only"

run "metrics: datetime — Note omits the date, shows time only (9:15A vs 5/11 9:15A on flagship)" \
  "echo '{\"updated\": \"2026-05-11T09:15:00\"}' | uv run vesta.py render --profile note --preview-only"

run "metrics: align center (block floats to middle of the 15-col grid)" \
  "echo '{\"temp\": 72, \"hum_pct\": 54}' | uv run vesta.py render --profile note --align center --valign center --preview-only"

run "metrics: signed tone — negative margin shows red tile" \
  "echo '{\"margin_pct\": -1.8, \"_style\": {\"margin_pct\": \"signed\"}}' | uv run vesta.py render --profile note --preview-only"

run "metrics: range-based color (87 near bad end of 65-95 → orange/red tile)" \
  "echo '{\"temp\": 87, \"_style\": {\"temp\": {\"good\": 65, \"bad\": 95}}}' | uv run vesta.py render --profile note --preview-only"

run "metrics: explain color + formatting logic on note profile" \
  "echo '{\"change_pct\": -3.5, \"revenue_curr\": 84210}' | uv run vesta.py render --profile note --explain --no-ansi --preview-only"

# ── KV (--template kv) ────────────────────────────────────────────────────────
# On the Note (cols < 18), render_kv uses the NARROW PATH: label and value each
# get their own row. This means only ~1.5 pairs fit in 3 rows.

run "kv: 1 pair — label row 0, value row 1, row 2 blank" \
  "echo '{\"temp\": \"72F\"}' | uv run vesta.py render --profile note --template kv --preview-only"

run "kv: 2 pairs — rows 0-1 = pair 1 (label+value), row 2 = pair 2 label only (value dropped!)" \
  "echo '{\"temp\": \"72F\", \"wind\": \"12mph\"}' | uv run vesta.py render --profile note --template kv --preview-only"

run "kv: _pct suffix — value formatted as percent" \
  "echo '{\"battery_pct\": 87.5}' | uv run vesta.py render --profile note --template kv --preview-only"

run "kv: _curr suffix — value formatted as currency" \
  "echo '{\"price_curr\": 1249.99}' | uv run vesta.py render --profile note --template kv --preview-only"

run "kv: with title — title on row 0, only 1 pair fits in remaining 2 rows" \
  "echo '{\"status\": \"online\", \"uptime\": \"14d\"}' | uv run vesta.py render --profile note --template kv --title 'SYS' --title-color blue --preview-only"

run "kv: label truncation — 14-char max, long names are cut" \
  "echo '{\"averylonglabelname\": 42}' | uv run vesta.py render --profile note --template kv --preview-only"

run "kv: value truncation — 15-char max, long strings are cut" \
  "echo '{\"url\": \"https://example.com/very/long/path\"}' | uv run vesta.py render --profile note --template kv --preview-only"

run "kv: --columns 2 falls back to 1-col (pair is too wide for 15 cols)" \
  "echo '{\"status\": \"online\", \"uptime\": \"14d\"}' | uv run vesta.py render --profile note --template kv --columns 2 --preview-only 2>&1"

# ── TABLES ────────────────────────────────────────────────────────────────────
# With no title: header on row 0, up to 2 data rows. 3 columns squeeze but fit.
# 5+ columns trigger a drop warning.

run "table: 2-col — header + 2 data rows fills the board perfectly" \
  "uv run vesta.py render --input testdata/note_table.json --profile note --preview-only"

run "table: stocks — 2-col with pct formatting + green/red color tiles" \
  "uv run vesta.py render --input testdata/note_stocks.json --profile note --preview-only"

run "table: 3-col — header + 2 rows, tight but fits" \
  "echo '[{\"name\": \"alice\", \"score\": 98, \"rank\": 1}, {\"name\": \"bob\", \"score\": 87, \"rank\": 2}]' | uv run vesta.py render --profile note --preview-only"

run "table: 5-col — column drop warning, only 4 columns rendered" \
  "echo '[{\"a\": 1, \"b\": 2, \"c\": 3, \"d\": 4, \"e\": 5}]' | uv run vesta.py render --profile note --preview-only 2>&1"

run "table: with title — 1 row for header, 1 for data; second data row lost" \
  "uv run vesta.py render --input testdata/note_table.json --profile note --title 'SCORES' --title-color green --preview-only"

# ── HEADER / SEPARATOR COST ───────────────────────────────────────────────────
# Each header element eats a row from an already-tight 3-row budget.
# title=1 row, separator=1 row, title+subtitle=2 rows.

run "separator alone — rainbow eats row 0, 2 content rows remain" \
  "echo '{\"temp\": \"72F\"}' | uv run vesta.py render --profile note --template kv --separator rainbow --preview-only"

run "title + separator — 2 rows consumed, only 1 content row left" \
  "echo '{\"status\": \"ok\"}' | uv run vesta.py render --profile note --template kv --title 'SYS' --title-color blue --separator white --preview-only"

run "title + subtitle — row 2 = first key label only, value has nowhere to go" \
  "echo '{\"status\": \"ok\"}' | uv run vesta.py render --profile note --template kv --title 'SYS' --subtitle 'v2.4' --title-color violet --preview-only"

# ── SPECIAL ───────────────────────────────────────────────────────────────────

run "heart glyph — code 62 renders as heart on Note (vs degree on flagship)" \
  "printf '\"I \xe2\x9d\xa4 NOTE\"' | uv run vesta.py render --profile note --valign center --preview-only"

run "timestamp: placed in bottom-right when last row is empty" \
  "echo '{\"temp\": \"72F\"}' | uv run vesta.py render --profile note --template kv --timestamp --preview-only"

run "timestamp: force-write overwrites occupied content" \
  "echo '{\"a\": 1, \"b\": 2}' | uv run vesta.py render --profile note --template kv --force-timestamp --preview-only"
