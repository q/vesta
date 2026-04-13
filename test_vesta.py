"""Tests for vesta.py — run with: uv run pytest test_vesta.py -v"""
import unittest

import io
import textwrap

from vesta import (
    FLAGSHIP,
    NOTE,
    Color,
    blank_grid,
    cli,
    compact_datetime,
    ellipsize,
    encode_cell,
    explain_metrics,
    format_metric_value,
    load_payload,
    place_timestamp,
    prettify_label,
    render_kv,
    smart_round,
    format_field,
    render_data,
    render_metrics,
    render_table,
    render_text,
    resolve_tone,
    tone_from_range,
    tone_to_color,
    wrap_text,
)


class TestProfiles(unittest.TestCase):
    def test_flagship_dimensions(self):
        self.assertEqual(FLAGSHIP.rows, 6)
        self.assertEqual(FLAGSHIP.cols, 22)

    def test_note_dimensions(self):
        self.assertEqual(NOTE.rows, 3)
        self.assertEqual(NOTE.cols, 15)

    def test_blank_grid_flagship(self):
        grid = blank_grid(FLAGSHIP)
        self.assertEqual(len(grid), 6)
        self.assertEqual(len(grid[0]), 22)

    def test_blank_grid_note(self):
        grid = blank_grid(NOTE)
        self.assertEqual(len(grid), 3)
        self.assertEqual(len(grid[0]), 15)


class TestEncoding(unittest.TestCase):
    def test_space_is_zero(self):
        self.assertEqual(encode_cell(" ", FLAGSHIP), 0)

    def test_letter_a(self):
        self.assertEqual(encode_cell("A", FLAGSHIP), 1)

    def test_lowercase_normalized(self):
        self.assertEqual(encode_cell("a", FLAGSHIP), 1)

    def test_letter_z(self):
        self.assertEqual(encode_cell("Z", FLAGSHIP), 26)

    def test_digit_1(self):
        self.assertEqual(encode_cell("1", FLAGSHIP), 27)

    def test_digit_0(self):
        self.assertEqual(encode_cell("0", FLAGSHIP), 36)

    def test_unsupported_char_is_zero(self):
        self.assertEqual(encode_cell("~", FLAGSHIP), 0)
        self.assertEqual(encode_cell("\n", FLAGSHIP), 0)

    def test_color_encodes_directly(self):
        self.assertEqual(encode_cell(Color.RED, FLAGSHIP), 63)
        self.assertEqual(encode_cell(Color.GREEN, FLAGSHIP), 66)
        self.assertEqual(encode_cell(Color.FILLED, FLAGSHIP), 71)

    def test_all_colors_in_range(self):
        for color in Color:
            code = encode_cell(color, FLAGSHIP)
            self.assertGreaterEqual(code, 63)
            self.assertLessEqual(code, 71)

    def test_degree_on_flagship(self):
        self.assertEqual(encode_cell("°", FLAGSHIP), 62)

    def test_heart_on_note(self):
        self.assertEqual(encode_cell("❤", NOTE), 62)

    def test_degree_on_note_maps_to_heart_code(self):
        # Hardware quirk: ° on Note resolves to ❤ (both are code 62)
        self.assertEqual(encode_cell("°", NOTE), 62)

    def test_heart_on_flagship_maps_to_degree_code(self):
        # Hardware quirk: ❤ on Flagship resolves to ° (both are code 62)
        self.assertEqual(encode_cell("❤", FLAGSHIP), 62)


class TestTruncation(unittest.TestCase):
    def test_no_truncation_when_fits(self):
        self.assertEqual(ellipsize("HELLO", 10), "HELLO")

    def test_exact_fit(self):
        self.assertEqual(ellipsize("HELLO", 5), "HELLO")

    def test_truncates_to_exact_width(self):
        result = ellipsize("HELLO WORLD", 6)
        self.assertEqual(result, "HELLO ")

    def test_normalizes_to_uppercase(self):
        self.assertEqual(ellipsize("hello", 10), "HELLO")

    def test_no_truncation_marker(self):
        result = ellipsize("HELLO WORLD", 8)
        self.assertEqual(result, "HELLO WO")

    def test_wrap_text_basic(self):
        lines = wrap_text("HELLO WORLD", 22, 6)
        self.assertIn("HELLO WORLD", lines[0])

    def test_wrap_text_respects_max_lines(self):
        lines = wrap_text("ONE TWO THREE FOUR FIVE SIX SEVEN", 5, 2)
        self.assertLessEqual(len(lines), 2)

    def test_wrap_text_pads_to_width(self):
        lines = wrap_text("HI", 10, 3)
        for line in lines:
            self.assertEqual(len(line), 10)

    def test_wrap_text_empty(self):
        lines = wrap_text("", 22, 6)
        self.assertEqual(lines, [""])


class TestDatetimeCompaction(unittest.TestCase):
    def test_iso_flagship(self):
        result = compact_datetime("2024-03-15T14:30:00", FLAGSHIP)
        self.assertEqual(result, "3/15 2:30P")

    def test_iso_note(self):
        result = compact_datetime("2024-03-15T14:30:00", NOTE)
        self.assertEqual(result, "2:30P")

    def test_midnight_is_am(self):
        result = compact_datetime("2024-01-01T00:00:00", NOTE)
        self.assertIn("A", result)

    def test_noon_is_pm(self):
        result = compact_datetime("2024-01-01T12:00:00", NOTE)
        self.assertIn("P", result)

    def test_noon_hour_is_12(self):
        result = compact_datetime("2024-01-01T12:00:00", NOTE)
        self.assertTrue(result.startswith("12:"))

    def test_invalid_falls_back(self):
        result = compact_datetime("not a date", FLAGSHIP)
        # Falls back to normalized/truncated string — no crash
        self.assertIsInstance(result, str)
        self.assertLessEqual(len(result), 12)

    def test_format_metric_value_datetime(self):
        result = format_metric_value("2024-06-01T09:15:00", "datetime", FLAGSHIP)
        self.assertEqual(result, "6/1 9:15A")

    def test_format_metric_value_percent_has_symbol(self):
        result = format_metric_value(12.5, "percent", FLAGSHIP)
        self.assertIn("%", result)

    def test_format_metric_value_percent_strips_trailing_zeros(self):
        result = format_metric_value(10.0, "percent", FLAGSHIP)
        self.assertEqual(result, "10%")

    def test_format_metric_value_percent_negative(self):
        result = format_metric_value(-3.5, "percent", FLAGSHIP)
        self.assertIn("%", result)
        self.assertIn("-3.5", result)


