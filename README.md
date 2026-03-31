# vesta

A small Python formatter / previewer / publisher for Vestaboard devices.

The goal is simple:

**semantic input → compact board layout → terminal preview → optional publish**

This repo is intentionally focused on practical use, not a big template language or a hosted service.

<img src="docs/example.png" width="600" alt="Terminal preview showing a metrics board with color indicators and explain output" />

## What it does

- formats structured data for Vestaboard
- supports multiple device profiles
  - flagship board: **6 x 22**
  - note: **3 x 15**
- previews output in the terminal before sending
- can publish via:
  - Vestaboard Cloud API
  - Vestaboard Local API

## Templates

- `text` — simple wrapped text
- `kv` — key/value rows
- `table` — compact table from CSV or JSON array of objects
- `metrics` — generic key/value layout with optional trailing color indicators
- `auto` — picks a reasonable renderer based on input shape

## Color indicators (experimental)

The `metrics` template supports trailing colored tile indicators on rows.
Color is driven by semantic tone — not raw cell placement.

**Auto-detection:** tone is inferred when a field name contains `pct`, `percent`,
`change`, `delta`, or `diff` and the value is numeric:
- positive → green
- negative → red
- zero → white

Keys ending in `_pct` or `_percent` also get two extra treatments: the suffix is
stripped from the label (so `wind_delta_pct` renders as `WIND DELTA`), and the
value is formatted with a `%` sign.

**Explicit tone:** override any field with `_style`:

```json
{
  "score": 91.2,
  "_style": {
    "score": "good"
  }
}
```

Accepted tone names: `good`, `bad`, `warn`, `info`, `neutral`, `muted`,
or any color directly: `green`, `red`, `yellow`, `blue`, `white`, `black`,
`violet`, `orange`.

**Range-based tone:** specify `good` and `bad` thresholds and the indicator
will follow a 4-step green → yellow → orange → red gradient. Direction is
implicit — wherever `good` sits numerically is the green end:

```json
{
  "bounce_rate": 68.4,
  "conversion": 3.2,
  "_style": {
    "bounce_rate": {"good": 30, "bad": 80},
    "conversion":  {"good": 8,  "bad": 2}
  }
}
```

`_style` and other `_`-prefixed keys are never shown on the board.

**Debug flag:** add `--explain` to see a breakdown of which fields got color
indicators, why, and what thresholds trigger each zone:

```bash
cat metrics.json | python vesta.py render --template metrics --preview-only --explain
```

## Layout flags

**`--valign [top|center]`** — vertical alignment of the content block.
Default is `top`. Use `center` when you have fewer rows of data than the
board height and want breathing room above and below.

**`--align [left|center]`** — horizontal alignment of metrics rows.
Default is `left`. Use `center` to indent the content block as a unit —
all rows start at the same left offset (determined by the widest row),
giving a cleaner look when the data is compact:

```
┌────────────── flagship 6x22 ───────────────┐
│                                            │
│      T E M P   6 8                         │
│      H U M I D I T Y   4 2                 │
│      W I N D   D E L T A   3 . 2 ██        │
│      R A I N   P C T   - 1 2 . 5 ██        │
│                                1 2 : 0 3 P │
└────────────────────────────────────────────┘
```

**`--timestamp`** — adds the current time (`10:01A`, `9:30P`) to the
bottom-right corner. Requires the timestamp width plus a 2-cell buffer to
be blank at the right of the last row — silently skipped if there isn't room.
Use **`--force-timestamp`** to place it regardless.

**`--tz`** — IANA timezone for the timestamp, e.g. `America/New_York`.
Defaults to local system time. 24h locale support is not yet handled.

```bash
cat metrics.json | python vesta.py render --template metrics \
  --valign center --align center --timestamp --preview-only
```

**Preview a saved board** — if the input is a raw character code grid (the
JSON output from `--json-only`), vesta decodes and previews it directly:

```bash
cat testdata/metrics_styled.json | python vesta.py render --template metrics --json-only > saved.json
cat saved.json | python vesta.py render --preview-only
```

## Why this exists

Hitting the Vestaboard API directly is easy.

The harder and more useful part is:
- making structured data fit well on a small grid
- compacting numbers and timestamps automatically
- previewing output locally before sending
- reusing layouts across scripts and data sources

This project is mainly about that rendering layer.

## Example usage

Render text:

```bash
echo '"hello world"' | python vesta.py render
```

Render a key/value dict:

```bash
echo '{"temp": "72F", "wind": "12mph"}' | python vesta.py render --template kv
```

Render a metrics payload with tone indicators:

```bash
cat metrics.json | python vesta.py render --template metrics
```

Preview only (no character output):

```bash
cat data.json | python vesta.py render --preview-only
```

Get raw character codes for the Vestaboard API:

```bash
cat data.json | python vesta.py render --json-only
```

Publish via Cloud API:

```bash
cat data.json | python vesta.py post-cloud --token $VESTABOARD_TOKEN
```

Publish via Local API:

```bash
cat data.json | python vesta.py post-local --api-key $VESTABOARD_LOCAL_API_KEY
```

Preview what's currently on your board:

```bash
python vesta.py read-cloud
```

Uses `VESTABOARD_TOKEN` from the environment. Board profile (flagship vs note) is
auto-detected from the grid dimensions returned by the API. Pass `--profile` to
override if needed.

Use the Note profile:

```bash
cat data.json | python vesta.py render --profile note --template metrics
```

## Current status

Early but functional. Some areas are still experimental:
- semantic color / tone indicators
- ANSI terminal preview rendering
- how much formatting logic belongs in templates vs shared helpers

Comments in the code mark anything that is still being tried and may change.
