from __future__ import annotations

import argparse
import csv
import io
import json
import os
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


# -----------------------------------------------------------------------------
# Encoding
# -----------------------------------------------------------------------------


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


def prettify_label(key: str) -> str:
    return normalize_text(key).replace("_", " ")


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
        "%m/%d %H:%M",
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
        if kind == "currency_short":
            return compact_number(n)
        if kind == "percent":
            formatted = f"{n:.2f}".rstrip("0").rstrip(".")
            return f"{formatted}%"
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
        natural[col] = max([header, *vals, 3])

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
# Auto-detection uses key name heuristics (pct/percent/yoy/change/delta/diff →
# positive/negative). Callers can override per-field via _style in their input.
# -----------------------------------------------------------------------------


def resolve_tone(data: dict[str, Any], key: str, value: Any) -> str | None:
    """Resolve a semantic tone for a field. Returns a tone name or None."""
    style = data.get("_style")
    if isinstance(style, dict) and key in style:
        override = style[key]
        if isinstance(override, str):
            return override.lower()
        if isinstance(override, dict):
            tone = override.get("tone")
            if isinstance(tone, str):
                return tone.lower()

    # Auto-detect tone for numeric fields whose key name implies a change/delta.
    if isinstance(value, (int, float)):
        lower_key = key.lower()
        if any(p in lower_key for p in ("pct", "percent", "yoy", "change", "delta", "diff")):
            n = float(value)
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