class TestTone(unittest.TestCase):
    def test_positive_pct_is_good(self):
        data = {"price_pct": 5.2}
        self.assertEqual(resolve_tone(data, "price_pct", 5.2), "good")

    def test_negative_change_is_bad(self):
        data = {"price_change": -3.1}
        self.assertEqual(resolve_tone(data, "price_change", -3.1), "bad")

    def test_zero_change_is_neutral(self):
        data = {"delta": 0}
        self.assertEqual(resolve_tone(data, "delta", 0), "neutral")

    def test_growth_delta_positive(self):
        data = {"growth_delta": 8.0}
        self.assertEqual(resolve_tone(data, "growth_delta", 8.0), "good")

    def test_diff_negative(self):
        data = {"diff": -1}
        self.assertEqual(resolve_tone(data, "diff", -1), "bad")

    def test_plain_value_no_tone(self):
        data = {"revenue": 1000}
        self.assertIsNone(resolve_tone(data, "revenue", 1000))

    def test_style_override_string(self):
        data = {"revenue": 1000, "_style": {"revenue": "bad"}}
        self.assertEqual(resolve_tone(data, "revenue", 1000), "bad")

    def test_style_override_dict(self):
        data = {"revenue": 1000, "_style": {"revenue": {"tone": "warn"}}}
        self.assertEqual(resolve_tone(data, "revenue", 1000), "warn")

    def test_tone_to_color_good(self):
        self.assertEqual(tone_to_color("good"), Color.GREEN)

    def test_tone_to_color_bad(self):
        self.assertEqual(tone_to_color("bad"), Color.RED)

    def test_tone_to_color_warn(self):
        self.assertEqual(tone_to_color("warn"), Color.YELLOW)

    def test_tone_to_color_none(self):
        self.assertIsNone(tone_to_color(None))

    def test_tone_to_color_unknown(self):
        self.assertIsNone(tone_to_color("unknown"))

    def test_tone_to_color_case_insensitive(self):
        self.assertEqual(tone_to_color("GOOD"), Color.GREEN)

    # Range-based tone
    def test_range_at_good_end(self):
        self.assertEqual(tone_from_range(30, good=30, bad=80), "good")

    def test_range_at_bad_end(self):
        self.assertEqual(tone_from_range(80, good=30, bad=80), "bad")

    def test_range_better_than_good_clamps_green(self):
        self.assertEqual(tone_from_range(10, good=30, bad=80), "good")

    def test_range_worse_than_bad_clamps_red(self):
        self.assertEqual(tone_from_range(99, good=30, bad=80), "bad")

    def test_range_midpoint_is_yellow_or_orange(self):
        # Midpoint (t=0.5) is the boundary between yellow and orange
        result = tone_from_range(55, good=30, bad=80)
        self.assertIn(result, ("warn", "orange"))

    def test_range_lower_quarter_is_yellow(self):
        # t=0.375 → yellow
        self.assertEqual(tone_from_range(48.75, good=30, bad=80), "warn")

    def test_range_upper_quarter_is_orange(self):
        # t=0.625 → orange
        self.assertEqual(tone_from_range(61.25, good=30, bad=80), "orange")

    def test_range_inverted_direction(self):
        # Higher is better: good=8, bad=2 (conversion rate)
        self.assertEqual(tone_from_range(8, good=8, bad=2), "good")
        self.assertEqual(tone_from_range(2, good=8, bad=2), "bad")
        self.assertEqual(tone_from_range(10, good=8, bad=2), "good")  # clamp

    def test_range_via_style_override(self):
        data = {"bounce_rate": 68.4, "_style": {"bounce_rate": {"good": 30, "bad": 80}}}
        # t = (68.4 - 30) / (80 - 30) = 38.4 / 50 = 0.768 → bad (red)
        self.assertEqual(resolve_tone(data, "bounce_rate", 68.4), "bad")

    def test_range_good_value_via_style(self):
        data = {"bounce_rate": 25.0, "_style": {"bounce_rate": {"good": 30, "bad": 80}}}
        # t = (25 - 30) / 50 = -0.1 → clamped to 0 → good (green)
        self.assertEqual(resolve_tone(data, "bounce_rate", 25.0), "good")

    def test_range_equal_good_bad_is_neutral(self):
        self.assertEqual(tone_from_range(50, good=50, bad=50), "neutral")

    # Exact boundary values for the 4-step gradient
    def test_range_boundary_at_t025_is_warn(self):
        # t=0.25 → first warn zone
        self.assertEqual(tone_from_range(42.5, good=30, bad=80), "warn")

    def test_range_boundary_at_t050_is_orange(self):
        # t=0.50 → orange zone
        self.assertEqual(tone_from_range(55.0, good=30, bad=80), "orange")

    def test_range_boundary_at_t075_is_bad(self):
        # t=0.75 → red zone
        self.assertEqual(tone_from_range(67.5, good=30, bad=80), "bad")

    # resolve_tone: range override does not apply to non-numeric values
    def test_range_override_non_numeric_returns_none(self):
        data = {"status": "ok", "_style": {"status": {"good": 0, "bad": 100}}}
        self.assertIsNone(resolve_tone(data, "status", "ok"))

    # tone_to_color for all semantic tone names
    def test_tone_to_color_info(self):
        self.assertEqual(tone_to_color("info"), Color.BLUE)

    def test_tone_to_color_neutral(self):
        self.assertEqual(tone_to_color("neutral"), Color.WHITE)

    def test_tone_to_color_muted(self):
        self.assertEqual(tone_to_color("muted"), Color.BLACK)

    def test_tone_to_color_orange(self):
        self.assertEqual(tone_to_color("orange"), Color.ORANGE)

    # Direct color names are also accepted
    def test_tone_to_color_direct_green(self):
        self.assertEqual(tone_to_color("green"), Color.GREEN)

    def test_tone_to_color_direct_violet(self):
        self.assertEqual(tone_to_color("violet"), Color.VIOLET)


class TestSmartRound(unittest.TestCase):
    def test_large_number_no_decimals(self):
        self.assertEqual(smart_round(288.17), "288")

    def test_tens_no_decimals(self):
        self.assertEqual(smart_round(28.17), "28")

    def test_single_digit_one_decimal(self):
        self.assertEqual(smart_round(3.17), "3.2")

    def test_sub_one_two_decimals(self):
        self.assertEqual(smart_round(0.317), "0.32")

    def test_negative_rounds_away_from_zero(self):
        self.assertEqual(smart_round(-12.5), "-13")

    def test_positive_half_rounds_up(self):
        self.assertEqual(smart_round(12.5), "13")

    def test_zero(self):
        self.assertEqual(smart_round(0), "0")

    def test_whole_number_no_trailing_zero(self):
        self.assertEqual(smart_round(10.0), "10")

    def test_hundred(self):
        self.assertEqual(smart_round(100.0), "100")


class TestPrettifyLabel(unittest.TestCase):
    def test_pct_suffix_stripped(self):
        self.assertEqual(prettify_label("wind_pct"), "WIND")

    def test_percent_suffix_stripped(self):
        self.assertEqual(prettify_label("rain_percent"), "RAIN")

    def test_compound_pct_suffix_stripped(self):
        self.assertEqual(prettify_label("wind_delta_pct"), "WIND DELTA")

    def test_non_pct_key_unchanged(self):
        self.assertEqual(prettify_label("temperature"), "TEMPERATURE")

    def test_curr_suffix_stripped(self):
        self.assertEqual(prettify_label("revenue_curr"), "REVENUE")

    def test_compound_curr_suffix_stripped(self):
        self.assertEqual(prettify_label("total_sales_curr"), "TOTAL SALES")

    def test_underscores_become_spaces(self):
        self.assertEqual(prettify_label("bounce_rate"), "BOUNCE RATE")


