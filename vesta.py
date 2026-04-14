from __future__ import annotations

try:
    from importlib.metadata import version
    __version__ = version("vestaboard-tools")
except Exception:
    __version__ = "0.1.0"  # fallback when running from source uninstalled

import argparse
import csv
import io
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Any

import requests


# -----------------------------------------------------------------------------
# Profiles
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class BoardProfile:
    name: str
    rows: int
    cols: int


FLAGSHIP = BoardProfile("flagship", 6, 22)
NOTE = BoardProfile("note", 3, 15)

PROFILES = {
    FLAGSHIP.name: FLAGSHIP,
    NOTE.name: NOTE,
}


# -----------------------------------------------------------------------------
# Color cells
# NOTE: Experimental. Color/filled cells are a Vestaboard hardware feature.
# The Color enum maps directly to Vestaboard character codes 63–71.
# In the grid, a Color value represents a colored tile — not a text character.
# -----------------------------------------------------------------------------


class Color(IntEnum):
    RED = 63
    ORANGE = 64
    YELLOW = 65
    GREEN = 66
    BLUE = 67
    VIOLET = 68
    WHITE = 69
    BLACK = 70
    FILLED = 71


# ANSI escape codes used only in terminal preview.
# NOTE: Experimental — may be adjusted as we refine preview fidelity.
COLOR_TO_ANSI: dict[Color, str] = {
    Color.RED: "\033[31m",
    Color.ORANGE: "\033[38;5;208m",
    Color.YELLOW: "\033[33m",
    Color.GREEN: "\033[32m",
    Color.BLUE: "\033[34m",
    Color.VIOLET: "\033[35m",
    Color.WHITE: "\033[37m",
    Color.BLACK: "\033[90m",
    Color.FILLED: "\033[97m",
}
ANSI_RESET = "\033[0m"


# NOTE: Experimental semantic tone support. Callers use tone names ("good", "bad",
# etc.) rather than placing Color values directly. This is the intended public
# surface for color support — not raw Color placement in grids.
TONE_TO_COLOR: dict[str, Color] = {
    "good": Color.GREEN,
    "bad": Color.RED,
    "warn": Color.YELLOW,
    "info": Color.BLUE,
    "neutral": Color.WHITE,
    "muted": Color.BLACK,
    # Direct color names also accepted for explicitness.
    "green": Color.GREEN,
    "red": Color.RED,
    "yellow": Color.YELLOW,
    "blue": Color.BLUE,
    "white": Color.WHITE,
    "black": Color.BLACK,
    "violet": Color.VIOLET,
    "orange": Color.ORANGE,
}


# -----------------------------------------------------------------------------
# Character encoding
# Minimal encoder for Vestaboard-supported characters.
# Unsupported characters are replaced with spaces (code 0).
# -----------------------------------------------------------------------------


CHAR_TO_CODE: dict[str, int] = {" ": 0}
for _i, _ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ", start=1):
    CHAR_TO_CODE[_ch] = _i
for _i, _ch in enumerate("1234567890", start=27):
    CHAR_TO_CODE[_ch] = _i

CHAR_TO_CODE.update(
    {
        "!": 37,
        "@": 38,
        "#": 39,
        "$": 40,
        "(": 41,
        ")": 42,
        "-": 44,
        "+": 46,
        "&": 47,
        "=": 48,
        ";": 49,
        ":": 50,
        "'": 52,
        '"': 53,
        "%": 54,
        ",": 55,
        ".": 56,
        "/": 59,
        "?": 60,
        # Code 62 is a hardware quirk: Flagship renders it as ° (degree symbol),
        # Note renders it as ❤ (heart). Both characters map to code 62 here;
        # encode_cell handles the per-profile swap at encoding time.
        "°": 62,
        "❤": 62,
    }
)


# -----------------------------------------------------------------------------
# Core render model
# A Cell is either a single text character (str, len == 1) or a Color tile.
# Grid is a 2-D list of cells with dimensions matching the board profile exactly.
# -----------------------------------------------------------------------------


Cell = str | Color  # str: single printable char; Color: colored tile
Grid = list[list[Cell]]


