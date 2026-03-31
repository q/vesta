from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Iterable

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
        "❤": 62,
    }
)

# Optional symbolic color tokens for templating / debugging.
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

CODE_TO_PREVIEW = {v: k for k, v in CHAR_TO_CODE.items()}
CODE_TO_PREVIEW.update(
    {
        63: "●",
        64: "●",
        65: "●",
        66: "●",
        67: "●",
        68: "●",
        69: "○",
        70: "●",
        71: "■",
    }
)


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

    def preview(self) -> str:
        inner = ["│" + "".join(cell if len(cell) == 1 else "?" for cell in row) + "│" for row in self.grid]
        top = "┌" + "─" * self.profile.cols + "┐"
        bottom = "└" + "─" * self.profile.cols + "┘"
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
    return text[: max(0, width - 1)] + "…"


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


def place_line(grid: list[list[str]], row_idx: int, text: str, align: str = "left") -> None:
    width = len(grid[row_idx])
    text = ellipsize(text, width)
    if align == "center":
        start = max(0, (width - len(text)) // 2)
    elif align == "right":
        start = max(0, width - len(text))
    else:
        start = 0
    for i, ch in enumerate(text[:width]):
        grid[row_idx][start + i] = ch


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


def render_auto(profile: BoardProfile, payload: Any, title: str | None = None) -> RenderedMessage:
    if isinstance(payload, str):
        return render_text(profile, payload)
    if isinstance(payload, dict):
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
    if template == "auto":
        return render_auto(profile, payload, title=title)
    raise SystemExit(f"unknown template: {template}")



def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vestaboard MVP formatter / preview / publisher")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--profile", choices=sorted(PROFILES), default="flagship")
        p.add_argument("--template", choices=["auto", "text", "kv", "table"], default="auto")
        p.add_argument("--title")
        p.add_argument("--input", default="-", help="Path to input file, or - for stdin")
        p.add_argument("--no-preview", action="store_true")

    render_p = sub.add_parser("render", help="Render and preview without posting")
    add_common(render_p)

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

    if not args.no_preview:
        print(message.preview())
        print()

    if args.command == "render":
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