class TestPctFormatting(unittest.TestCase):
    def test_pct_key_value_has_percent_sign(self):
        msg = render_metrics(FLAGSHIP, {"score_pct": 21.32})
        all_chars = "".join(c for row in msg.grid for c in row if isinstance(c, str))
        self.assertIn("%", all_chars)

    def test_pct_key_label_has_no_pct(self):
        msg = render_metrics(FLAGSHIP, {"score_pct": 21.32})
        all_chars = "".join(c for row in msg.grid for c in row if isinstance(c, str))
        self.assertNotIn("P C T", all_chars)

    def test_curr_key_value_has_dollar_sign(self):
        msg = render_metrics(FLAGSHIP, {"revenue_curr": 84210.50})
        all_chars = "".join(c for row in msg.grid for c in row if isinstance(c, str))
        self.assertIn("$", all_chars)

    def test_curr_key_label_has_no_curr(self):
        msg = render_metrics(FLAGSHIP, {"revenue_curr": 84210.50})
        all_chars = "".join(c for row in msg.grid for c in row if isinstance(c, str))
        self.assertNotIn("C U R R", all_chars)

    def test_non_pct_key_no_percent_sign(self):
        msg = render_metrics(FLAGSHIP, {"score": 21.32})
        all_chars = "".join(c for row in msg.grid for c in row if isinstance(c, str))
        self.assertNotIn("%", all_chars)


class TestRenderMetrics(unittest.TestCase):
    def test_grid_dimensions_flagship(self):
        msg = render_metrics(FLAGSHIP, {"score": 95, "count": 42})
        self.assertEqual(len(msg.grid), 6)
        self.assertEqual(len(msg.grid[0]), 22)

    def test_grid_dimensions_note(self):
        msg = render_metrics(NOTE, {"a": 1, "b": 2, "c": 3, "d": 4})
        self.assertEqual(len(msg.grid), 3)
        self.assertEqual(len(msg.grid[0]), 15)

    def test_underscore_keys_not_rendered(self):
        msg = render_metrics(FLAGSHIP, {"score": 95, "_style": {"score": "good"}})
        all_chars = [cell for row in msg.grid for cell in row if isinstance(cell, str)]
        self.assertNotIn("_STYLE", "".join(all_chars))

    def test_color_indicator_right_edge_on_positive_pct(self):
        msg = render_metrics(FLAGSHIP, {"score_pct": 10.0})
        color_cells = [row[-1] for row in msg.grid if isinstance(row[-1], Color)]
        self.assertTrue(any(c == Color.GREEN for c in color_cells))

    def test_color_indicator_red_on_negative_pct(self):
        msg = render_metrics(FLAGSHIP, {"score_pct": -5.0})
        color_cells = [row[-1] for row in msg.grid if isinstance(row[-1], Color)]
        self.assertTrue(any(c == Color.RED for c in color_cells))

    def test_no_indicator_for_plain_field(self):
        msg = render_metrics(FLAGSHIP, {"score": 95})
        color_cells = [row[-1] for row in msg.grid if isinstance(row[-1], Color)]
        self.assertEqual(color_cells, [])

    def test_style_override_drives_color(self):
        data = {"revenue": 1000, "_style": {"revenue": "warn"}}
        msg = render_metrics(FLAGSHIP, data)
        color_cells = [row[-1] for row in msg.grid if isinstance(row[-1], Color)]
        self.assertTrue(any(c == Color.YELLOW for c in color_cells))

    def test_with_title_uses_first_row(self):
        msg = render_metrics(FLAGSHIP, {"val": 42}, title="DASHBOARD")
        all_chars = "".join(c for row in msg.grid for c in row if isinstance(c, str))
        self.assertIn("DASHBOARD", all_chars)

    def test_to_characters_all_ints(self):
        msg = render_metrics(FLAGSHIP, {"score_pct": 5.0})
        chars = msg.to_characters()
        self.assertEqual(len(chars), 6)
        self.assertEqual(len(chars[0]), 22)
        self.assertTrue(all(isinstance(v, int) for row in chars for v in row))

    def test_color_code_in_characters(self):
        msg = render_metrics(FLAGSHIP, {"score_pct": 5.0})
        chars = msg.to_characters()
        # Color.GREEN = 66 should appear somewhere in the right-most column
        right_col = [row[-1] for row in chars]
        self.assertIn(66, right_col)


class TestValign(unittest.TestCase):
    def test_top_aligns_to_row_zero(self):
        msg = render_metrics(FLAGSHIP, {"score": 95}, valign="top")
        first_content_row = next(
            i for i, row in enumerate(msg.grid)
            if any(c != " " for c in row)
        )
        self.assertEqual(first_content_row, 0)

    def test_center_offsets_from_top(self):
        msg = render_metrics(FLAGSHIP, {"score": 95}, valign="center")
        first_content_row = next(
            i for i, row in enumerate(msg.grid)
            if any(c != " " for c in row)
        )
        self.assertGreater(first_content_row, 0)

    def test_center_content_is_roughly_middle(self):
        # 1 entry on a 6-row board should center around row 2-3
        msg = render_metrics(FLAGSHIP, {"score": 95}, valign="center")
        first_content_row = next(
            i for i, row in enumerate(msg.grid)
            if any(c != " " for c in row)
        )
        self.assertGreaterEqual(first_content_row, 2)

    def test_full_board_same_regardless_of_valign(self):
        # When entries fill the board, top and center produce the same result
        data = {f"k{i}": i for i in range(6)}
        top = render_metrics(FLAGSHIP, data, valign="top").to_characters()
        center = render_metrics(FLAGSHIP, data, valign="center").to_characters()
        self.assertEqual(top, center)


class TestAlign(unittest.TestCase):
    def test_left_starts_at_col_zero(self):
        msg = render_metrics(FLAGSHIP, {"score": 95}, align="left")
        first_content_col = next(
            i for i, c in enumerate(msg.grid[0]) if c != " "
        )
        self.assertEqual(first_content_col, 0)

    def test_center_starts_after_col_zero(self):
        msg = render_metrics(FLAGSHIP, {"score": 95}, align="center")
        first_content_col = next(
            i for i, c in enumerate(msg.grid[0]) if c != " "
        )
        self.assertGreater(first_content_col, 0)

    def test_center_all_rows_same_start_col(self):
        # All content rows should start at the same left offset
        data = {"temp": 68, "humidity": 42, "wind_delta": 3.2}
        msg = render_metrics(FLAGSHIP, data, align="center")
        start_cols = [
            next((i for i, c in enumerate(row) if c != " "), None)
            for row in msg.grid
            if any(c != " " for c in row)
        ]
        self.assertEqual(len(set(start_cols)), 1)

    def test_center_color_tile_adjacent_to_value(self):
        # No space between value and color tile in centered layout
        msg = render_metrics(FLAGSHIP, {"score_pct": 5.0}, align="center")
        for row in msg.grid:
            for i, cell in enumerate(row):
                if isinstance(cell, Color):
                    self.assertNotEqual(row[i - 1], " ")

    def test_center_left_produce_same_characters(self):
        # Centered and left layouts should encode to the same non-space characters
        data = {"score": 95, "count": 42}
        left_chars = set(
            c for row in render_metrics(FLAGSHIP, data, align="left").grid
            for c in row if c != " "
        )
        center_chars = set(
            c for row in render_metrics(FLAGSHIP, data, align="center").grid
            for c in row if c != " "
        )
        self.assertEqual(left_chars, center_chars)


