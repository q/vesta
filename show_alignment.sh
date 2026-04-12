#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

R="uv run vesta.py render --preview-only"

section() { echo; echo "=== $1 ==="; }

show3() {
  local data="$1"
  echo "LEFT:"
  echo "$data" | $R --align left
  echo "CENTER:"
  echo "$data" | $R --align center
  echo "RIGHT:"
  echo "$data" | $R --align right
}

# ── 1 column ──────────────────────────────────────────────────────────────────
section "1 COL / numeric"
show3 '[{"score":9842},{"score":7631},{"score":5920},{"score":4110}]'

section "1 COL / alpha"
show3 '[{"city":"boston"},{"city":"denver"},{"city":"austin"},{"city":"miami"}]'

# ── 2 columns ─────────────────────────────────────────────────────────────────
section "2 COL / all numeric"
show3 '[{"rank":1,"score":9842},{"rank":2,"score":7631},{"rank":3,"score":5920}]'

section "2 COL / all alpha"
show3 '[{"city":"boston","status":"online"},{"city":"denver","status":"offline"},{"city":"austin","status":"online"}]'

section "2 COL / mixed (text + num)"
show3 '[{"player":"alice","score":98},{"player":"bob","score":87},{"player":"carol","score":76}]'

# ── 3 columns ─────────────────────────────────────────────────────────────────
section "3 COL / all numeric"
show3 '[{"q1":88,"q2":94,"rank":1},{"q1":72,"q2":81,"rank":2},{"q1":65,"q2":70,"rank":3},{"q1":51,"q2":59,"rank":4}]'

section "3 COL / all alpha"
show3 '[{"name":"alice","dept":"eng","status":"active"},{"name":"bob","dept":"ops","status":"away"},{"name":"carol","dept":"eng","status":"active"}]'

section "3 COL / mixed (text + num)"
show3 '[{"name":"alice","score":98,"rank":1},{"name":"bob","score":87,"rank":2},{"name":"carol","score":76,"rank":3},{"name":"dave","score":61,"rank":4}]'

section "3 COL / pre-numeric strings"
show3 '[{"product":"widget","revenue":"$12.4k","growth":"+8%"},{"product":"gadget","revenue":"$9.1k","growth":"-2%"},{"product":"doohick","revenue":"$4.7k","growth":"+15%"}]'

# ── 4 columns ─────────────────────────────────────────────────────────────────
section "4 COL / all numeric"
show3 '[{"q1":88,"q2":94,"q3":91,"rank":1},{"q1":72,"q2":81,"q3":77,"rank":2},{"q1":65,"q2":70,"q3":68,"rank":3}]'

section "4 COL / all alpha"
show3 '[{"name":"alice","dept":"eng","role":"lead","loc":"nyc"},{"name":"bob","dept":"ops","role":"mgr","loc":"sf"},{"name":"carol","dept":"eng","role":"ic","loc":"chi"}]'

section "4 COL / mixed (text + num)"
show3 '[{"name":"alice","q1":88,"q2":94,"rank":1},{"name":"bob","q1":72,"q2":81,"rank":2},{"name":"carol","q1":65,"q2":70,"rank":3}]'