def render_text(profile: BoardProfile, text: str, align: str = "center") -> RenderedMessage:
    grid = blank_grid(profile)
    lines = wrap_text(text, profile.cols, profile.rows)
    top = max(0, (profile.rows - len(lines)) // 2)
    for i, line in enumerate(lines):
        place_line(grid, top + i, line.rstrip(), align=align)
    return RenderedMessage(profile=profile, grid=grid)


def render_kv(profile: BoardProfile, data: dict[str, Any], title: str | None = None) -> RenderedMessage:
    grid = blank_grid(profile)
    row = 0
    if title:
        place_line(grid, row, title, align="center")
        row += 1

    # Skip internal hint keys (e.g. _style, _template).
    items = [(k, v) for k, v in data.items() if not k.startswith("_")]
    items = items[: max(0, profile.rows - row)]

    for key, value in items:
        if row >= profile.rows:
            break
        key_s = normalize_text(str(key)).replace("_", " ")
        value_s = normalize_text(format_scalar(value))
        if profile.cols >= 18:
            left_width = min(max(len(key_s), 6), profile.cols // 2)
            right_width = profile.cols - left_width - 1
            left = ellipsize(key_s, left_width).ljust(left_width)
            right = ellipsize(value_s, right_width).rjust(right_width)
            place_line(grid, row, f"{left} {right}", align="left")
        else:
            place_line(grid, row, ellipsize(key_s, profile.cols - 1), align="left")
            row += 1
            if row >= profile.rows:
                break
            place_line(grid, row, ellipsize(value_s, profile.cols), align="right")
        row += 1

    return RenderedMessage(profile=profile, grid=grid)


def render_table(profile: BoardProfile, rows: list[dict[str, Any]], title: str | None = None) -> RenderedMessage:
    grid = blank_grid(profile)
    row_idx = 0

    if title:
        place_line(grid, row_idx, title, align="center")
        row_idx += 1

    if not rows:
        if row_idx < profile.rows:
            place_line(grid, row_idx, "NO DATA", align="center")
        return RenderedMessage(profile=profile, grid=grid)

    columns = list(rows[0].keys())[:3]
    visible_rows = rows[: max(0, profile.rows - row_idx)]

    widths = infer_widths(columns, visible_rows, profile.cols)
    header = " ".join(ellipsize(col.replace("_", " ").upper(), widths[col]).ljust(widths[col]) for col in columns)
    if row_idx < profile.rows:
        place_line(grid, row_idx, header, align="left")
        row_idx += 1

    for record in visible_rows[: max(0, profile.rows - row_idx)]:
        cells = []
        for col in columns:
            raw = format_scalar(record.get(col, ""))
            is_num = isinstance(record.get(col), (int, float))
            cell = ellipsize(normalize_text(raw), widths[col])
            cells.append(cell.rjust(widths[col]) if is_num else cell.ljust(widths[col]))
        line = " ".join(cells)
        if row_idx < profile.rows:
            place_line(grid, row_idx, line, align="left")
            row_idx += 1

    return RenderedMessage(profile=profile, grid=grid)


# NOTE: Experimental. render_metrics is a generic key-value renderer that adds
# a trailing color tile indicator based on semantic tone. Useful for dashboards
# where some fields (e.g. percent changes) have a natural positive/negative meaning.
# Use _style overrides in the input dict to assign tones explicitly per field.
def render_metrics(profile: BoardProfile, data: dict[str, Any], title: str | None = None) -> RenderedMessage:
    entries = []
    for key, value in data.items():
        if key.startswith("_"):
            continue
        entries.append(
            {
                "key": key,
                "label": prettify_label(key),
                "value": format_metric_value(value, "auto", profile),
                "tone": resolve_tone(data, key, value),
            }
        )

    grid = blank_grid(profile)
    row = 0
    if title:
        place_line(grid, row, title, align="center")
        row += 1

    for entry in entries[: max(0, profile.rows - row)]:
        color = tone_to_color(entry["tone"])

        # Reserve the last two columns for a trailing color indicator tile.
        # NOTE: Experimental — indicator placement may change.
        reserve_cols = 2 if color and profile.cols >= 12 else 0
        available_width = profile.cols - reserve_cols
        left_width = max(4, min(len(entry["label"]), max(4, available_width // 2)))
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


def render_auto(profile: BoardProfile, payload: Any, title: str | None = None) -> RenderedMessage:
    """Infer the best renderer from the payload type and content."""
    if isinstance(payload, str):
        return render_text(profile, payload)
    if isinstance(payload, dict):
        # Route to metrics if the caller has provided _style overrides,
        # which signals they want tone-aware rendering. Otherwise use kv.
        if "_style" in payload:
            return render_metrics(profile, payload, title=title)
        return render_kv(profile, payload, title=title)
    if isinstance(payload, list) and payload and all(isinstance(x, dict) for x in payload):
        return render_table(profile, payload, title=title)
    return render_text(profile, json.dumps(payload, separators=(",", ":")), align="left")


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
            return rows
    except Exception:
        pass

    return raw


# -----------------------------------------------------------------------------
# Publishers
# -----------------------------------------------------------------------------


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
# CLI
# -----------------------------------------------------------------------------


def build_message(profile: BoardProfile, template: str, payload: Any, title: str | None) -> RenderedMessage:
    if template == "text":
        return render_text(profile, str(payload))
    if template == "kv":
        if not isinstance(payload, dict):
            raise SystemExit("template=kv requires a JSON object")
        return render_kv(profile, payload, title=title)
    if template == "table":
        if not (isinstance(payload, list) and all(isinstance(x, dict) for x in payload)):
            raise SystemExit("template=table requires CSV or a JSON array of objects")
        return render_table(profile, payload, title=title)
    if template == "metrics":
        if not isinstance(payload, dict):
            raise SystemExit("template=metrics requires a JSON object")
        return render_metrics(profile, payload, title=title)
    if template == "auto":
        return render_auto(profile, payload, title=title)
    raise SystemExit(f"unknown template: {template}")


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vestaboard formatter / preview / publisher")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--profile", choices=sorted(PROFILES), default="flagship")
        p.add_argument("--template", choices=["auto", "text", "kv", "table", "metrics"], default="auto")
        p.add_argument("--visible-spaces", action="store_true", help="Show spaces as · in terminal preview")
        p.add_argument("--cell-width", type=int, default=2, help="Terminal preview width per board cell")
        p.add_argument("--no-ansi", action="store_true", help="Disable ANSI color in terminal preview")
        p.add_argument("--title")
        p.add_argument("--input", default="-", help="Path to input file, or - for stdin")
        p.add_argument("--no-preview", action="store_true")

    render_p = sub.add_parser("render", help="Render and preview without posting")
    add_common(render_p)
    render_p.add_argument("--preview-only", action="store_true", help="Print only the terminal preview")
    render_p.add_argument("--json-only", action="store_true", help="Print only the raw character array JSON")

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

    args = parser.parse_args(argv)
    profile = PROFILES[args.profile]
    payload = load_payload(args.input)
    message = build_message(profile, args.template, payload, args.title)

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


if __name__ == "__main__":
    raise SystemExit(cli())