class TestTimestamp(unittest.TestCase):
    def test_timestamp_placed_when_last_row_empty(self):
        msg = render_metrics(FLAGSHIP, {"score": 95}, valign="top")
        before = list(msg.grid[-1])
        msg = place_timestamp(msg)
        # Last row should have changed
        self.assertNotEqual(msg.grid[-1], before)

    def test_timestamp_skipped_when_last_row_full(self):
        # Fill all 6 rows so last row has content
        data = {f"k{i}": i for i in range(FLAGSHIP.rows)}
        msg = render_metrics(FLAGSHIP, data, valign="top")
        last_row_before = list(msg.grid[-1])
        msg = place_timestamp(msg)
        self.assertEqual(msg.grid[-1], last_row_before)

    def test_force_timestamp_overwrites(self):
        data = {f"k{i}": i for i in range(FLAGSHIP.rows)}
        msg = render_metrics(FLAGSHIP, data, valign="top")
        last_row_before = list(msg.grid[-1])
        msg = place_timestamp(msg, force=True)
        self.assertNotEqual(msg.grid[-1], last_row_before)

    def test_timestamp_is_right_aligned(self):
        msg = render_metrics(FLAGSHIP, {"score": 95}, valign="top")
        msg = place_timestamp(msg)
        last_row = msg.grid[-1]
        # Last cell should not be a space (timestamp ends at right edge)
        self.assertNotEqual(last_row[-1], " ")


class TestRenderText(unittest.TestCase):
    def test_grid_dimensions_flagship(self):
        msg = render_text(FLAGSHIP, "HELLO")
        self.assertEqual(len(msg.grid), 6)
        self.assertEqual(len(msg.grid[0]), 22)

    def test_grid_dimensions_note(self):
        msg = render_text(NOTE, "HI")
        self.assertEqual(len(msg.grid), 3)
        self.assertEqual(len(msg.grid[0]), 15)

    def test_to_characters_correct_codes(self):
        msg = render_text(FLAGSHIP, "A")
        chars = msg.to_characters()
        # "A" should appear somewhere in the grid
        flat = [v for row in chars for v in row]
        self.assertIn(1, flat)  # code 1 = A

    def test_valign_top_places_content_on_first_row(self):
        msg = render_text(FLAGSHIP, "HELLO", valign="top")
        # Row 0 should contain content, not be blank
        row0_chars = [c for c in msg.grid[0] if isinstance(c, str) and c != " "]
        self.assertTrue(len(row0_chars) > 0, "Expected content in row 0 for valign=top")

    def test_valign_center_places_content_in_middle(self):
        msg = render_text(FLAGSHIP, "HELLO", valign="center")
        # Single line on flagship (6 rows): top = (6-1)//2 = 2
        # Row 0 should be blank
        row0_chars = [c for c in msg.grid[0] if isinstance(c, str) and c != " "]
        self.assertEqual(row0_chars, [], "Expected row 0 to be blank for valign=center")
        # Row 2 should contain content
        row2_chars = [c for c in msg.grid[2] if isinstance(c, str) and c != " "]
        self.assertTrue(len(row2_chars) > 0, "Expected content in row 2 for valign=center")

    def test_valign_default_is_center(self):
        msg_default = render_text(FLAGSHIP, "HELLO")
        msg_center = render_text(FLAGSHIP, "HELLO", valign="center")
        self.assertEqual(msg_default.grid, msg_center.grid)

    def test_valign_top_via_build_message(self):
        # Integration: valign must thread through build_message → render_text
        from vesta import build_message
        msg = build_message(FLAGSHIP, "text", "HELLO", None, valign="top")
        row0_chars = [c for c in msg.grid[0] if isinstance(c, str) and c != " "]
        self.assertTrue(len(row0_chars) > 0, "Expected content in row 0 for valign=top via build_message")

    def test_valign_center_via_build_message(self):
        from vesta import build_message
        msg = build_message(FLAGSHIP, "text", "HELLO", None, valign="center")
        row0_chars = [c for c in msg.grid[0] if isinstance(c, str) and c != " "]
        self.assertEqual(row0_chars, [], "Expected row 0 blank for valign=center via build_message")


