# Numeric format control — design notes

## The problem

Auto-formatting works well most of the time but there's no escape hatch when it doesn't:

- `sessions: 10823` compacts to `10.8K` — no way to keep it as `10823`
- `temperature: 72.456` renders as `72.46` — no way to say "I want 1 decimal place"
- `ratio: 0.00342` renders as `0` via smart_round at 2 sig figs — loses meaning entirely

`--explain` now surfaces these transformations, which makes the problem visible, but doesn't solve it.

---

## Option A: `_format` metadata key

A new `_format` key parallel to `_style`. Keeps concerns separated — `_style` is color, `_format` is value display.

```json
{
  "sessions": 10823,
  "temperature": 72.456,
  "_format": {
    "sessions": "raw",
    "temperature": {"decimals": 1}
  }
}
```

### `"raw"` / suppression

Suppresses compaction and rounding — show the number as-is from the JSON value.

Open questions:
- **Name**: `"raw"` implies "exactly as written" but the board always uppercases. `"none"` is consistent with how `_style: "none"` suppresses color. `"full"` or `"no-compact"` are more descriptive.
- **Interaction with suffixes**: if `revenue_curr` has `_format: "raw"`, does it still show `$`? Probably yes — `raw` controls the number formatting step, not suffix behavior. So you'd get `$84210.5` not `$84.2K`.

### `{"decimals": N}`

Round to N decimal places before any other formatting.

- `{"decimals": 0}` on `10823` → `10823` (implicitly opts out of compaction since the value is already an integer string)
- `{"decimals": 1}` on `72.456` → `72.5`
- `{"decimals": 2}` on `0.00342` → `0.00` ← useless, which is a problem

### `{"sig_figs": N}`

Round to N significant figures. Better than decimals for variable-magnitude data.

- `{"sig_figs": 2}` on `0.00342` → `0.0034`
- `{"sig_figs": 3}` on `72.456` → `72.5`
- `{"sig_figs": 4}` on `10823` → `10820`

Consistent with `smart_round` which already uses sig figs internally.

### Does `{"decimals": N}` make `"raw"` unnecessary?

Mostly yes — `{"decimals": 0}` on an integer gets you the uncompacted value. The only thing `"raw"` adds is "show whatever Python gives me, I don't know how many decimals" — a narrow use case. Could skip `"raw"` entirely.

---

## Option B: `_sf` key suffixes

Suffix conventions alongside `_pct` and `_curr`. No new metadata key — consistent with how the rest of the system works.

Proposed: `_sf2`, `_sf3`, `_sf4` (significant figures 2–4).

```json
{
  "temperature_sf3": 72.456,
  "ratio_sf2": 0.00342,
  "sessions_sf4": 10823
}
```

Renders as: `72.5`, `0.0034`, `10820`.

Label stripping: `_sf2` strips from the label like `_pct` does, so `temperature_sf3` → `TEMPERATURE`.

### Edge cases

**Compaction interaction** — after rounding to N sig figs, does compaction still run?

- `sessions_sf2: 10823` → round to 2 sig figs → `11000` → compact → `11K`

Lean: yes, compaction still runs. Sig figs gives you precision control; compaction is a separate display concern. If you want `10823` verbatim, that's a different ask (`_format: "raw"` or `{"decimals": 0}`).

**Combining with `_pct` or `_curr`** — suffix detection is currently `endswith`, so only the last suffix matches. `revenue_curr_sf3` or `margin_pct_sf2` would not work without explicitly supporting multi-suffix parsing. Probably not worth the complexity — if you need sig figs on a currency field, `_format` is the better tool.

**Range** — why 2–4? `_sf1` is too coarse for most data. `_sf5+` is rarely meaningful on a small board. Could support any N but the named range (`_sf2`/`_sf3`/`_sf4`) covers the practical cases and is easy to document.

---

## Comparison

| | `_format` key | `_sf` suffixes |
|---|---|---|
| Consistency with existing system | New concept | Consistent with `_pct`, `_curr` |
| Combining with color (`_style`) | Independent | Independent |
| Combining with `_pct`/`_curr` | Works fine | Probably not supported |
| Suppressing compaction entirely | Yes (`"raw"`) | No (compaction still runs) |
| Arbitrary decimal places | Yes | No (sig figs only) |
| Discoverability | Needs docs | Visible in field names |

---

## Open questions

1. Is suppressing compaction entirely (`"raw"`) a real use case, or does sig figs cover everything?
2. For `_sf` suffixes: should compaction still run after rounding, or does `_sf` imply "show the exact rounded number"?
3. Do both options need to exist, or does one cover all the cases?
4. If `_format`, what's the right name for the suppression value — `"raw"`, `"none"`, `"full"`, `"no-compact"`?
