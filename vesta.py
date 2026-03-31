from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
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
# Character encoding
# Minimal-but-useful encoder for common Vestaboard characters.
# Unsupported characters are replaced with spaces.
# -----------------------------------------------------------------------------


CHAR_TO_CODE: dict[str, int] = {" ": 0}
for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ", start=1):
    CHAR_TO_CODE[ch] = i
for i, ch in enumerate("1234567890", start=27):
    CHAR_TO_CODE[ch] = i

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
        "°": 62,
        "❤": 62
    }
)

# NOTE: Experimental token cells. We are trying this as an internal rendering detail,
# not as a public mini-language we expect callers to author directly.
TOKEN_TO_CODE = {
    "<RED>": 63,
    "<ORANGE>": 64,
    "<YELLOW>": 65,
    "<GREEN>": 66,
    "<BLUE>": 67,
    "<VIOLET>": 68,
    "<WHITE>": 69,
    "<BLACK>": 70,
    "<FILLED>": 71,
}

# NOTE: Experimental ANSI preview colors. This is only for terminal preview and may
# not stick around in this exact form.
TOKEN_TO_ANSI = {
    "<RED>": "\033[31m",
    "<ORANGE>": "\033[38;5;208m",
    "<YELLOW>": "\033[33m",
    "<GREEN>": "\033[32m",
    "<BLUE>": "\033[34m",
    "<VIOLET>": "\033[35m",
    "<WHITE>": "\033[37m",
    "<BLACK>": "\033[90m",
    "<FILLED>": "\033[97m",
}
ANSI_RESET = "\033[0m"

TONE_TO_TOKEN = {
    "good": "<GREEN>",
    "bad": "<RED>",
    "warn": "<YELLOW>",
    "info": "<BLUE>",
    "neutral": "<WHITE>",
    "muted": "<BLACK>",
    "green": "<GREEN>",
    "red": "<RED>",
    "yellow": "<YELLOW>",
    "blue": "<BLUE>",
    "white": "<WHITE>",
    "black": "<BLACK>",
    "violet": "<VIOLET>",
    "orange": "<ORANGE>",
}


# -----------------------------------------------------------------------------
# Core model
# -----------------------------------------------------------------------------


@dataclass
class RenderedMessage:
    profile: BoardProfile
    grid: list[list[str]]

    def to_lines(self) -> list[str]:
        return ["".join(row) for row in self.grid]

    def to_characters(self) -> list[list[int]]:
        return [[encode_cell(cell, self.profile) for cell in row] for row in self.grid]

    def preview(self, visible_spaces: bool = True, cell_width: int = 2, ansi_color: bool = True) -> str:
        cell_width = max(1, cell_width)

        def show(cell: str) -> str:
            if cell in TOKEN_TO_CODE:
                block = "█" * cell_width
                if ansi_color and cell in TOKEN_TO_ANSI:
                    return f"{TOKEN_TO_ANSI[cell]}{block}{ANSI_RESET}"
                return block
            if len(cell) != 1:
                ch = "?"
            elif cell == " ":
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
            top = top[:start] + label + top[start + len(label):]
        return "\n".join([top, *inner, bottom])


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def blank_grid(profile: BoardProfile, fill: str = " ") -> list[list[str]]:
    return [[fill for _ in range(profile.cols)] for _ in range(profile.rows)]


def normalize_text(text: str) -> str:
    return text.upper().replace("\t", " ")


def ellipsize(text: str, width: int) -> str:
    text = normalize_text(text)
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: max(0, width - 1)] + "."


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


def place_line(grid: list[list[str]], row_idx: int, text: str, align: str = "left", start_col: int = 0) -> None:
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


def place_cell(grid: list[list[str]], row_idx: int, col_idx: int, value: str) -> None:
    if 0 <= row_idx < len(grid) and 0 <= col_idx < len(grid[row_idx]):
        grid[row_idx][col_idx] = value


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

    available_rows = profile.rows - row
    items = list(data.items())[:available_rows]

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
            line = f"{ellipsize(key_s, profile.cols - 1)}"
            place_line(grid, row, line, align="left")
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