class TestRenderKv(unittest.TestCase):
    def test_underscore_keys_filtered(self):
        msg = render_kv(FLAGSHIP, {"name": "foo", "_hint": "bar"})
        all_chars = "".join(c for row in msg.grid for c in row if isinstance(c, str))
        self.assertNotIn("_HINT", all_chars)

    def test_grid_dimensions(self):
        msg = render_kv(FLAGSHIP, {"a": 1})
        self.assertEqual(len(msg.grid), 6)
        self.assertEqual(len(msg.grid[0]), 22)

    def test_no_spurious_color_reserve(self):
        # _style referencing a key not in data should not narrow the value column.
        with_spurious = render_kv(FLAGSHIP, {"name": "alice", "_style": {"nonexistent": "good"}})
        without_style = render_kv(FLAGSHIP, {"name": "alice"})
        self.assertEqual(with_spurious.grid, without_style.grid)

    def test_color_reserve_only_when_color_resolves(self):
        # _style with a real matching key should reserve a column.
        with_color = render_kv(FLAGSHIP, {"score": 91, "_style": {"score": "good"}})
        without_style = render_kv(FLAGSHIP, {"score": 91})
        # The grids should differ because the color tile shifts the value left.
        self.assertNotEqual(with_color.grid, without_style.grid)
        # Color tile should appear at the right edge.
        self.assertIsInstance(with_color.grid[0][-1], Color)

    # --- columns=2 ---

    def test_columns_2_packs_four_items_into_two_rows(self):
        msg = render_kv(FLAGSHIP, {"a": 1, "b": 2, "c": 3, "d": 4}, columns=2)
        # 4 items → 2 content rows; rows 2-5 should be blank.
        for r in range(2, 6):
            chars = [c for c in msg.grid[r] if isinstance(c, str) and c != " "]
            self.assertEqual(chars, [], f"row {r} should be blank with 4 items in columns=2")

    def test_columns_2_odd_items_last_row_right_blank(self):
        # 3 items → 2 content rows; row 1 has left pair only, right side blank.
        msg = render_kv(FLAGSHIP, {"a": 1, "b": 2, "c": 3}, columns=2)
        row1_content = [c for c in msg.grid[1] if isinstance(c, str) and c != " "]
        self.assertTrue(len(row1_content) > 0, "row 1 should have left-pair content")
        # Row 2 onwards blank (only 2 content rows from 3 items packed into 2 pairs).
        row2_chars = [c for c in msg.grid[2] if isinstance(c, str) and c != " "]
        self.assertEqual(row2_chars, [])

    def test_columns_2_single_item_no_crash(self):
        # 1 item → only left column rendered, right side empty.
        msg = render_kv(FLAGSHIP, {"name": "alice"}, columns=2)
        self.assertEqual(len(msg.grid), 6)
        row0_content = [c for c in msg.grid[0] if isinstance(c, str) and c != " "]
        self.assertTrue(len(row0_content) > 0)
        # Rows 1-5 blank.
        for r in range(1, 6):
            chars = [c for c in msg.grid[r] if isinstance(c, str) and c != " "]
            self.assertEqual(chars, [], f"row {r} should be blank with 1 item")

    def test_columns_2_right_color_tile_at_right_edge(self):
        # Auto-detected pct field in right column → color tile at col 21 (right edge).
        msg = render_kv(FLAGSHIP, {"a": 1, "growth_pct": 5.0}, columns=2)
        self.assertIsInstance(msg.grid[0][-1], Color)

    def test_columns_2_no_color_tiles_without_style(self):
        # Plain keys with no _style and no auto-detected tones → no Color cells.
        msg = render_kv(FLAGSHIP, {"name": "alice", "city": "nyc"}, columns=2)
        color_cells = [c for row in msg.grid for c in row if isinstance(c, Color)]
        self.assertEqual(color_cells, [])

    def test_columns_2_left_color_tile_placed_when_gap_is_one(self):
        # When content fills the board, the gap between columns is trimmed to 1.
        # The left-column color tile must still appear at position left_pw even
        # when gap == 1 (it sits in the single gap cell, not overwriting the right label).
        # a_pct ("A PCT", value "5") → left_pw = 5+1+1 = 7; "note" + 10-char value → gap trims to 1.
        msg = render_kv(FLAGSHIP, {"a_pct": 5.0, "note": "x" * 10}, columns=2)
        self.assertIsInstance(msg.grid[0][7], Color)  # tile at left_pw = 7
        self.assertIsInstance(msg.grid[0][8], str)    # right label starts at left_pw+1, not overwritten

    def test_columns_2_fallback_when_content_too_wide(self):
        # Left pair width alone exceeds note profile; should fall back to 1-col with a warning.
        import contextlib
        data = {"verylonglabel": "val", "hi": "ok"}
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            msg = render_kv(NOTE, data, columns=2)
        self.assertIn("falling back", buf.getvalue())
        self.assertEqual(len(msg.grid), NOTE.rows)  # didn't crash

    # --- long keys / value truncation (wide-board single-col path) ---

    def test_long_key_truncated_on_flagship(self):
        # Wide path: max key display = min(max(len, 6), cols//2) = 11 for FLAGSHIP.
        long_key = "averylonglabelname"  # 18 chars, truncated to 11
        msg = render_kv(FLAGSHIP, {long_key: 42})
        self.assertEqual(len(msg.grid), FLAGSHIP.rows)
        self.assertEqual(len(msg.grid[0]), FLAGSHIP.cols)

    def test_long_key_content_fits_in_row(self):
        long_key = "x" * 20
        msg = render_kv(FLAGSHIP, {long_key: "val"})
        for row in msg.grid:
            self.assertEqual(len(row), FLAGSHIP.cols)

    def test_long_value_truncated_on_flagship(self):
        # right_width = 22 - left_width - 1 - reserve; value must not exceed it.
        msg = render_kv(FLAGSHIP, {"k": "a" * 30})
        self.assertEqual(len(msg.grid), FLAGSHIP.rows)
        for row in msg.grid:
            self.assertEqual(len(row), FLAGSHIP.cols)

    # --- note profile single-col (narrow path) ---

    def test_note_1col_label_appears(self):
        msg = render_kv(NOTE, {"temp": 72})
        all_chars = "".join(c for row in msg.grid for c in row if isinstance(c, str))
        self.assertIn("TEMP", all_chars)

    def test_note_1col_value_appears(self):
        msg = render_kv(NOTE, {"temp": 72})
        all_chars = "".join(c for row in msg.grid for c in row if isinstance(c, str))
        self.assertIn("72", all_chars)

    def test_note_1col_label_on_row0_value_on_row1(self):
        msg = render_kv(NOTE, {"temp": 72})
        row0 = "".join(c for c in msg.grid[0] if isinstance(c, str))
        row1 = "".join(c for c in msg.grid[1] if isinstance(c, str))
        self.assertIn("TEMP", row0)
        self.assertIn("72", row1)

    def test_note_1col_two_pairs_fit(self):
        # Each pair uses 2 rows; 2 pairs fill all 3 rows of NOTE (second value dropped).
        msg = render_kv(NOTE, {"a": 1, "b": 2})
        all_chars = "".join(c for row in msg.grid for c in row if isinstance(c, str))
        self.assertIn("A", all_chars)
        self.assertIn("1", all_chars)
        self.assertIn("B", all_chars)

    # --- title and subtitle on kv ---

    def test_title_appears_in_kv(self):
        msg = render_kv(FLAGSHIP, {"temp": 72}, title="Weather")
        all_chars = "".join(c for row in msg.grid for c in row if isinstance(c, str))
        self.assertIn("WEATHER", all_chars)

    def test_title_color_places_color_tiles(self):
        msg = render_kv(FLAGSHIP, {"temp": 72}, title="Weather", title_color=Color.BLUE)
        color_cells = [c for row in msg.grid for c in row if isinstance(c, Color)]
        self.assertTrue(len(color_cells) > 0)

    def test_subtitle_appears_in_kv(self):
        msg = render_kv(FLAGSHIP, {"temp": 72}, title="Weather", subtitle="Today")
        all_chars = "".join(c for row in msg.grid for c in row if isinstance(c, str))
        self.assertIn("TODAY", all_chars)

    def test_subtitle_short_has_color_tiles(self):
        msg = render_kv(FLAGSHIP, {"temp": 72}, title="Weather", subtitle="Today",
                        title_color=Color.BLUE)
        row1 = msg.grid[1]
        self.assertIsInstance(row1[0], Color)
        self.assertIsInstance(row1[-1], Color)

    def test_subtitle_long_falls_back_to_plain_no_tiles(self):
        # Subtitle longer than cols-2 (20 chars on FLAGSHIP) should render without tiles.
        long_sub = "A" * 21  # 21 > 22-2=20
        msg = render_kv(FLAGSHIP, {"temp": 72}, title="T", subtitle=long_sub,
                        title_color=Color.BLUE)
        row1 = msg.grid[1]
        self.assertNotIsInstance(row1[0], Color)
        self.assertNotIsInstance(row1[-1], Color)

    def test_title_and_subtitle_reduce_content_rows(self):
        # With title + subtitle, only 4 rows remain for content on FLAGSHIP.
        # Without them, all 6 rows are available.
        plain = render_kv(FLAGSHIP, {f"k{i}": i for i in range(6)})
        with_header = render_kv(FLAGSHIP, {f"k{i}": i for i in range(6)}, title="T", subtitle="S")
        plain_chars = "".join(c for row in plain.grid for c in row if isinstance(c, str) and c != " ")
        header_chars = "".join(c for row in with_header.grid for c in row if isinstance(c, str) and c != " ")
        # plain should show more kv content than with_header
        self.assertGreater(len(plain_chars), len(header_chars))

    def test_subtitle_without_title_ignored(self):
        # subtitle is silently ignored when no title is provided.
        with_sub = render_kv(FLAGSHIP, {"temp": 72}, subtitle="Sub")
        without = render_kv(FLAGSHIP, {"temp": 72})
        self.assertEqual(with_sub.grid, without.grid)


