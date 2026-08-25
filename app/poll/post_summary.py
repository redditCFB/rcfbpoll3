from functools import lru_cache
from io import BytesIO
import os
import tempfile
from pathlib import Path

import requests
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .models import Ballot, UserRole
from .utils import get_result_set_record, get_results_comparison


WIDTH = 1200
HEIGHT = 1500
PAPER = "#f7f3eb"
NAVY = "#081f2c"
GREEN = "#0e8f68"
MINT = "#a7e8ce"
GOLD = "#f1b743"
CORAL = "#e45f58"
INK = "#0d2534"
MUTED = "#657580"
WHITE = "#ffffff"
SURFACE_LIGHT = "#173b4d"


def _font(size, bold=False):
    names = (
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text(draw, xy, value, size=24, bold=False, fill=INK, anchor=None):
    draw.text(xy, str(value), font=_font(size, bold), fill=fill, anchor=anchor)


def _draw_fitted(draw, xy, value, max_width, size=24, min_size=10, bold=False, fill=INK, anchor=None):
    value = str(value)
    current_size = size
    while current_size > min_size:
        font = _font(current_size, bold)
        if draw.textbbox((0, 0), value, font=font)[2] <= max_width:
            break
        current_size -= 1
    draw.text(xy, value, font=_font(current_size, bold), fill=fill, anchor=anchor)


def _team_name(team):
    return team.short_name or team.name


def build_post_summary(poll):
    comparison = list(get_results_comparison(poll))
    top25 = [row for row in comparison if row["rank"] <= 25]
    voter_count = Ballot.objects.filter(
        poll=poll,
        submission_date__isnull=False,
        user_type=UserRole.Role.VOTER,
    )
    voter_count = voter_count.count()

    return {
        "poll": str(poll),
        "voter_count": voter_count,
        "top25": top25,
    }


@lru_cache(maxsize=256)
def _load_logo(handle):
    url = settings.TEAM_LOGO_URL_TEMPLATE.format(handle=handle)
    try:
        response = requests.get(url, timeout=(2, 4))
        response.raise_for_status()
        image = Image.open(BytesIO(response.content)).convert("RGBA")
        image.thumbnail((320, 320), Image.Resampling.LANCZOS)
        return image.copy()
    except (OSError, requests.RequestException):
        return None


def _paste_logo(canvas, handle, box, border=GREEN, frame=True):
    x, y, width, height = box
    draw = ImageDraw.Draw(canvas)
    if frame:
        radius = min(20, width // 4, height // 4)
        draw.rounded_rectangle((x, y, x + width, y + height), radius=radius, fill=WHITE, outline=border, width=3)
    logo = _load_logo(handle)
    if logo:
        fitted = ImageOps.contain(logo, (width - 18, height - 18))
        canvas.alpha_composite(fitted, (x + (width - fitted.width) // 2, y + (height - fitted.height) // 2))
    else:
        _text(draw, (x + width // 2, y + height // 2), handle[:3].upper(), size=max(14, width // 4), bold=True, anchor="mm", fill=GREEN)


@lru_cache(maxsize=1)
def _load_site_logo():
    paths = (
        Path(settings.BASE_DIR) / "poll" / "static" / "images" / "poll.png",
        Path(settings.STATIC_ROOT) / "images" / "poll.png",
    )
    for path in paths:
        try:
            return Image.open(path).convert("RGBA")
        except OSError:
            continue
    return None


def _movement_label(result):
    change = result.get("rank_diff", 0)
    rank_text = result.get("rank_diff_str", "--")
    if rank_text == "NEW":
        return "NEW", "new"
    if change == 0:
        return "—", "hold"
    return (f"+{change}", "up") if change > 0 else (f"−{abs(change)}", "down")


def _draw_team_mark(canvas, draw, result, center_x, top_y, logo_size, slot_width, name_size, rank_size, on_dark=False):
    label, state = _movement_label(result)
    colors = {
        "up": MINT if on_dark else GREEN,
        "down": "#ff8a83" if on_dark else CORAL,
        "new": GOLD,
        "hold": "#91a4af" if on_dark else MUTED,
    }
    rank_fill = MINT if on_dark else GREEN
    name_fill = WHITE if on_dark else INK
    _text(draw, (center_x - 9, top_y + 9), f'#{result["rank"]}', size=rank_size, bold=True, fill=rank_fill, anchor="ra")
    _text(draw, (center_x + 11, top_y + 9), label, size=max(10, rank_size - 7), bold=True, fill=colors[state], anchor="la")
    logo_y = top_y + rank_size + 13
    _paste_logo(canvas, result["team"].handle, (int(center_x - logo_size / 2), logo_y, logo_size, logo_size), frame=False)
    name_y = logo_y + logo_size + 10
    _draw_fitted(draw, (center_x, name_y), _team_name(result["team"]), slot_width - 12, size=name_size, min_size=10, bold=True, fill=name_fill, anchor="ma")


def _draw_empty_state(draw):
    _text(draw, (WIDTH / 2, 520), "Results coming soon", size=42, bold=True, fill=WHITE, anchor="mm")
    _text(draw, (WIDTH / 2, 565), "The next community Top 25 will appear here.", size=19, fill=MINT, anchor="mm")


def render_post_summary(poll):
    summary = build_post_summary(poll)
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), NAVY)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((38, 132, 1162, 136), fill=GREEN)

    site_logo = _load_site_logo()
    if site_logo:
        fitted = ImageOps.contain(site_logo, (76, 76))
        canvas.alpha_composite(fitted, (42, 30))
    _text(draw, (136, 31), "THE r/CFB POLL", size=17, bold=True, fill=MINT)
    _draw_fitted(draw, (136, 61), summary["poll"], 700, size=43, min_size=29, bold=True, fill=WHITE)
    draw.line((924, 31, 924, 105), fill="#315060", width=2)
    _text(draw, (957, 40), summary["voter_count"], size=32, bold=True, fill=WHITE)
    _text(draw, (957, 78), "HUMAN BALLOTS", size=11, bold=True, fill="#91a4af")

    top25 = summary["top25"]
    if top25:
        draw.rounded_rectangle((38, 158, 1162, 940), radius=28, fill=PAPER)
        _text(draw, (66, 181), "A PLAYOFF-SIZED TOP 12", size=17, bold=True, fill=INK)
        _text(draw, (1134, 185), "POLL RANKS  /  NOT A BRACKET", size=10, bold=True, fill=MUTED, anchor="ra")

        rows = (
            (top25[0:1], (600,), 198, 180, 280, 24, 25),
            (top25[1:3], (375, 825), 426, 128, 330, 18, 21),
            (top25[3:7], (170, 455, 745, 1030), 600, 98, 230, 15, 18),
            (top25[7:12], (125, 362, 600, 838, 1075), 754, 84, 190, 13, 16),
        )
        for results, centers, top_y, logo_size, slot_width, name_size, rank_size in rows:
            for result, center_x in zip(results, centers):
                _draw_team_mark(canvas, draw, result, center_x, top_y, logo_size, slot_width, name_size, rank_size)

        draw.rounded_rectangle((430, 918, 770, 954), radius=18, fill=GREEN)
        _text(draw, (600, 936), "12-TEAM CUT LINE", size=13, bold=True, fill=WHITE, anchor="mm")

        _text(draw, (40, 982), "THE REST OF THE TOP 25", size=17, bold=True, fill=WHITE)
        _text(draw, (1160, 986), "RANKS 13–25", size=10, bold=True, fill="#91a4af", anchor="ra")
        lower_rows = (
            (top25[12:18], (110, 306, 502, 698, 894, 1090), 1004, 96, 182),
            (top25[18:25], (90, 260, 430, 600, 770, 940, 1110), 1204, 96, 156),
        )
        for results, centers, top_y, logo_size, slot_width in lower_rows:
            for result, center_x in zip(results, centers):
                _draw_team_mark(canvas, draw, result, center_x, top_y, logo_size, slot_width, 14, 16, on_dark=True)
        draw.line((40, 1418, 1160, 1418), fill=SURFACE_LIGHT, width=1)
    else:
        _draw_empty_state(draw)

    _text(draw, (40, 1458), "POLL.REDDITCFB.COM", size=15, bold=True, fill=MINT, anchor="lm")
    _text(draw, (1160, 1458), "THE HUMAN TOP 25", size=11, bold=True, fill="#91a4af", anchor="rm")
    output = BytesIO()
    canvas.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()


def post_summary_path(poll):
    return Path(settings.STATIC_ROOT) / "post_summaries" / f"poll-{poll.pk}.png"


def cache_post_summary(poll, refresh=False):
    path = post_summary_path(poll)
    result_set = get_result_set_record(poll)
    result_timestamp = result_set.time_calculated.timestamp()
    if path.exists() and not refresh and path.stat().st_mtime >= result_timestamp:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".png", delete=False) as temporary:
        temporary.write(render_post_summary(poll))
        temporary_path = temporary.name
    os.replace(temporary_path, path)
    return path
