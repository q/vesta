from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

try:
    import yaml
except ImportError:
    yaml = None


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
        "…": 0,
    }
)

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

    def preview(self, visible_spaces: bool = True, cell_width: int = 2) -> str:
        cell_width = max(1, cell_width)

        def show(cell: str) -> str:
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
    if width == 2:
        return text[:2]
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
            place_line(grid, row, ellipsize(key_s, profile.cols), align="left")
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
    visible_rows = rows[: max(0, profile.rows - row_idx - 1)]

    widths = infer_widths(columns, visible_rows, profile.cols)
    header = " ".join(
        ellipsize(col.replace("_", " ").upper(), widths[col]).ljust(widths[col])
        for col in columns
    )
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



def render_metrics(profile: BoardProfile, data: dict[str, Any], title: str | None = None) -> RenderedMessage:
    aliases = [
        (("rpm", "revenue_per_min", "revenue_per_minute"), "RPM", "number"),
        (("revenue_24h", "rev_24h", "revenue24h"), "REV 24H", "currency_short"),
        (("week_yoy_pct", "week_yoy", "week_change_pct"), "WEEK YOY", "percent"),
        (("month_yoy_pct", "month_yoy", "month_change_pct"), "MONTH YOY", "percent"),
        (("updated", "upd", "timestamp", "ts"), "UPD", "datetime"),
    ]

    ordered: list[tuple[str, str]] = []
    used_keys: set[str] = set()

    for keys, label, kind in aliases:
        for key in keys:
            if key in data:
                ordered.append((label, format_metric_value(data[key], kind, profile)))
                used_keys.add(key)
                break

    for key, value in data.items():
        if key in used_keys:
            continue
        ordered.append((prettify_metric_label(key), format_metric_value(value, "auto", profile)))

    grid = blank_grid(profile)
    row = 0
    if title:
        place_line(grid, row, title, align="center")
        row += 1

    for label, value in ordered[: max(0, profile.rows - row)]:
        left_width = max(4, min(len(label), profile.cols // 2))
        right_width = profile.cols - left_width - 1
        left = ellipsize(label, left_width).ljust(left_width)
        right = ellipsize(value, right_width).rjust(right_width)
        place_line(grid, row, f"{left} {right}", align="left")
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
            return f"{value / 1_000_000:.2f}".rstrip("0").rstrip(".") + "M"
        if abs(value) >= 1_000:
            return f"{value / 1_000:.1f}".rstrip("0").rstrip(".") + "K"
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
            return compact_number(n, decimals=2 if abs(n) < 100 else 1)
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
# Publishers and target config
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



def load_devices_config(path: str) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise SystemExit(f"devices file not found: {path}")
    if yaml is None:
        raise SystemExit("PyYAML is required for devices.yaml support. Install with: pip install pyyaml")

    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    devices = data.get("devices")
    if not isinstance(devices, dict):
        raise SystemExit("devices.yaml must contain a top-level 'devices:' mapping")
    return devices



def resolve_target(target: str, devices_file: str) -> dict[str, Any]:
    devices = load_devices_config(devices_file)
    if target not in devices:
        available = ", ".join(sorted(devices)) or "none"
        raise SystemExit(f"unknown target '{target}'. Available targets: {available}")
    config = devices[target]
    if not isinstance(config, dict):
        raise SystemExit(f"target '{target}' must map to an object")
    return config



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
    if strategy or step_interval_ms is not None or step_size is not None:
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
        p.add_argument("--profile", choices=sorted(PROFILES), default=None)
        p.add_argument("--template", choices=["auto", "text", "kv", "table", "metrics"], default="auto")
        p.add_argument("--visible-spaces", action="store_true", help="Show spaces as · in terminal preview")
        p.add_argument("--cell-width", type=int, default=2, help="Terminal preview width per board cell")
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

    post_p = sub.add_parser("post", help="Render and send via a named target from devices.yaml")
    add_common(post_p)
    post_p.add_argument("--target", required=True)
    post_p.add_argument("--devices-file", default=os.getenv("VESTA_DEVICES_FILE", "devices.yaml"))

    args = parser.parse_args(argv)

    target_config: dict[str, Any] | None = None
    if args.command == "post":
        target_config = resolve_target(args.target, args.devices_file)
        profile_name = args.profile or target_config.get("profile") or "flagship"
    else:
        profile_name = args.profile or "flagship"

    profile = PROFILES[profile_name]
    payload = load_payload(args.input)
    message = build_message(profile, args.template, payload, args.title)

    show_preview = not args.no_preview
    if args.command == "render" and getattr(args, "json_only", False):
        show_preview = False

    if show_preview:
        print(message.preview(visible_spaces=args.visible_spaces, cell_width=args.cell_width))
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

    if args.command == "post":
        assert target_config is not None
        kind = str(target_config.get("kind", "")).lower()

        if kind == "cloud":
            token = target_config.get("token")
            token_env = target_config.get("token_env")
            if not token and token_env:
                token = os.getenv(str(token_env))
            if not token:
                raise SystemExit(f"target '{args.target}' is missing token or token_env")
            result = post_cloud(str(token), message)
            print(json.dumps(result, indent=2))
            return 0

        if kind == "local":
            api_key = target_config.get("api_key")
            api_key_env = target_config.get("api_key_env")
            if not api_key and api_key_env:
                api_key = os.getenv(str(api_key_env))
            if not api_key:
                raise SystemExit(f"target '{args.target}' is missing api_key or api_key_env")

            host = str(target_config.get("host") or os.getenv("VESTABOARD_LOCAL_HOST", "http://vestaboard.local:7000"))
            result = post_local(
                api_key=str(api_key),
                host=host,
                message=message,
                strategy=target_config.get("strategy"),
                step_interval_ms=target_config.get("step_interval_ms"),
                step_size=target_config.get("step_size"),
            )
            print(json.dumps(result, indent=2))
            return 0

        raise SystemExit(f"target '{args.target}' has unsupported kind '{kind}'. Use 'cloud' or 'local'.")

    return 1


if __name__ == "__main__":
    raise SystemExit(cli())