class TestRenderTable(unittest.TestCase):
    def test_empty_rows_shows_no_data(self):
        msg = render_table(FLAGSHIP, [])
        all_chars = "".join(c for row in msg.grid for c in row if isinstance(c, str))
        self.assertIn("NO DATA", all_chars)

    def test_grid_dimensions(self):
        rows = [{"name": "alice", "score": 10}, {"name": "bob", "score": 20}]
        msg = render_table(FLAGSHIP, rows)
        self.assertEqual(len(msg.grid), 6)
        self.assertEqual(len(msg.grid[0]), 22)

    def test_grid_dimensions_note(self):
        rows = [{"name": "alice", "score": 10}, {"name": "bob", "score": 20}]
        msg = render_table(NOTE, rows)
        self.assertEqual(len(msg.grid), 3)
        self.assertEqual(len(msg.grid[0]), 15)

    def test_note_fits_header_and_data(self):
        rows = [{"name": "alice", "score": 10}, {"name": "bob", "score": 20}]
        msg = render_table(NOTE, rows)
        all_chars = "".join(c for row in msg.grid for c in row if isinstance(c, str))
        # header row should be present
        self.assertIn("NAME", all_chars)


class TestRenderData(unittest.TestCase):
    def test_dict_dispatches_to_kv_layout(self):
        msg = render_data(FLAGSHIP, {"temp": 68, "humidity": 42})
        self.assertEqual(len(msg.grid), FLAGSHIP.rows)
        all_chars = "".join(c for row in msg.grid for c in row if isinstance(c, str))
        self.assertIn("TEMP", all_chars)

    def test_list_dispatches_to_table_layout(self):
        rows = [{"ticker": "DDOG", "price_curr": 118.35, "change_pct": 2.19}]
        msg = render_data(FLAGSHIP, rows)
        self.assertEqual(len(msg.grid), FLAGSHIP.rows)

    def test_list_applies_suffix_formatting(self):
        rows = [{"ticker": "DDOG", "price_curr": 118.35, "change_pct": 2.19}]
        msg = render_data(FLAGSHIP, rows)
        all_chars = "".join(c for row in msg.grid for c in row if isinstance(c, str))
        self.assertIn("$", all_chars)
        self.assertIn("%", all_chars)

    def test_list_has_color_indicator(self):
        rows = [{"ticker": "DDOG", "price_curr": 118.35, "change_pct": 2.19}]
        msg = render_data(FLAGSHIP, rows)
        all_colors = [c for row in msg.grid for c in row if isinstance(c, Color)]
        self.assertTrue(len(all_colors) > 0)

    def test_list_header_strips_suffix(self):
        rows = [{"ticker": "DDOG", "price_curr": 118.35, "change_pct": 2.19}]
        msg = render_data(FLAGSHIP, rows)
        all_chars = "".join(c for row in msg.grid for c in row if isinstance(c, str))
        self.assertNotIn("CURR", all_chars)
        self.assertNotIn("PCT", all_chars)

    def test_note_dict_grid_dimensions(self):
        msg = render_data(NOTE, {"temp": 68, "humidity": 42})
        self.assertEqual(len(msg.grid), NOTE.rows)
        self.assertEqual(len(msg.grid[0]), NOTE.cols)

    def test_note_dict_shows_label(self):
        msg = render_data(NOTE, {"temp": 68, "humidity": 42})
        all_chars = "".join(c for row in msg.grid for c in row if isinstance(c, str))
        self.assertIn("TEMP", all_chars)

    def test_note_list_grid_dimensions(self):
        rows = [{"ticker": "DDOG", "change_pct": 2.19}]
        msg = render_data(NOTE, rows)
        self.assertEqual(len(msg.grid), NOTE.rows)
        self.assertEqual(len(msg.grid[0]), NOTE.cols)

    def test_note_metrics_color_indicator(self):
        msg = render_data(NOTE, {"change_pct": 2.19})
        all_colors = [c for row in msg.grid for c in row if isinstance(c, Color)]
        self.assertTrue(len(all_colors) > 0)


class TestFormatField(unittest.TestCase):
    def test_pct_suffix_formats_as_percent(self):
        _, value, _ = format_field("score_pct", 21.32, FLAGSHIP)
        self.assertIn("%", value)

    def test_curr_suffix_formats_as_currency(self):
        _, value, _ = format_field("revenue_curr", 84210.50, FLAGSHIP)
        self.assertIn("$", value)

    def test_pct_auto_tone(self):
        _, _, color = format_field("change_pct", 5.0, FLAGSHIP)
        self.assertEqual(color, Color.GREEN)

    def test_negative_pct_auto_tone(self):
        _, _, color = format_field("change_pct", -5.0, FLAGSHIP)
        self.assertEqual(color, Color.RED)

    def test_plain_field_no_color(self):
        _, _, color = format_field("sessions", 1000, FLAGSHIP)
        self.assertIsNone(color)

    def test_style_override(self):
        _, _, color = format_field("sessions", 1000, FLAGSHIP, style={"sessions": "good"})
        self.assertEqual(color, Color.GREEN)


class TestPreview(unittest.TestCase):
    def test_has_border_characters(self):
        msg = render_text(FLAGSHIP, "HI")
        preview = msg.preview(ansi_color=False)
        self.assertIn("┌", preview)
        self.assertIn("┘", preview)
        self.assertIn("│", preview)

    def test_contains_profile_label(self):
        msg = render_text(FLAGSHIP, "HI")
        self.assertIn("flagship", msg.preview(ansi_color=False))

    def test_no_ansi_no_escape_sequences(self):
        msg = render_metrics(FLAGSHIP, {"score_pct": 5.0})
        self.assertNotIn("\033[", msg.preview(ansi_color=False))

    def test_ansi_enabled_has_escape_sequences(self):
        msg = render_metrics(FLAGSHIP, {"score_pct": 5.0})
        self.assertIn("\033[", msg.preview(ansi_color=True))

    def test_flagship_line_count(self):
        msg = render_text(FLAGSHIP, "HI")
        lines = msg.preview(ansi_color=False).splitlines()
        # top border + 6 data rows + bottom border
        self.assertEqual(len(lines), 8)

    def test_note_line_count(self):
        msg = render_text(NOTE, "HI")
        lines = msg.preview(ansi_color=False).splitlines()
        # top border + 3 data rows + bottom border
        self.assertEqual(len(lines), 5)

    def test_visible_spaces_shown_as_dot(self):
        msg = render_text(FLAGSHIP, "HI")
        preview = msg.preview(visible_spaces=True, ansi_color=False)
        self.assertIn("·", preview)

    def test_invisible_spaces_not_shown_as_dot(self):
        msg = render_text(FLAGSHIP, "HI")
        preview = msg.preview(visible_spaces=False, ansi_color=False)
        self.assertNotIn("·", preview)


