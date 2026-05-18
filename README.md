# vesta

[![CI](https://github.com/q/vesta/actions/workflows/ci.yml/badge.svg)](https://github.com/q/vesta/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/vestaboard-tools)](https://pypi.org/project/vestaboard-tools/)
[![Python](https://img.shields.io/pypi/pyversions/vestaboard-tools)](https://pypi.org/project/vestaboard-tools/)
[![License](https://img.shields.io/github/license/q/vesta)](LICENSE)
[![Website](https://img.shields.io/badge/website-vestaboard.tools-blue)](https://vestaboard.tools)

A small Python formatter / previewer / publisher for Vestaboard devices. → **[vestaboard.tools](https://vestaboard.tools)**

**semantic input → board layout → terminal preview → optional publish**

<img src="docs/example.png" width="600" alt="Terminal preview showing a metrics board with color indicators and explain output" />

## What it does

- Formats structured data (JSON, CSV, plain text) for Vestaboard
- Supports multiple device profiles:
  - flagship: **6 × 22**
  - note: **3 × 15**
- Previews output in the terminal before sending
- Publishes via Vestaboard Cloud API or Local API

## Templates

| Template | Input | Behaviour |
|----------|-------|-----------|
| `text` | string | Wrapped and centered text |
| `kv` | JSON object | Key / value rows. Applies `_pct`/`_curr` suffix formatting; values otherwise treated as strings. |
| `data` | JSON object or array | Label/value rows (object) or columnar table (array). Applies suffix formatting and color indicators. |
| `auto` | any | Picks the best renderer based on input shape (default) |

`metrics` and `table` are accepted as aliases for `data`.

In most cases `--template` can be omitted — `auto` selects `kv`, `data`, or `text` based on input shape. Specify `--template kv` explicitly when you want the flush-right value layout for a JSON object instead of the metrics layout.

CSV is auto-detected — no `--template` flag needed.

## Key suffixes

Field name suffixes control formatting automatically. The suffix is stripped from the label on the board.

| Suffix | Effect |
|--------|--------|
| `_pct` / `_percent` | formats value as `3.2%` |
| `_curr` | formats value as `$184.2K` |

```json
{
  "revenue_curr": 184210.50,
  "sessions": 10823,
  "growth_pct": 12.4
}
```

Renders as:

```
REVENUE   $184.2K
SESSIONS  10.8K
GROWTH    12.4%
```

## Color indicators

A trailing colored tile is added to a field automatically when a color can be determined. Color is driven by meaning, not raw placement — you describe intent and vesta picks the tile.

There are three ways to assign color to a field:

**1. Auto-detection** — no `_style` needed. Fields whose name contains `change`, `delta`, or `diff` are colored automatically based on sign:
- positive → green
- negative → red
- zero → white

`_pct` / `_percent` control value formatting only — they do not trigger auto-detection. Use `_style` to add color to percentage fields explicitly.

**2. Explicit color via `_style`** — two forms accepted:

*Semantic tones* — name the intent, vesta picks the color:

| Tone | Color |
|------|-------|
| `good` | green |
| `bad` | red |
| `warn` | yellow |
| `info` | blue |
| `neutral` | white |
| `muted` | black |

```json
{
  "score": 91.2,
  "_style": { "score": "good" }
}
```

*Direct colors* — name the color explicitly: `green`, `red`, `yellow`, `blue`, `white`, `black`, `violet`, `orange`.
Aliases: `purple` → violet, `grey`/`gray` → black.

**3. Dynamic strategies** — the color depends on the field's value at render time:

*`"signed"`* — colors by sign: positive → green, negative → red, zero → white. Useful for numeric fields not named with `change`/`delta`/`diff`:

```json
{
  "margin_pct": 4.2,
  "_style": { "margin_pct": "signed" }
}
```

*Range object* — specify numeric thresholds for a 4-step gradient. The `good` and `bad` keys are threshold labels (not tone names) that mark which end of the scale is favorable; direction is inferred automatically:

```json
{
  "bounce_rate": 68.4,
  "_style": { "bounce_rate": {"good": 30, "bad": 80} }
}
```

| Zone | Color | Position |
|------|-------|----------|
| 1st quarter | green | 0–25% toward bad |
| 2nd quarter | yellow | 25–50% |
| 3rd quarter | orange | 50–75% |
| 4th quarter | red | 75–100% (and beyond) |

The range object also accepts an optional `"decimals"` key to fix the number of decimal places shown for percentage fields. Useful for "nines" availability metrics where the default rounding would collapse `99.97%` to `100%`:

```json
{
  "uptime_pct": 99.97,
  "_style": { "uptime_pct": {"good": 100, "bad": 95, "decimals": 2} }
}
```

**Suppressing a tile** — use `"none"` to prevent a color tile on a field that would otherwise get one (e.g. auto-detected fields where you want plain output):

```json
{
  "delta": 0,
  "_style": { "delta": "none" }
}
```

`_style` and other `_`-prefixed keys are never shown on the board.

Use `--explain` to see which fields got indicators and why:

```bash
cat metrics.json | vesta render --preview-only --explain
```

## Layout flags

**`--title TEXT`**

Adds a title row at the top with colored tile bookends. Tries 2 tiles each side, falls back to 1 if the text is long.

**`--title-color COLOR[,COLOR,COLOR]|none`**

Color of the bookend tiles. Defaults to `white`. Pass `none` for a plain centered title with no tiles. Pass up to 3 comma-separated colors to use multiple tiles — the right side mirrors the left: `--title-color red,blue,orange` places `red blue orange` on the left and `orange blue red` on the right. Falls back through fewer tiles if the title text is too long to fit.

**`--subtitle TEXT|time`**

Optional second row below the title, with a single tile bookend on each side (same color as title by default). Use the special value `time` to insert the current time. You can also embed the subtitle directly in the title using a newline — `--title $'Weather\nSan Francisco'` — and the second line becomes the subtitle automatically (explicit `--subtitle` takes precedence).

**`--subtitle-color COLOR`**

Color of the subtitle bookend tile. Defaults to the title color. Accepts the same values as `--title-color`.

**`--separator [PATTERN]`**

Adds a full-width row of colored tiles below the title block (after subtitle if present). Used alone, defaults to solid white. Accepts:

| Pattern | Result |
|---------|--------|
| *(omitted)* | solid white |
| `white`, `blue`, `red`, … | solid named color |
| `rainbow` | R O Y G B V cycling |
| `red,black` | alternating colors |

```bash
echo '{"temp":"68F","hum_pct":42,"co2":"820","noise":"38"}' | \
  vesta render --template kv --title "HOME" --separator rainbow --preview-only
```

```
┌────────────── flagship 6x22 ───────────────┐
│████              H O M E               ████│
│████████████████████████████████████████████│
│T E M P                               6 8 F │
│H U M                                 4 2 % │
│C O 2                                 8 2 0 │
│N O I S E                           3 8 D B │
└────────────────────────────────────────────┘
```

```bash
vesta render --input testdata/home.json --columns 2 \
  --title "HOME" --title-color white --subtitle time --preview-only
```

```
┌────────────── flagship 6x22 ───────────────┐
│████              H O M E               ████│
│██              1 2 : 0 9 A               ██│
│T E M P       6 8 F     H U M         4 2 % │
│C O 2         8 2 0     N O I S E   3 8 D B │
│D O O R S   S H U T     L I G H T       O N │
│H E A T       O F F     F A N S         O N │
└────────────────────────────────────────────┘
```

**`--columns [1|2]`** *(kv layout)*

Pack two key-value pairs per row instead of one. Each column is sized independently to its own content, which creates a natural gap between columns. Color indicators from `_style` or auto-detection still apply: left-column tiles appear in the gap; right-column tiles appear at the board's right edge. When using `auto` template (the default), passing `--columns 2` with a JSON object automatically selects kv layout.

```bash
echo '{"now":"62F","rain_pct":0,"high":"66F","low":"48F"}' | \
  vesta render --columns 2 --preview-only
```

```
┌────────────── flagship 6x22 ───────────────┐
│N O W     6 2 F             R A I N     0 % │
│H I G H   6 6 F             L O W     4 8 F │
│                                            │
│                                            │
│                                            │
│                                            │
└────────────────────────────────────────────┘
```

Falls back to `--columns 1` with a warning if the content is too wide for the profile.

**`--align [left|center|right]`**

For **metrics** (JSON object): controls horizontal placement. Default is `left`. Use `center` for a tight two-column block (labels left-aligned, values right-aligned, the whole block centered on the board). Color indicator tiles, when present, are placed immediately after the value column with no gap.

For **tables** (JSON array or CSV): default is `center` (compact block, centered). When columns are too wide to center comfortably, the layout automatically spreads left-to-right to avoid clipping. `left` and `right` spread columns edge-to-edge with equal inter-column gaps — first column anchored to the chosen edge, last column anchored to the opposite edge.

**`--valign [top|center]`**

Vertical alignment of the content block. Default is `top`. Use `center` for breathing room when you have fewer rows than the board height.

**`--timestamp`**

Adds the current time (`10:01A`, `9:30P`) to the bottom-right corner. Silently skipped if there isn't room. Use `--force-timestamp` to place it regardless, overwriting content if needed.

**`--tz`**

IANA timezone for the timestamp, e.g. `America/New_York`. Defaults to local system time.

**`--profile [flagship|note]`**

Board profile. Auto-detected from API grid dimensions when publishing. Defaults to flagship.

## Example usage

**Text:**

```bash
echo '"hello world"' | vesta render --preview-only
```

```
┌────────────── flagship 6x22 ───────────────┐
│                                            │
│                                            │
│          H E L L O   W O R L D             │
│                                            │
│                                            │
│                                            │
└────────────────────────────────────────────┘
```

**Key/value:**

```bash
echo '{"temp": "72F", "wind": "12mph"}' | vesta render --template kv --preview-only
```

```
┌────────────── flagship 6x22 ───────────────┐
│T E M P                               7 2 F │
│W I N D                           1 2 M P H │
│                                            │
│                                            │
│                                            │
│                                            │
└────────────────────────────────────────────┘
```

**Key/value 2-col with title:**

```bash
vesta render --input testdata/home.json --columns 2 \
  --title "HOME" --subtitle time --preview-only
```

```
┌────────────── flagship 6x22 ───────────────┐
│████              H O M E               ████│
│██              1 2 : 0 9 A               ██│
│T E M P       6 8 F     H U M         4 2 % │
│C O 2         8 2 0     N O I S E   3 8 D B │
│D O O R S   S H U T     L I G H T       O N │
│H E A T       O F F     F A N S         O N │
└────────────────────────────────────────────┘
```

**CSV table** (auto-detected, centered by default):

```bash
vesta render --input scores.csv --preview-only
```

```
┌────────────── flagship 6x22 ───────────────┐
│    N A M E       S C O R E     R A N K     │
│    A L I C E           9 8           1     │
│    B O B               8 7           2     │
│    C A R O L           7 6           3     │
│    D A V E             6 1           4     │
│                                            │
└────────────────────────────────────────────┘
```

Use `--align left` or `--align right` to spread columns edge-to-edge instead.

**Metrics with color indicators:**

```bash
echo '{
  "revenue_curr": 184210.50,
  "sessions": 10823,
  "conversion_pct": 13.2,
  "bounce_rate_pct": 48.4,
  "_style": {
    "revenue_curr": "good",
    "conversion_pct": {"good": 8, "bad": 2},
    "bounce_rate_pct": {"good": 30, "bad": 80}
  }
}' | vesta render --valign center --align center --timestamp --preview-only
```

```
┌────────────── flagship 6x22 ───────────────┐
│                                            │
│    R E V E N U E         $ 1 8 4 . 2 K ██  │
│    S E S S I O N S           1 0 . 8 K     │
│    C O N V E R S I O N       1 3 . 2 % ██  │
│    B O U N C E   R A T E     4 8 . 4 % ██  │
│                                  9 : 3 4 P │
└────────────────────────────────────────────┘
```

**Note profile:**

```bash
vesta render --input testdata/metrics_note.json --profile note --preview-only
```

```
┌───────── note 3x15 ──────────┐
│T E M P                 7 2   │
│H U M I D I T Y       5 4 %   │
│C H A N G E       - 2 . 1 % ██│
└──────────────────────────────┘
```

## Escape sequences

Color tiles and any Vestaboard character code can be embedded inline in text input using `{name}` or `{N}` syntax:

| Escape | Result |
|--------|--------|
| `{red}`, `{green}`, `{blue}`, … | Color tile |
| `{63}` – `{71}` | Color tile by code |
| `{0}` – `{62}` | Any other character code |
| `{anything_else}` | Rendered as `(anything_else)` |

Color names match the Vestaboard tile set: `red`, `orange`, `yellow`, `green`, `blue`, `violet`, `white`, `black`, `filled`. `purple` is accepted as an alias for `violet`. Names are case-insensitive.

```bash
echo "STATUS {green} ALL GOOD" | vesta render --preview-only
```

```
┌────────────── flagship 6x22 ───────────────┐
│    S T A T U S   ██  A L L   G O O D       │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
└────────────────────────────────────────────┘
```

```bash
echo "ALERT {red} CHECK ENGINE" | vesta render --preview-only
```

```
┌────────────── flagship 6x22 ───────────────┐
│  A L E R T   ██  C H E C K   E N G I N E   │
│                                            │
│                                            │
│                                            │
│                                            │
│                                            │
└────────────────────────────────────────────┘
```

**Get raw character codes** (for direct API use):

```bash
cat data.json | vesta render --json-only
```

## Publishing

**Cloud API:**

```bash
cat data.json | vesta post-cloud --token $VESTABOARD_TOKEN
```

Add `--forced` to send even during configured quiet hours:

```bash
cat data.json | vesta post-cloud --token $VESTABOARD_TOKEN --forced
```

**Local API:**

```bash
cat data.json | vesta post-local --api-key $VESTABOARD_LOCAL_API_KEY
```

`VESTABOARD_LOCAL_HOST` / `--host` should point only at your own Vestaboard Local API endpoint. The local API key is sent to that host.

**Preview current board state:**

```bash
vesta read-cloud
```

`VESTABOARD_TOKEN` is read from the environment. Board profile is auto-detected from the grid dimensions returned by the API. Pass `--profile` to override.

**Re-render a saved board:**

```bash
cat data.json | vesta render --json-only > saved.json
cat saved.json | vesta render --preview-only
```

## Installation

```bash
pip install vestaboard-tools
```

Or run directly from source with [uv](https://github.com/astral-sh/uv):

```bash
uv run vesta.py render
```

## Why this exists

Hitting the Vestaboard API directly is straightforward. The harder part is making structured data fit well on a small fixed-size grid — compacting numbers, handling suffixes, previewing locally, and reusing layouts across scripts and data sources. This project is mainly that rendering layer.