# NOTE: Experimental style metadata and row indicators. We are trying a semantic
# approach to color support here, but it is still very possible we simplify or
# remove this later.
def render_metrics(profile: BoardProfile, data: dict[str, Any], title: str | None = None) -> RenderedMessage:
    aliases = [
        (("rpm", "revenue_per_min", "revenue_per_minute"), "RPM", "number"),
        (("revenue_24h", "rev_24h", "revenue24h"), "REV 24H", "currency_short"),
        (("week_yoy_pct", "week_yoy", "week_change_pct"), "WEEK YOY", "percent"),
        (("month_yoy_pct", "month_yoy", "month_change_pct"), "MONTH YOY", "percent"),
        (("updated", "upd", "timestamp", "ts"), "UPD", "datetime"),
    ]

    ordered: list[dict[str, Any]] = []
    used_keys: set[str] = set()

    for keys, label, kind in aliases:
        for key in keys:
            if key in data:
                value = data[key]
                ordered.append(
                    {
                        "key": key,
                        "label": label,
                        "value": format_metric_value(value, kind, profile),
                        "tone": resolve_metric_tone(data, key, value),
                    }
                )
                used_keys.add(key)
                break

    for key, value in data.items():
        if key in used_keys or key.startswith("_"):
            continue
        ordered.append(
            {
                "key": key,
                "label": prettify_metric_label(key),
                "value": format_metric_value(value, "auto", profile),
                "tone": resolve_metric_tone(data, key, value),
            }
        )

    grid = blank_grid(profile)
    row = 0
    if title:
        place_line(grid, row, title, align="center")
        row += 1

    for entry in ordered[: max(0, profile.rows - row)]:
        token = tone_to_token(entry["tone"])

        # NOTE: Experimental indicator placement. We are trying the color cell as a
        # trailing badge beside the value instead of a leading marker on the left.
        reserve_cols = 2 if token and profile.cols >= 12 else 0
        available_width = profile.cols - reserve_cols
        left_width = max(4, min(len(entry["label"]), max(4, available_width // 2)))
        right_width = max(1, available_width - left_width - 1)
        left = ellipsize(entry["label"], left_width).ljust(left_width)
        right = ellipsize(entry["value"], right_width).rjust(right_width)
        place_line(grid, row, f"{left} {right}", align="left")

        if token and profile.cols >= 12:
            place_cell(grid, row, profile.cols - 1, token)
        row += 1
        if row >= profile.rows:
            break

    return RenderedMessage(profile=profile, grid=grid)


def render_auto(profile: BoardProfile, payload: Any, title: str | None = None) -> RenderedMessage:
    if isinstance(payload, str):
        return render_text(profile, payload)
    if isinstance(payload, dict):
        metric_keys = {
            "rpm",
            "revenue_per_min",
            "revenue_per_minute",
            "revenue_24h",
            "rev_24h",
            "week_yoy_pct",
            "week_yoy",
            "month_yoy_pct",
            "month_yoy",
            "updated",
            "upd",
            "timestamp",
            "ts",
        }
        if any(key in payload for key in metric_keys):
            return render_metrics(profile, payload, title=title)
        return render_kv(profile, payload, title=title)
    if isinstance(payload, list) and payload and all(isinstance(x, dict) for x in payload):
        return render_table(profile, payload, title=title)
    return render_text(profile, json.dumps(payload, separators=(",", ":")), align="left")


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


def prettify_metric_label(key: str) -> str:
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
        return ellipsize(normalize_text(str(value)), 10 if profile.cols <= 15 else 12)

    month = dt.month
    day = dt.day
    hour_24 = dt.hour
    minute = dt.minute
    suffix = "A" if hour_24 < 12 else "P"
    hour_12 = hour_24 % 12 or 12

    if profile.cols <= 15:
        return f"{hour_12}:{minute:02d}{suffix}"
    return f"{month}/{day} {hour_12}:{minute:02d}{suffix}"


def format_metric_value(value: Any, kind: str, profile: BoardProfile) -> str:
    if kind == "datetime":
        return compact_datetime(value, profile)

    if isinstance(value, (int, float)):
        n = float(value)
        if kind == "currency_short":
            return compact_number(n)
        if kind == "percent":
            return f"{n:.2f}".rstrip("0").rstrip(".")
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


# NOTE: Experimental tone resolution. We may decide later this is too much logic
# for the renderer, but it is useful for quickly testing semantic color support.
def resolve_metric_tone(data: dict[str, Any], key: str, value: Any) -> str | None:
    style = data.get("_style")
    if isinstance(style, dict) and key in style:
        override = style[key]
        if isinstance(override, str):
            return override.lower()
        if isinstance(override, dict):
            tone = override.get("tone")
            if isinstance(tone, str):
                return tone.lower()

    if isinstance(value, (int, float)):
        lower_key = key.lower()
        if any(part in lower_key for part in ["pct", "percent", "yoy", "change"]):
            n = float(value)
            if n > 0:
                return "good"
            if n < 0:
                return "bad"
            return "neutral"

    return None


def tone_to_token(tone: str | None) -> str | None:
    if not tone:
        return None
    return TONE_TO_TOKEN.get(tone.lower())


# -----------------------------------------------------------------------------
# Encoding
# -----------------------------------------------------------------------------


def encode_cell(cell: str, profile: BoardProfile) -> int:
    if cell in TOKEN_TO_CODE:
        return TOKEN_TO_CODE[cell]

    ch = normalize_text(cell[:1] if cell else " ")
    if ch == "❤" and profile.name != "note":
        ch = "°"
    if ch == "°" and profile.name == "note":
        ch = "❤"
    return CHAR_TO_CODE.get(ch, 0)


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
        payload = {
            "characters": message.to_characters(),
        }
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
    parser = argparse.ArgumentParser(description="Vestaboard MVP formatter / preview / publisher")
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
        print(message.preview(visible_spaces=args.visible_spaces, cell_width=args.cell_width, ansi_color=not args.no_ansi))
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