class TestExplainMetrics(unittest.TestCase):
    def test_auto_tone_field_labeled_auto(self):
        result = explain_metrics({"change_pct": 5.0}, FLAGSHIP, ansi_color=False)
        self.assertIn("auto", result)

    def test_explicit_style_labeled_explicit(self):
        data = {"score": 90, "_style": {"score": "good"}}
        result = explain_metrics(data, FLAGSHIP, ansi_color=False)
        self.assertIn("explicit", result)

    def test_range_style_labeled_range(self):
        data = {"bounce": 55.0, "_style": {"bounce": {"good": 30, "bad": 80}}}
        result = explain_metrics(data, FLAGSHIP, ansi_color=False)
        self.assertIn("range", result)

    def test_range_style_shows_thresholds(self):
        data = {"bounce": 55.0, "_style": {"bounce": {"good": 30, "bad": 80}}}
        result = explain_metrics(data, FLAGSHIP, ansi_color=False)
        self.assertIn("good=30", result)
        self.assertIn("bad=80", result)

    def test_no_color_fields_returns_empty(self):
        result = explain_metrics({"revenue": 1000}, FLAGSHIP, ansi_color=False)
        self.assertEqual(result, "")

    def test_underscore_keys_excluded(self):
        data = {"change_pct": 5.0, "_style": {"change_pct": "good"}}
        result = explain_metrics(data, FLAGSHIP, ansi_color=False)
        self.assertNotIn("_style", result)

    def test_header_line_present(self):
        result = explain_metrics({"change_pct": 5.0}, FLAGSHIP, ansi_color=False)
        self.assertIn("color indicators", result)

    def test_no_ansi_no_escape_sequences(self):
        result = explain_metrics({"change_pct": 5.0}, FLAGSHIP, ansi_color=False)
        self.assertNotIn("\033[", result)

    def test_ansi_color_has_escape_sequences(self):
        result = explain_metrics({"change_pct": 5.0}, FLAGSHIP, ansi_color=True)
        self.assertIn("\033[", result)


class TestLoadPayload(unittest.TestCase):
    def _load_str(self, s: str):
        """Helper: parse s as if it came from stdin."""
        import unittest.mock as mock
        with mock.patch("sys.stdin", io.StringIO(s)):
            return load_payload(None)

    def test_json_dict(self):
        result = self._load_str('{"a": 1}')
        self.assertEqual(result, {"a": 1})

    def test_json_list(self):
        result = self._load_str('[{"a": 1}, {"a": 2}]')
        self.assertEqual(result, [{"a": 1}, {"a": 2}])

    def test_json_string(self):
        result = self._load_str('"hello"')
        self.assertEqual(result, "hello")

    def test_csv_produces_list_of_dicts(self):
        csv_input = textwrap.dedent("""\
            name,score,rank
            alice,98,1
            bob,87,2
        """)
        result = self._load_str(csv_input)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "alice")
        self.assertEqual(result[0]["score"], 98)

    def test_csv_preserves_all_columns(self):
        csv_input = textwrap.dedent("""\
            name,score,rank
            carol,76,3
        """)
        result = self._load_str(csv_input)
        self.assertIn("name", result[0])
        self.assertIn("score", result[0])
        self.assertIn("rank", result[0])

    def test_plain_text_falls_through(self):
        result = self._load_str("not json, not csv")
        self.assertEqual(result, "not json, not csv")

    def test_empty_input_returns_empty_string(self):
        result = self._load_str("   ")
        self.assertEqual(result, "")

    def test_csv_renders_as_table(self):
        """CSV input should produce the same table as equivalent JSON."""
        csv_input = textwrap.dedent("""\
            name,score,rank
            alice,98,1
            bob,87,2
        """)
        json_input = '[{"name": "alice", "score": 98, "rank": 1}, {"name": "bob", "score": 87, "rank": 2}]'
        with __import__("unittest.mock", fromlist=["mock"]).patch("sys.stdin", io.StringIO(csv_input)):
            csv_payload = load_payload(None)
        with __import__("unittest.mock", fromlist=["mock"]).patch("sys.stdin", io.StringIO(json_input)):
            json_payload = load_payload(None)
        csv_msg = render_data(FLAGSHIP, csv_payload)
        json_msg = render_data(FLAGSHIP, json_payload)
        self.assertEqual(csv_msg.grid, json_msg.grid)