@dataclass
class RenderedMessage:
    profile: BoardProfile
    grid: Grid

    def to_characters(self) -> list[list[int]]:
        """Encode the grid to Vestaboard character codes."""
        return [[encode_cell(cell, self.profile) for cell in row] for row in self.grid]

    def preview(self, visible_spaces: bool = True, cell_width: int = 2, ansi_color: bool = True) -> str:
        """Render a terminal-friendly preview of the board."""
        cell_width = max(1, cell_width)

        def show(cell: Cell) -> str:
            if isinstance(cell, Color):
                block = "█" * cell_width
                if ansi_color and cell in COLOR_TO_ANSI:
                    return f"{COLOR_TO_ANSI[cell]}{block}{ANSI_RESET}"
                return block
            if cell == " ":
                ch = "·" if visible_spaces else " "
            else:
                ch = cell
            return ch.ljust(cell_width)

        inner = ["│" + "".join(show(cell) for cell in row) + "│" for row in self.grid]
        preview_cols = self.profile.cols * cell_width
        top = "┌" + "─" * preview_cols + "┐"
        bottom = "└" + "─" * preview_cols + "┘"
        label = f" {self.profile.name} {self.profile.rows}x{self.profile.cols} "
        if len(label) + 2 <= len(top):
            start = max(1, (len(top) - len(label)) // 2)
            top = top[:start] + label + top[start + len(label) :]
        return "\n".join([top, *inner, bottom])


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def blank_grid(profile: BoardProfile, fill: str = " ") -> Grid:
    return [[fill for _ in range(profile.cols)] for _ in range(profile.rows)]


def normalize_text(text: str) -> str:
    return text.upper().replace("\t", " ")


def ellipsize(text: str, width: int) -> str:
    """Hard-truncate text to fit within width. No truncation marker — the board
    has no ellipsis character and there is rarely space to spare."""
    text = normalize_text(text)
    return text[:width]


def wrap_text(text: str, width: int, max_lines: int) -> list[str]:
    words = normalize_text(text).split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            if len(word) > width:
                lines.append(word[:width])
                current = ""
            else:
                current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if words and len(lines) == max_lines:
        consumed = sum(len(line.split()) for line in lines)
        if consumed < len(words):
            lines[-1] = ellipsize(lines[-1], width)
    return [line.ljust(width)[:width] for line in lines]


def place_line(grid: Grid, row_idx: int, text: str, align: str = "left", start_col: int = 0) -> None:
    available_width = len(grid[row_idx]) - start_col
    if available_width <= 0:
        return
    text = ellipsize(text, available_width)
    if align == "center":
        start = start_col + max(0, (available_width - len(text)) // 2)
    elif align == "right":
        start = start_col + max(0, available_width - len(text))
    else:
        start = start_col
    for i, ch in enumerate(text[:available_width]):
        grid[row_idx][start + i] = ch


def place_cell(grid: Grid, row_idx: int, col_idx: int, value: Cell) -> None:
    if 0 <= row_idx < len(grid) and 0 <= col_idx < len(grid[row_idx]):
        grid[row_idx][col_idx] = value


def place_title_row(grid: Grid, row_idx: int, text: str, color: Color | list[Color]) -> None:
    """Place a title row with colored tile bookends, text centered between them.
    color may be a single Color (tries 2 tiles then 1) or a list of 1–3 Colors
    (tries len(colors) tiles then fewer). Right side mirrors the left (reversed).
    Falls back to plain centered text if the text is too long for even 1 tile."""
    cols = len(grid[row_idx])
    text = text.upper()
    color_list: list[Color] = [color, color] if isinstance(color, Color) else list(color[:3])
    for bookend in range(len(color_list), 0, -1):
        inner = cols - 2 * bookend
        if len(text) <= inner:
            left = color_list[:bookend]
            right = list(reversed(left))
            for i, c in enumerate(left):
                grid[row_idx][i] = c
            for i, c in enumerate(right):
                grid[row_idx][cols - bookend + i] = c
            start = bookend + max(0, (inner - len(text)) // 2)
            for i, ch in enumerate(text):
                grid[row_idx][start + i] = ch
            return
    # Text fills the whole row — render plain so it isn't dropped entirely.
    place_line(grid, row_idx, text, align="center")


def _lead_color(color: Color | list[Color] | None, default: Color = Color.WHITE) -> Color:
    """Return the first (leftmost) color from a Color or list, for single-tile uses."""
    if color is None:
        return default
    return color[0] if isinstance(color, list) else color


def place_subtitle_row(grid: Grid, row_idx: int, text: str, color: Color) -> None:
    """Place a subtitle row with a single colored tile bookend on each side.
    Falls back to plain centered text if the text is too long to fit with tiles."""
    cols = len(grid[row_idx])
    text = text.upper()
    inner = cols - 2
    if len(text) <= inner:
        grid[row_idx][0] = color
        grid[row_idx][cols - 1] = color
        start = 1 + max(0, (inner - len(text)) // 2)
        for i, ch in enumerate(text):
            grid[row_idx][start + i] = ch
    else:
        place_line(grid, row_idx, text, align="center")


SEPARATOR_PATTERNS: dict[str, list[Color]] = {
    "rainbow": [Color.RED, Color.ORANGE, Color.YELLOW, Color.GREEN, Color.BLUE, Color.VIOLET],
}


def place_separator(grid: Grid, row_idx: int, pattern: str) -> None:
    """Fill a row with a repeating color pattern.
    Accepts a named pattern ('rainbow'), a single color name ('white'),
    or comma-separated color names ('red,black')."""
    cols = len(grid[row_idx])
    key = pattern.strip().lower()
    if key in SEPARATOR_PATTERNS:
        colors = SEPARATOR_PATTERNS[key]
    else:
        colors = [tone_to_color(p.strip()) or Color.WHITE for p in key.split(",")]
    for col in range(cols):
        grid[row_idx][col] = colors[col % len(colors)]


# -----------------------------------------------------------------------------
# Encoding / decoding
# -----------------------------------------------------------------------------


# Inverse of CHAR_TO_CODE. Code 62 always decodes to ° (degree symbol) —
# the heart glyph on the Note is a display quirk, not a separate character.
CODE_TO_CHAR: dict[int, str] = {v: k for k, v in CHAR_TO_CODE.items()}
CODE_TO_CHAR[62] = "°"


def from_characters(chars: list[list[int]], profile: BoardProfile) -> RenderedMessage:
    """Reconstruct a RenderedMessage from a raw Vestaboard character code grid."""
    # Code 62 hardware quirk: decode to the correct glyph for the profile.
    code62 = "❤" if profile.name == "note" else "°"
    grid: Grid = []
    for row in chars:
        grid_row: list[Cell] = []
        for code in row:
            if 63 <= code <= 71:
                grid_row.append(Color(code))
            elif code == 62:
                grid_row.append(code62)
            else:
                grid_row.append(CODE_TO_CHAR.get(code, " "))
        grid.append(grid_row)
    return RenderedMessage(profile=profile, grid=grid)


def is_raw_grid(payload: Any, profile: BoardProfile) -> bool:
    """Return True if payload looks like a Vestaboard character code grid for this profile."""
    return (
        isinstance(payload, list)
        and len(payload) == profile.rows
        and all(
            isinstance(row, list)
            and len(row) == profile.cols
            and all(isinstance(c, int) for c in row)
            for row in payload
        )
    )


def encode_cell(cell: Cell, profile: BoardProfile) -> int:
    if isinstance(cell, Color):
        return int(cell)

    ch = normalize_text(cell[:1] if cell else " ")
    # Code 62 hardware quirk: normalize regardless of which symbol the caller used.
    if ch == "❤" and profile.name != "note":
        ch = "°"
    if ch == "°" and profile.name == "note":
        ch = "❤"
    return CHAR_TO_CODE.get(ch, 0)


# -----------------------------------------------------------------------------
# Width / formatting helpers
# -----------------------------------------------------------------------------


def format_scalar(value: Any) -> str:
    if isinstance(value, float):
        if abs(value) >= 1_000_000:
            return f"{value / 1_000_000:.2f}M"
        if abs(value) >= 1_000:
            return f"{value / 1_000:.1f}K"
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


_PCT_SUFFIXES = ("_pct", "_percent")
_CURR_SUFFIXES = ("_curr",)


def key_is_pct(key: str) -> bool:
    lower = key.lower()
    return any(lower.endswith(s) for s in _PCT_SUFFIXES)


def key_is_curr(key: str) -> bool:
    lower = key.lower()
    return any(lower.endswith(s) for s in _CURR_SUFFIXES)


def prettify_label(key: str) -> str:
    label = normalize_text(key)
    # Strip trailing suffixes where the formatting carries the meaning.
    label = re.sub(r"[_ ]+(PCT|PERCENT|CURR)$", "", label)
    return label.replace("_", " ").strip()


def smart_round(value: float, sig_figs: int = 2) -> str:
    """Format a number to sig_figs significant figures, stripping trailing zeros."""
    if value == 0:
        return "0"
    magnitude = math.floor(math.log10(abs(value)))
    decimals = max(0, sig_figs - 1 - magnitude)
    # Use ROUND_HALF_UP to avoid Python's default banker's rounding (e.g. -12.5 → -13, not -12).
    factor = 10 ** decimals
    rounded = math.copysign(math.floor(abs(value) * factor + 0.5) / factor, value)
    formatted = f"{rounded:.{decimals}f}"
    if decimals > 0:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted


def compact_number(value: float, decimals: int = 2) -> str:
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.{decimals}f}".rstrip("0").rstrip(".") + "B"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.{decimals}f}".rstrip("0").rstrip(".") + "M"
    if abs_value >= 1_000:
        return f"{value / 1_000:.1f}".rstrip("0").rstrip(".") + "K"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def try_parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None

    raw = value.strip()
    if not raw:
        return None

    candidates = [
        raw,
        raw.replace("Z", "+00:00"),
        raw.replace(" ET", ""),
        raw.replace(" UTC", ""),
        raw.replace("T", " "),
    ]
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%m/%d/%Y %H:%M",
        "%m/%d/%y %H:%M",
    ]

    for candidate in candidates:
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            pass
        for fmt in formats:
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
    return None


def compact_datetime(value: Any, profile: BoardProfile) -> str:
    dt = try_parse_datetime(value)
    if dt is None:
        max_len = 10 if profile.cols <= 15 else 12
        return ellipsize(normalize_text(str(value)), max_len)

    suffix = "A" if dt.hour < 12 else "P"
    hour_12 = dt.hour % 12 or 12

    if profile.cols <= 15:
        return f"{hour_12}:{dt.minute:02d}{suffix}"
    return f"{dt.month}/{dt.day} {hour_12}:{dt.minute:02d}{suffix}"


def format_metric_value(value: Any, kind: str, profile: BoardProfile) -> str:
    if kind == "datetime":
        return compact_datetime(value, profile)

    if isinstance(value, (int, float)):
        n = float(value)
        if kind in ("currency", "currency_short"):
            if abs(n) >= 1_000:
                return f"${compact_number(n)}"
            return f"${n:.2f}"
        if kind == "percent":
            return f"{smart_round(n, sig_figs=3)}%"
    if kind == "percent":
        s = normalize_text(format_scalar(value))
        return s if s.endswith("%") else s + "%"
    if kind in ("currency", "currency_short"):
        try:
            n = float(str(value).lstrip("$").replace(",", "").strip())
            if abs(n) >= 1_000:
                return f"${compact_number(n)}"
            return f"${n:.2f}"
        except ValueError:
            s = normalize_text(format_scalar(value))
            return s if s.startswith("$") else "$" + s
        if kind == "number":
            return compact_number(n if abs(n) >= 1000 else n, decimals=2 if abs(n) < 100 else 1)
        if kind == "auto":
            return compact_number(n)

    if kind == "auto":
        parsed_dt = try_parse_datetime(value)
        if parsed_dt is not None:
            return compact_datetime(parsed_dt, profile)

    return normalize_text(format_scalar(value))


def infer_widths(columns: list[str], rows: list[dict[str, Any]], total_width: int) -> dict[str, int]:
    if not columns:
        return {}

    natural = {}
    for col in columns:
        header = len(col.replace("_", " ").upper())
        vals = [len(normalize_text(format_scalar(r.get(col, "")))) for r in rows]
        natural[col] = max([header, *vals, 1])

    separators = max(0, len(columns) - 1)
    available = total_width - separators
    base = {col: min(natural[col], max(4, available // len(columns))) for col in columns}
    used = sum(base.values())
    remaining = max(0, available - used)

    while remaining > 0:
        made_progress = False
        for col in columns:
            if base[col] < natural[col]:
                base[col] += 1
                remaining -= 1
                made_progress = True
                if remaining == 0:
                    break
        if not made_progress:
            break

    return base


# -----------------------------------------------------------------------------
# Tone resolution
# NOTE: Experimental. Tones drive the trailing color indicator in render_metrics.
# Auto-detection uses key name heuristics (change/delta/diff → positive/negative).
# _pct/_percent only controls value formatting, not color. Use _style to add color
# to percentage fields explicitly. Callers can override per-field via _style.
# Range-based coloring: {"good": <threshold>, "bad": <threshold>} maps a value
# to a 4-step green→yellow→orange→red gradient. Direction is implicit — wherever
# "good" sits numerically is the green end.
# -----------------------------------------------------------------------------


def tone_from_range(value: float, good: float, bad: float) -> str:
    """Map a value to a 4-step tone gradient between good (green) and bad (red).
    NOTE: Experimental — part of the range-based color support in _style."""
    if good == bad:
        return "neutral"
    t = max(0.0, min(1.0, (value - good) / (bad - good)))
    if t < 0.25:
        return "good"    # green
    if t < 0.5:
        return "warn"    # yellow
    if t < 0.75:
        return "orange"  # orange
    return "bad"         # red


def resolve_tone(data: dict[str, Any], key: str, value: Any) -> str | None:
    """Resolve a semantic tone for a field. Returns a tone name or None."""
    style = data.get("_style")
    if isinstance(style, dict) and key in style:
        override = style[key]
        if isinstance(override, str):
            return override.lower()
        if isinstance(override, dict):
            # Range-based: {"good": <threshold>, "bad": <threshold>}
            if "good" in override and "bad" in override and isinstance(value, (int, float)):
                return tone_from_range(float(value), float(override["good"]), float(override["bad"]))
            tone = override.get("tone")
            if isinstance(tone, str):
                return tone.lower()

    # Auto-detect tone for fields whose key name implies a change/delta.
    # Try to coerce string values to float (strip trailing % if present) so that
    # "42" and "42%" behave the same as 42 when the key signals a percentage/change.
    lower_key = key.lower()
    if any(p in lower_key for p in ("change", "delta", "diff")):
        n: float | None = None
        if isinstance(value, (int, float)):
            n = float(value)
        elif isinstance(value, str) and key_is_pct(key):
            # Coerce string values only for explicit _pct/_percent suffix keys —
            # "42" and "42%" are unambiguously percentages when the key declares it.
            try:
                n = float(value.rstrip("%").strip())
            except ValueError:
                pass
        if n is not None:
            if n > 0:
                return "good"
            if n < 0:
                return "bad"
            return "neutral"

    return None


def tone_to_color(tone: str | None) -> Color | None:
    """Map a tone name to a Color tile, or None if the tone is unknown."""
    if not tone:
        return None
    return TONE_TO_COLOR.get(tone.lower())


# -----------------------------------------------------------------------------
# Renderers
# -----------------------------------------------------------------------------


def render_text(profile: BoardProfile, text: str, align: str = "center", valign: str = "center") -> RenderedMessage:
    grid = blank_grid(profile)
    lines = wrap_text(text, profile.cols, profile.rows)
    if valign == "center":
        top = max(0, (profile.rows - len(lines)) // 2)
    else:
        top = 0
    for i, line in enumerate(lines):
        place_line(grid, top + i, line.rstrip(), align=align)
    return RenderedMessage(profile=profile, grid=grid)


def _kv_format_value(key: str, value: Any) -> str:
    """Format a kv value, appending % for _pct keys or $ for _curr keys when missing."""
    s = normalize_text(format_scalar(value))
    if key_is_pct(key) and not s.endswith("%"):
        return s + "%"
    if key_is_curr(key) and not s.startswith("$"):
        return "$" + s
    return s


def render_kv(profile: BoardProfile, data: dict[str, Any], title: str | None = None, title_color: Color | list[Color] | None = None, subtitle: str | None = None, columns: int = 1, separator: str | None = None) -> RenderedMessage:
    import sys
    grid = blank_grid(profile)
    row = 0
    if title:
        if title_color is not None:
            place_title_row(grid, row, title, title_color)
        else:
            place_line(grid, row, title, align="center")
        row += 1
    if subtitle and title and row < profile.rows:
        place_subtitle_row(grid, row, subtitle, _lead_color(title_color))
        row += 1
    if separator and row < profile.rows:
        place_separator(grid, row, separator)
        row += 1

    style = data.get("_style") if isinstance(data.get("_style"), dict) else None
    # Skip internal hint keys (e.g. _style, _template).
    items = [(k, v) for k, v in data.items() if not k.startswith("_")]

    if columns == 2:
        from itertools import zip_longest

        max_rows = max(0, profile.rows - row)
        items = items[: max_rows * 2]
        left_items = items[::2]
        right_items = items[1::2]

        def _col_widths(col_items: list) -> tuple[int, int]:
            lw = max((len(prettify_label(k)) for k, _ in col_items), default=0)
            vw = max((len(_kv_format_value(k, v)) for k, v in col_items), default=0)
            return lw, vw

        # Per-column widths (not global max) so the natural gap between columns reflects
        # the actual content, rather than being squeezed by whichever column has the longest value.
        left_lw, left_vw = _col_widths(left_items)
        right_lw, right_vw = _col_widths(right_items) if right_items else (0, 0)
        left_pw = left_lw + 1 + left_vw
        right_pw = right_lw + 1 + right_vw if right_items else 0  # 0, not 1, when right col is empty

        # Fall back to 1-col if the content is too wide: need left pair + 1-col gap + right label.
        if right_items and left_pw + 1 + right_lw > profile.cols:
            print(f"warning: content too wide for --columns 2 on '{profile.name}', falling back to 1", file=sys.stderr)
            columns = 1
        else:
            # Reserve 1 col at the right edge when any right-column entry has a color
            # (explicit _style or auto-detected from key name), so the tile appears
            # after the value rather than before the label.
            right_has_color = any(
                tone_to_color(resolve_tone(data, k, v)) for k, v in right_items
            )
            right_reserve = 1 if right_has_color else 0

            # Trim right value width if needed to keep at least a 1-col gap.
            if left_pw + right_pw + right_reserve >= profile.cols:
                right_vw = max(0, profile.cols - left_pw - right_lw - 2 - right_reserve)
                right_pw = right_lw + 1 + right_vw if right_items else 0
            gap = max(1, profile.cols - left_pw - right_pw - right_reserve)
            right_start = left_pw + gap

            pairs = list(zip_longest(left_items, right_items))
            for left_item, right_item in pairs:
                if row >= profile.rows:
                    break

                if left_item is not None:
                    lk, lv = left_item
                    label = ellipsize(prettify_label(lk), left_lw).ljust(left_lw)
                    value = ellipsize(_kv_format_value(lk, lv), left_vw).rjust(left_vw)
                    place_line(grid, row, f"{label} {value}", align="left", start_col=0)
                    # Color tile for left column sits in the gap cell right after the value.
                    # gap = max(1, …) guarantees right_start > left_pw, so the tile at
                    # left_pw never overlaps the right label that starts at right_start.
                    color = tone_to_color(resolve_tone(data, lk, lv))
                    if color:
                        place_cell(grid, row, left_pw, color)

                if right_item is not None:
                    rk, rv = right_item
                    label = ellipsize(prettify_label(rk), right_lw).ljust(right_lw)
                    value = ellipsize(_kv_format_value(rk, rv), right_vw).rjust(right_vw)
                    place_line(grid, row, f"{label} {value}", align="left", start_col=right_start)
                    # Color tile for right column goes at the board's right edge.
                    if right_reserve:
                        color = tone_to_color(resolve_tone(data, rk, rv))
                        if color:
                            place_cell(grid, row, profile.cols - 1, color)

                row += 1
            return RenderedMessage(profile=profile, grid=grid)

    # columns == 1 path
    # Reserve 1 cell for a color tile only when an entry will actually produce one.
    # Check resolve_tone unconditionally — auto-detection works without _style.
    has_any_color = any(tone_to_color(resolve_tone(data, k, v)) for k, v in items)
    reserve = 1 if has_any_color and profile.cols >= 12 else 0
    items = items[: max(0, profile.rows - row)]

    for key, value in items:
        if row >= profile.rows:
            break
        key_s = prettify_label(key)
        value_s = _kv_format_value(key, value)
        if profile.cols >= 18:
            left_width = min(max(len(key_s), 6), profile.cols // 2)
            right_width = profile.cols - left_width - 1 - reserve
            left = ellipsize(key_s, left_width).ljust(left_width)
            right = ellipsize(value_s, right_width).rjust(right_width)
            place_line(grid, row, f"{left} {right}", align="left")
            color = tone_to_color(resolve_tone(data, key, value))
            if color and reserve:
                place_cell(grid, row, profile.cols - 1, color)
        else:
            place_line(grid, row, ellipsize(key_s, profile.cols - 1), align="left")
            row += 1
            if row >= profile.rows:
                break
            place_line(grid, row, ellipsize(value_s, profile.cols), align="right")
        row += 1

    return RenderedMessage(profile=profile, grid=grid)


def render_table(profile: BoardProfile, rows: list[dict[str, Any]], title: str | None = None, title_color: Color | list[Color] | None = None, subtitle: str | None = None, align: str | None = None, separator: str | None = None) -> RenderedMessage:
    import sys
    align = align or "center"
    grid = blank_grid(profile)
    row_idx = 0

    if title:
        if title_color is not None:
            place_title_row(grid, row_idx, title, title_color)
        else:
            place_line(grid, row_idx, title, align="center")
        row_idx += 1
    if subtitle and title and row_idx < profile.rows:
        place_subtitle_row(grid, row_idx, subtitle, _lead_color(title_color))
        row_idx += 1
    if separator and row_idx < profile.rows:
        place_separator(grid, row_idx, separator)
        row_idx += 1

    if not rows:
        if row_idx < profile.rows:
            place_line(grid, row_idx, "NO DATA", align="center")
        return RenderedMessage(profile=profile, grid=grid)

    # Determine color-tile reserve first (based on all columns).
    all_columns = list(rows[0].keys())
    color_col = next((c for c in reversed(all_columns) if tone_to_color(resolve_tone({c: 0}, c, 0))), None)
    reserve = 1 if color_col and profile.cols >= 12 else 0
    available_cols = profile.cols - reserve

    # Fit as many columns as possible (minimum usable width: 3 chars each).
    MIN_COL_WIDTH = 3
    columns = []
    for col in all_columns:
        n = len(columns) + 1
        if (available_cols - (n - 1)) // n >= MIN_COL_WIDTH:
            columns.append(col)
        else:
            break
    dropped = all_columns[len(columns):]
    if dropped:
        print(f"warning: {len(dropped)} column(s) dropped (board too narrow): {', '.join(dropped)}", file=sys.stderr)

    # Determine which columns are purely numeric (for header alignment).
    numeric_cols = {
        col for col in columns
        if rows and all(isinstance(record.get(col, ""), (int, float)) for record in rows)
    }

    def fmt_header(col: str, width: int) -> str:
        label = ellipsize(prettify_label(col), width)
        return label.rjust(width) if col in numeric_cols else label.ljust(width)

    def fmt_cell(col: str, value: Any, width: int, formatted: str) -> str:
        cell = ellipsize(formatted, width)
        return cell.rjust(width) if isinstance(value, (int, float)) else cell.ljust(width)

    # Use formatted values for width inference.
    formatted_rows = [
        {col: format_field(col, record.get(col, ""), profile)[1] for col in columns}
        for record in rows
    ]
    widths = infer_widths(columns, formatted_rows, available_cols)

    # For left/right: distribute extra horizontal space as inter-column gaps so
    # columns span the full board width. For center: compact block, centered.
    if align in ("left", "right") and len(columns) > 1:
        total_content = sum(widths[col] for col in columns)
        extra = available_cols - total_content
        n_gaps = len(columns) - 1
        sep_base = extra // n_gaps
        sep_rem = extra % n_gaps
        col_starts = []
        pos = 0
        for i, col in enumerate(columns):
            col_starts.append(pos)
            if i < n_gaps:
                gap = sep_base + (1 if (align == "left" and i < sep_rem) or (align == "right" and i >= n_gaps - sep_rem) else 0)
                pos += widths[col] + gap

        def place_row(row_idx: int, cells: list[str]) -> None:
            for col, start, cell in zip(columns, col_starts, cells):
                place_line(grid, row_idx, cell, align="left", start_col=start)

        if row_idx < profile.rows:
            place_row(row_idx, [fmt_header(col, widths[col]) for col in columns])
            row_idx += 1

        visible_rows = rows[: max(0, profile.rows - row_idx)]
        for record in visible_rows:
            row_color = None
            data_cells = []
            for col in columns:
                value = record.get(col, "")
                _, formatted, color = format_field(col, value, profile)
                if color:
                    row_color = color
                data_cells.append(fmt_cell(col, value, widths[col], formatted))
            if row_idx < profile.rows:
                place_row(row_idx, data_cells)
                if row_color and reserve:
                    place_cell(grid, row_idx, profile.cols - 1, row_color)
                row_idx += 1
    else:
        # Center (or single-column): compact block.
        # Prefer a 2-space inter-column separator for breathing room; fall back
        # to 1 if the content is too wide to fit.
        n_gaps = len(columns) - 1
        content_width = sum(widths[col] for col in columns)
        sep = "  " if n_gaps > 0 and content_width + 2 * n_gaps <= available_cols else " "

        header = sep.join(fmt_header(col, widths[col]) for col in columns)
        if row_idx < profile.rows:
            place_line(grid, row_idx, header, align=align)
            row_idx += 1

        visible_rows = rows[: max(0, profile.rows - row_idx)]
        for record in visible_rows:
            cells = []
            row_color = None
            for col in columns:
                value = record.get(col, "")
                _, formatted, color = format_field(col, value, profile)
                if color:
                    row_color = color
                cells.append(fmt_cell(col, value, widths[col], formatted))
            if row_idx < profile.rows:
                place_line(grid, row_idx, sep.join(cells), align=align)
                if row_color and reserve:
                    place_cell(grid, row_idx, profile.cols - 1, row_color)
                row_idx += 1

    return RenderedMessage(profile=profile, grid=grid)


def format_field(key: str, value: Any, profile: BoardProfile, style: dict | None = None) -> tuple[str, str, Color | None]:
    """Shared field formatting: returns (label, formatted_value, color).
    Applies suffix conventions (_pct, _curr), value formatting, and tone resolution."""
    is_pct = key_is_pct(key)
    is_curr = key_is_curr(key)
    if isinstance(value, (int, float)):
        kind = "percent" if is_pct else "currency" if is_curr else "auto"
    elif is_pct:
        kind = "percent"
    elif is_curr:
        kind = "currency"
    else:
        kind = "auto"
    label = prettify_label(key)
    formatted = format_metric_value(value, kind, profile)
    data = {key: value}
    if style:
        data["_style"] = style
    color = tone_to_color(resolve_tone(data, key, value))
    return label, formatted, color


def render_data(profile: BoardProfile, payload: dict[str, Any] | list[dict[str, Any]], title: str | None = None, title_color: Color | list[Color] | None = None, subtitle: str | None = None, valign: str = "top", align: str | None = None, separator: str | None = None) -> RenderedMessage:
    """Unified renderer for structured data. Accepts a dict (label/value rows) or
    a list of dicts (columnar table). Applies _pct/_curr suffix formatting and
    color indicators to all fields regardless of layout."""
    if isinstance(payload, list):
        return render_table(profile, payload, title=title, title_color=title_color, subtitle=subtitle, align=align, separator=separator)
    return render_metrics(profile, payload, title=title, title_color=title_color, subtitle=subtitle, valign=valign, align=align or "left", separator=separator)


def render_metrics(profile: BoardProfile, data: dict[str, Any], title: str | None = None, title_color: Color | list[Color] | None = None, subtitle: str | None = None, valign: str = "top", align: str = "left", separator: str | None = None) -> RenderedMessage:
    style = data.get("_style") if isinstance(data.get("_style"), dict) else None
    entries = []
    for key, value in data.items():
        if key.startswith("_"):
            continue
        label, formatted, color = format_field(key, value, profile, style=style)
        entries.append({"key": key, "label": label, "value": formatted, "tone": color, "color": color})

    title_rows = (1 if title else 0) + (1 if subtitle and title else 0) + (1 if separator else 0)
    n_entries = min(len(entries), profile.rows - title_rows)
    used_rows = title_rows + n_entries
    top = (profile.rows - used_rows) // 2 if valign == "center" else 0

    grid = blank_grid(profile)
    row = top
    if title:
        if title_color is not None:
            place_title_row(grid, row, title, title_color)
        else:
            place_line(grid, row, title, align="center")
        row += 1
    if subtitle and title and row < profile.rows:
        place_subtitle_row(grid, row, subtitle, _lead_color(title_color))
        row += 1
    if separator and row < profile.rows:
        place_separator(grid, row, separator)
        row += 1

    if align == "center":
        def natural_width(entry: dict) -> int:
            has_color = entry["color"] is not None and profile.cols >= 12
            return len(entry["label"]) + 1 + len(entry["value"]) + (1 if has_color else 0)

        max_width = min(max((natural_width(e) for e in entries[:n_entries]), default=0), profile.cols)
        start_col = max(0, (profile.cols - max_width) // 2)

        for entry in entries[:n_entries]:
            color = entry["color"]
            label = ellipsize(entry["label"], profile.cols)
            value = ellipsize(entry["value"], profile.cols)
            text = f"{label} {value}"
            place_line(grid, row, text, align="left", start_col=start_col)
            if color and profile.cols >= 12:
                place_cell(grid, row, start_col + len(text), color)
            row += 1
            if row >= profile.rows:
                break
    else:
        for entry in entries[:n_entries]:
            color = entry["color"]

            reserve_cols = 1 if color and profile.cols >= 12 else 0
            available_width = profile.cols - reserve_cols
            min_value_space = min(len(entry["value"]), max(4, available_width // 3))
            left_width = max(4, min(len(entry["label"]), available_width - min_value_space - 1))
            right_width = max(1, available_width - left_width - 1)
            left = ellipsize(entry["label"], left_width).ljust(left_width)
            right = ellipsize(entry["value"], right_width).rjust(right_width)
            place_line(grid, row, f"{left} {right}", align="left")

            if color and profile.cols >= 12:
                place_cell(grid, row, profile.cols - 1, color)
            row += 1
            if row >= profile.rows:
                break

    return RenderedMessage(profile=profile, grid=grid)


def render_auto(profile: BoardProfile, payload: Any, title: str | None = None, title_color: Color | list[Color] | None = None, subtitle: str | None = None, align: str | None = None, valign: str = "top", separator: str | None = None) -> RenderedMessage:
    """Infer the best renderer from the payload type and content."""
    if isinstance(payload, str):
        return render_text(profile, payload, valign=valign)
    if isinstance(payload, dict):
        return render_data(profile, payload, title=title, title_color=title_color, subtitle=subtitle, align=align, valign=valign, separator=separator)
    if isinstance(payload, list) and payload and all(isinstance(x, dict) for x in payload):
        return render_data(profile, payload, title=title, title_color=title_color, subtitle=subtitle, align=align, valign=valign, separator=separator)
    return render_text(profile, json.dumps(payload, separators=(",", ":")), align="left", valign=valign)


# -----------------------------------------------------------------------------
# Input parsing
# -----------------------------------------------------------------------------


def load_payload(path: str | None) -> Any:
    if path and path != "-":
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    else:
        raw = sys.stdin.read()
    raw = raw.strip()
    if not raw:
        return ""

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    try:
        reader = csv.DictReader(io.StringIO(raw))
        rows = list(reader)
        if rows and reader.fieldnames:
            coerced = []
            for row in rows:
                new_row = {}
                for k, v in row.items():
                    try:
                        new_row[k] = int(v)
                    except (ValueError, TypeError):
                        try:
                            new_row[k] = float(v)
                        except (ValueError, TypeError):
                            new_row[k] = v
                coerced.append(new_row)
            return coerced
    except Exception:
        pass

    return raw


# -----------------------------------------------------------------------------
# Publishers
# -----------------------------------------------------------------------------


def _detect_profile(chars: list[list[int]]) -> BoardProfile:
    """Infer board profile from grid dimensions. Falls back to flagship if unknown."""
    rows, cols = len(chars), len(chars[0]) if chars else 0
    for profile in PROFILES.values():
        if profile.rows == rows and profile.cols == cols:
            return profile
    return FLAGSHIP


def read_cloud(token: str, profile: BoardProfile | None = None, timeout: int = 10) -> RenderedMessage:
    """Fetch the current board state from the Vestaboard Cloud RW API."""
    r = requests.get(
        "https://rw.vestaboard.com/",
        headers={"X-Vestaboard-Read-Write-Key": token},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    # layout is a JSON-encoded string (not a parsed array), so double-parse.
    chars = json.loads(data["currentMessage"]["layout"])
    return from_characters(chars, profile or _detect_profile(chars))


def post_cloud(token: str, message: RenderedMessage, timeout: int = 10) -> dict[str, Any]:
    payload = {"characters": message.to_characters()}
    r = requests.post(
        "https://cloud.vestaboard.com/",
        headers={
            "Content-Type": "application/json",
            "X-Vestaboard-Token": token,
        },
        json=payload,
        timeout=timeout,
    )
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return {"status": r.status_code, "text": r.text}


def post_local(
    api_key: str,
    message: RenderedMessage,
    host: str = "http://vestaboard.local:7000",
    strategy: str | None = None,
    step_interval_ms: int | None = None,
    step_size: int | None = None,
    timeout: int = 10,
) -> dict[str, Any]:
    payload: Any = message.to_characters()
    if strategy or step_interval_ms or step_size:
        payload = {"characters": message.to_characters()}
        if strategy:
            payload["strategy"] = strategy
        if step_interval_ms is not None:
            payload["step_interval_ms"] = step_interval_ms
        if step_size is not None:
            payload["step_size"] = step_size

    r = requests.post(
        f"{host.rstrip('/')}/local-api/message",
        headers={
            "Content-Type": "application/json",
            "X-Vestaboard-Local-Api-Key": api_key,
        },
        json=payload,
        timeout=timeout,
    )
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return {"status": r.status_code, "text": r.text}


# -----------------------------------------------------------------------------
# Timestamp
# -----------------------------------------------------------------------------


def compact_time(dt: datetime) -> str:
    """Format a datetime as a short 12h time string: 10:01A, 9:30P.
    NOTE: 24h locale support is not yet handled — always uses 12h with A/P suffix."""
    suffix = "A" if dt.hour < 12 else "P"
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.minute:02d}{suffix}"


def place_timestamp(message: RenderedMessage, tz: str | None = None, force: bool = False) -> RenderedMessage:
    """Place the current time in the bottom-right of the grid if there is room.
    Requires the timestamp width plus a 2-cell buffer to be blank at the right
    of the last row. Silently skipped if there isn't room, unless force=True.
    tz accepts IANA timezone strings (e.g. 'America/New_York'); defaults to local time."""
    if tz:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(tz))
    else:
        now = datetime.now()

    ts = compact_time(now)
    last_row = message.grid[-1]
    buffer = 2
    has_room = all(cell == " " for cell in last_row[-(len(ts) + buffer):])
    if has_room or force:
        place_line(message.grid, message.profile.rows - 1, ts, align="right")
    return message


# -----------------------------------------------------------------------------
# Debug / explain
# NOTE: Experimental — tied to the experimental tone/color system.
# -----------------------------------------------------------------------------


def _ansi_block(color: Color, ansi: bool) -> str:
    if ansi and color in COLOR_TO_ANSI:
        return f"{COLOR_TO_ANSI[color]}██{ANSI_RESET}"
    return "██"


def explain_metrics(data: dict[str, Any], profile: BoardProfile, ansi_color: bool = True) -> str:
    """Return a human-readable breakdown of tone/color decisions for a metrics payload.
    Returns an empty string if no color indicators are present."""
    style = data.get("_style") if isinstance(data.get("_style"), dict) else {}
    rows = []

    for key, value in data.items():
        if key.startswith("_"):
            continue
        tone = resolve_tone(data, key, value)
        color = tone_to_color(tone)
        if color is None:
            continue

        label = prettify_label(key)
        fmt_value = format_metric_value(value, "auto", profile)
        block = _ansi_block(color, ansi_color)
        override = style.get(key)

        if isinstance(override, str):
            rows.append(f"  {label:<20} {fmt_value:>8}   {block} explicit")

        elif isinstance(override, dict) and "good" in override and "bad" in override:
            good = float(override["good"])
            bad = float(override["bad"])
            b1 = good + (bad - good) * 0.25
            b2 = good + (bad - good) * 0.50
            b3 = good + (bad - good) * 0.75

            if good < bad:
                zones = (
                    f"{_ansi_block(Color.GREEN,  ansi_color)}≤{b1:g}"
                    f" · {_ansi_block(Color.YELLOW, ansi_color)}{b1:g}–{b2:g}"
                    f" · {_ansi_block(Color.ORANGE, ansi_color)}{b2:g}–{b3:g}"
                    f" · {_ansi_block(Color.RED,    ansi_color)}≥{b3:g}"
                )
            else:
                zones = (
                    f"{_ansi_block(Color.GREEN,  ansi_color)}≥{b1:g}"
                    f" · {_ansi_block(Color.YELLOW, ansi_color)}{b2:g}–{b1:g}"
                    f" · {_ansi_block(Color.ORANGE, ansi_color)}{b3:g}–{b2:g}"
                    f" · {_ansi_block(Color.RED,    ansi_color)}≤{b3:g}"
                )
            rows.append(f"  {label:<20} {fmt_value:>8}   {block} range good={good:g} bad={bad:g}   {zones}")

        else:
            rows.append(f"  {label:<20} {fmt_value:>8}   {block} auto")

    if not rows:
        return ""
    return "\n".join(["── color indicators " + "─" * 20, *rows])


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def build_message(profile: BoardProfile, template: str, payload: Any, title: str | None, valign: str = "top", align: str | None = None, title_color: Color | list[Color] | None = None, subtitle: str | None = None, tz: str | None = None, columns: int = 1, separator: str | None = None) -> RenderedMessage:
    # A newline in the title splits it: first line → title, second line → subtitle
    # (only when no explicit subtitle was provided).
    if title and "\n" in title:
        parts = title.split("\n", 1)
        title = parts[0]
        if not subtitle:
            subtitle = parts[1]

    # Resolve subtitle "time" keyword to actual current time string
    resolved_subtitle: str | None = None
    if subtitle and title:
        if subtitle.lower() == "time":
            if tz:
                from zoneinfo import ZoneInfo
                now = datetime.now(ZoneInfo(tz))
            else:
                now = datetime.now()
            resolved_subtitle = compact_time(now)
        else:
            resolved_subtitle = subtitle

    if columns > 1 and template == "auto" and isinstance(payload, dict):
        template = "kv"  # columns only applies to kv; auto-upgrade silently
    if columns > 1 and template not in ("kv",):
        import sys
        print(f"warning: --columns {columns} has no effect on template '{template}'", file=sys.stderr)

    if is_raw_grid(payload, profile):
        return from_characters(payload, profile)
    if template == "text":
        return render_text(profile, str(payload), valign=valign)
    if template == "kv":
        if not isinstance(payload, dict):
            raise SystemExit("template=kv requires a JSON object")
        return render_kv(profile, payload, title=title, title_color=title_color, subtitle=resolved_subtitle, columns=columns, separator=separator)
    if template in ("data", "table", "metrics"):  # table/metrics kept as aliases
        if not isinstance(payload, (dict, list)):
            raise SystemExit("template=data requires a JSON object or array of objects")
        return render_data(profile, payload, title=title, title_color=title_color, subtitle=resolved_subtitle, valign=valign, align=align, separator=separator)
    if template == "auto":
        return render_auto(profile, payload, title=title, title_color=title_color, subtitle=resolved_subtitle, align=align, valign=valign, separator=separator)
    raise SystemExit(f"unknown template: {template}")


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vestaboard formatter / preview / publisher")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--profile", choices=sorted(PROFILES), default="flagship")
        p.add_argument("--template", choices=["auto", "text", "kv", "data", "table", "metrics"], default="auto")
        p.add_argument("--visible-spaces", action="store_true", help="Show spaces as · in terminal preview")
        p.add_argument("--cell-width", type=int, default=2, help="Terminal preview width per board cell")
        p.add_argument("--no-ansi", action="store_true", help="Disable ANSI color in terminal preview")
        p.add_argument("--title")
        p.add_argument("--title-color", default="white", metavar="COLOR", help="Color(s) of title bookend tiles (default: white). Single name or up to 3 comma-separated colors (e.g. red,blue,orange — right side mirrors left). Use 'none' for plain centered title with no tiles.")
        p.add_argument("--subtitle", metavar="TEXT|time", help="Optional subtitle row below title. Use 'time' for current time")
        p.add_argument("--columns", type=int, choices=[1, 2], default=1, help="Number of key-value pairs per row (kv template only, default: 1)")
        p.add_argument("--input", default="-", help="Path to input file, or - for stdin")
        p.add_argument("--no-preview", action="store_true")
        p.add_argument("--valign", choices=["top", "center"], default="top", help="Vertical alignment of content block")
        p.add_argument("--align", choices=["left", "center", "right"], default=None, help="Horizontal alignment (default: center for tables, left for metrics)")
        p.add_argument("--timestamp", action="store_true", help="Add current time to bottom-right if space allows")
        p.add_argument("--force-timestamp", action="store_true", help="Add current time to bottom-right, overwriting if needed")
        p.add_argument("--tz", default=None, help="Timezone for timestamp, e.g. America/New_York (default: local)")
        p.add_argument("--separator", nargs="?", const="white", default=None, metavar="PATTERN", help="Add a separator row below the title block. PATTERN: color name, 'rainbow', or comma-separated colors (default: white)")

    render_p = sub.add_parser("render", help="Render and preview without posting")
    add_common(render_p)
    render_p.add_argument("--preview-only", action="store_true", help="Print only the terminal preview")
    render_p.add_argument("--json-only", action="store_true", help="Print only the raw character array JSON")
    render_p.add_argument("--explain", action="store_true", help="Show color indicator breakdown after preview")

    cloud_p = sub.add_parser("post-cloud", help="Render and send via Cloud API")
    add_common(cloud_p)
    cloud_p.add_argument("--token", default=os.getenv("VESTABOARD_TOKEN"))

    local_p = sub.add_parser("post-local", help="Render and send via Local API")
    add_common(local_p)
    local_p.add_argument("--api-key", default=os.getenv("VESTABOARD_LOCAL_API_KEY"))
    local_p.add_argument("--host", default=os.getenv("VESTABOARD_LOCAL_HOST", "http://vestaboard.local:7000"))
    local_p.add_argument("--strategy")
    local_p.add_argument("--step-interval-ms", type=int)
    local_p.add_argument("--step-size", type=int)

    read_cloud_p = sub.add_parser("read-cloud", help="Preview current board state from Cloud RW API")
    read_cloud_p.add_argument("--token", default=os.getenv("VESTABOARD_TOKEN"))
    read_cloud_p.add_argument("--profile", choices=sorted(PROFILES), default=None, help="Override profile (auto-detected from grid dimensions if omitted)")
    read_cloud_p.add_argument("--visible-spaces", action="store_true")
    read_cloud_p.add_argument("--cell-width", type=int, default=2)
    read_cloud_p.add_argument("--no-ansi", action="store_true")
    read_cloud_p.add_argument("--json-only", action="store_true", help="Print only the raw character array JSON")

    args = parser.parse_args(argv)

    if args.command == "read-cloud":
        if not args.token:
            raise SystemExit("missing --token or VESTABOARD_TOKEN")
        profile = PROFILES[args.profile] if args.profile else None
        message = read_cloud(args.token, profile)
        if args.json_only:
            print(json.dumps(message.to_characters()))
            return 0
        print(message.preview(
            visible_spaces=args.visible_spaces,
            cell_width=args.cell_width,
            ansi_color=not args.no_ansi,
        ))
        return 0

    profile = PROFILES[args.profile]
    payload = load_payload(args.input)
    if not args.title or args.title_color.lower() == "none":
        title_color: Color | list[Color] | None = None
    else:
        _tc_parts = [p.strip() for p in args.title_color.split(",")]
        if len(_tc_parts) == 1:
            title_color = tone_to_color(_tc_parts[0])
        else:
            title_color = [tone_to_color(p) or Color.WHITE for p in _tc_parts[:3]]
    message = build_message(profile, args.template, payload, args.title, valign=args.valign, align=args.align, title_color=title_color, subtitle=getattr(args, "subtitle", None), tz=args.tz, columns=args.columns, separator=getattr(args, "separator", None))

    if getattr(args, "force_timestamp", False) or getattr(args, "timestamp", False):
        message = place_timestamp(message, tz=args.tz, force=getattr(args, "force_timestamp", False))

    show_preview = not args.no_preview
    if args.command == "render" and args.json_only:
        show_preview = False

    if show_preview:
        print(message.preview(
            visible_spaces=args.visible_spaces,
            cell_width=args.cell_width,
            ansi_color=not args.no_ansi,
        ))
        print()

    if args.command == "render":
        if args.preview_only and args.json_only:
            raise SystemExit("choose only one of --preview-only or --json-only")
        if getattr(args, "explain", False) and isinstance(payload, dict):
            explanation = explain_metrics(payload, profile, ansi_color=not args.no_ansi)
            if explanation:
                print(explanation)
                print()
        if args.preview_only:
            return 0
        print(json.dumps(message.to_characters()))
        return 0

    if args.command == "post-cloud":
        if not args.token:
            raise SystemExit("missing --token or VESTABOARD_TOKEN")
        result = post_cloud(args.token, message)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "post-local":
        if not args.api_key:
            raise SystemExit("missing --api-key or VESTABOARD_LOCAL_API_KEY")
        result = post_local(
            api_key=args.api_key,
            host=args.host,
            message=message,
            strategy=args.strategy,
            step_interval_ms=args.step_interval_ms,
            step_size=args.step_size,
        )
        print(json.dumps(result, indent=2))
        return 0

    return 1


def main() -> None:
    raise SystemExit(cli())


if __name__ == "__main__":
    main()