class TestNoteEdgeCases(unittest.TestCase):
    # ---- long labels on 15-col grid (narrow single-col path) ----

    def test_long_label_truncated_to_fit_note(self):
        # Label wider than 14 chars must not crash and grid dims must be correct.
        long_label = "averylonglabelname"  # 18 chars > 14
        msg = render_kv(NOTE, {long_label: 42})
        self.assertEqual(len(msg.grid), NOTE.rows)
        self.assertEqual(len(msg.grid[0]), NOTE.cols)

    def test_long_label_row_width_not_exceeded(self):
        long_label = "x" * 20
        msg = render_kv(NOTE, {long_label: "val"})
        for row in msg.grid:
            self.assertEqual(len(row), NOTE.cols)

    def test_long_value_truncated_to_fit_note(self):
        long_value = "a" * 30  # 30 chars > 15
        msg = render_kv(NOTE, {"key": long_value})
        self.assertEqual(len(msg.grid), NOTE.rows)
        # Value row (row 1) must not spill past board width.
        self.assertEqual(len(msg.grid[1]), NOTE.cols)

    # ---- timestamp on NOTE ----

    def test_timestamp_placed_on_note_when_last_row_empty(self):
        # 1 kv pair on NOTE uses rows 0 and 1; row 2 is blank → timestamp fits.
        msg = render_kv(NOTE, {"temp": 72})
        last_before = list(msg.grid[-1])
        msg = place_timestamp(msg)
        self.assertNotEqual(msg.grid[-1], last_before)

    def test_timestamp_skipped_on_note_when_last_row_full(self):
        # With a title + 1 kv pair: title→row0, label→row1, value right-aligned→row2.
        # The value occupies the rightmost cell, which blocks the timestamp buffer.
        msg = render_kv(NOTE, {"a": 1}, title="T")
        last_before = list(msg.grid[-1])
        msg = place_timestamp(msg)
        self.assertEqual(msg.grid[-1], last_before)

    def test_force_timestamp_on_note_overwrites(self):
        msg = render_kv(NOTE, {"a": 1, "b": 2})
        last_before = list(msg.grid[-1])
        msg = place_timestamp(msg, force=True)
        self.assertNotEqual(msg.grid[-1], last_before)

    def test_timestamp_right_aligned_on_note(self):
        msg = render_kv(NOTE, {"temp": 72})
        msg = place_timestamp(msg)
        self.assertNotEqual(msg.grid[-1][-1], " ")

    # ---- many-column table on NOTE (column dropping) ----

    def test_note_table_drops_excess_columns(self):
        # 5 plain columns on NOTE (15 cols, no color reserve).
        # n=4: (15-3)//4 = 3 >= 3 → fits; n=5: (15-4)//5 = 2 < 3 → drop.
        rows = [{"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}]
        import sys
        stderr_capture = io.StringIO()
        orig = sys.stderr
        sys.stderr = stderr_capture
        try:
            msg = render_table(NOTE, rows)
        finally:
            sys.stderr = orig
        self.assertIn("dropped", stderr_capture.getvalue())
        self.assertEqual(len(msg.grid), NOTE.rows)

    def test_note_table_dropped_column_warning_names_column(self):
        rows = [{"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}]
        import sys
        stderr_capture = io.StringIO()
        orig = sys.stderr
        sys.stderr = stderr_capture
        try:
            render_table(NOTE, rows)
        finally:
            sys.stderr = orig
        warning = stderr_capture.getvalue()
        # The dropped column(s) should be named in the warning.
        self.assertIn("e", warning)

    def test_note_table_with_color_col_drops_at_four(self):
        # With a change_pct col (triggers color reserve → available=14),
        # n=4: (14-3)//4 = 2 < 3 → only 3 columns fit.
        rows = [{"a": 1, "b": 2, "c": 3, "change_pct": 0.5}]
        import sys
        stderr_capture = io.StringIO()
        orig = sys.stderr
        sys.stderr = stderr_capture
        try:
            msg = render_table(NOTE, rows)
        finally:
            sys.stderr = orig
        self.assertIn("dropped", stderr_capture.getvalue())

    def test_note_table_two_columns_fit_without_warning(self):
        rows = [{"name": "alice", "score": 10}]
        import sys
        stderr_capture = io.StringIO()
        orig = sys.stderr
        sys.stderr = stderr_capture
        try:
            render_table(NOTE, rows)
        finally:
            sys.stderr = orig
        self.assertEqual(stderr_capture.getvalue(), "")


class TestColumnsWarning(unittest.TestCase):
    """--columns 2 on non-kv templates should emit a warning."""

    def _stderr_for(self, argv: list[str], stdin_text: str) -> str:
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()):
            with contextlib.redirect_stderr(buf):
                with __import__("unittest.mock", fromlist=["patch"]).patch(
                    "sys.stdin", io.StringIO(stdin_text)
                ):
                    cli(argv)
        return buf.getvalue()

    def test_columns_2_warns_on_text_template(self):
        out = self._stderr_for(
            ["render", "--columns", "2", "--template", "text", "--no-preview"],
            '"hello"',
        )
        self.assertIn("warning", out)
        self.assertIn("text", out)

    def test_columns_2_warns_on_data_template(self):
        out = self._stderr_for(
            ["render", "--columns", "2", "--template", "data", "--no-preview"],
            '{"score": 91}',
        )
        self.assertIn("warning", out)
        self.assertIn("data", out)

    def test_columns_2_warns_on_table_template(self):
        out = self._stderr_for(
            ["render", "--columns", "2", "--template", "table", "--no-preview"],
            '[{"name": "alice", "score": 10}]',
        )
        self.assertIn("warning", out)
        self.assertIn("table", out)

    def test_columns_2_warns_on_metrics_template(self):
        out = self._stderr_for(
            ["render", "--columns", "2", "--template", "metrics", "--no-preview"],
            '{"score": 91}',
        )
        self.assertIn("warning", out)
        self.assertIn("metrics", out)

    def test_columns_2_no_warning_on_kv_template(self):
        out = self._stderr_for(
            ["render", "--columns", "2", "--template", "kv", "--no-preview"],
            '{"a": 1, "b": 2}',
        )
        self.assertNotIn("warning", out)

    def test_columns_1_no_warning_on_any_template(self):
        # Default --columns 1 should never trigger the warning.
        out = self._stderr_for(
            ["render", "--template", "text", "--no-preview"],
            '"hello"',
        )
        self.assertNotIn("warning", out)

    def test_columns_2_no_warning_on_auto_template(self):
        # auto may route to kv; suppress the warning for auto.
        out = self._stderr_for(
            ["render", "--columns", "2", "--template", "auto", "--no-preview"],
            '{"a": 1, "b": 2}',
        )
        self.assertNotIn("--columns", out)

class TestCliExplain(unittest.TestCase):
    """End-to-end tests for `vesta render --explain` via the cli() entry point."""

    def _run(self, argv: list[str], stdin_text: str) -> str:
        """Call cli() with patched stdin and return captured stdout."""
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with __import__("unittest.mock", fromlist=["patch"]).patch(
                "sys.stdin", io.StringIO(stdin_text)
            ):
                cli(argv)
        return buf.getvalue()

    def test_explain_auto_tone_appears_in_output(self):
        # change_pct with positive value → auto-detected green → "auto" in explain output.
        out = self._run(
            ["render", "--explain", "--no-preview", "--no-ansi"],
            '{"change_pct": 5.0}',
        )
        self.assertIn("auto", out)

    def test_explain_shows_field_label(self):
        out = self._run(
            ["render", "--explain", "--no-preview", "--no-ansi"],
            '{"change_pct": 5.0}',
        )
        self.assertIn("CHANGE", out)

    def test_explain_explicit_style_shown(self):
        # _style with an explicit tone → "explicit" in explain output.
        out = self._run(
            ["render", "--explain", "--no-preview", "--no-ansi"],
            '{"score": 91, "_style": {"score": "good"}}',
        )
        self.assertIn("explicit", out)

    def test_explain_silent_when_no_color_fields(self):
        # Plain dict with no tone-triggering keys → explain returns "" → nothing extra.
        out = self._run(
            ["render", "--explain", "--no-preview", "--no-ansi"],
            '{"name": "alice", "city": "nyc"}',
        )
        # Output should be only the JSON array (no explain block).
        import json as _json
        parsed = _json.loads(out.strip())
        self.assertIsInstance(parsed, list)

    def test_explain_skipped_for_list_payload(self):
        # --explain is silently ignored when payload is a list (table data).
        out = self._run(
            ["render", "--explain", "--no-preview", "--no-ansi"],
            '[{"ticker": "DDOG", "change_pct": 2.19}]',
        )
        # Should not contain "auto" or "explicit" — just JSON output.
        self.assertNotIn("auto", out)
        self.assertNotIn("explicit", out)

    def test_explain_works_on_note_profile(self):
        out = self._run(
            ["render", "--explain", "--no-preview", "--no-ansi", "--profile", "note"],
            '{"change_pct": -3.5}',
        )
        self.assertIn("auto", out)

    def test_explain_with_range_style_shows_range(self):
        payload = '{"temp": 75, "_style": {"temp": {"good": 65, "bad": 90}}}'
        out = self._run(
            ["render", "--explain", "--no-preview", "--no-ansi"],
            payload,
        )
        self.assertIn("range", out)

    def test_title_color_none_produces_no_tiles(self):
        import json as _json
        out = self._run(
            ["render", "--template", "kv", "--title", "Weather",
             "--title-color", "none", "--no-preview", "--no-ansi"],
            '{"temp": 72}',
        )
        grid = _json.loads(out.strip())
        color_codes = {c.value for c in Color}
        row0 = grid[0]
        self.assertFalse(any(cell in color_codes for cell in row0),
                         "row 0 should have no color tiles with --title-color none")


if __name__ == "__main__":
    unittest.main()
