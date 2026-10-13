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
        content_box = image.getbbox()
        if content_box:
            image = image.crop(content_box)
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


def _draw_ranked_logo(canvas, draw, result, center_x, top_y, logo_size, badge_size, on_dark=False):
    logo_x = int(center_x - logo_size / 2)
    _paste_logo(canvas, result["team"].handle, (logo_x, top_y, logo_size, logo_size), frame=False)
    badge_x = logo_x - int(badge_size * 0.18)
    badge_y = top_y - int(badge_size * 0.14)
    outline = MINT if on_dark else PAPER
    draw.ellipse((badge_x, badge_y, badge_x + badge_size, badge_y + badge_size), fill=GREEN, outline=outline, width=3)
    rank_size = max(13, int(badge_size * 0.32))
    _text(draw, (badge_x + badge_size / 2, badge_y + badge_size / 2), f'#{result["rank"]}', size=rank_size, bold=True, fill=WHITE, anchor="mm")


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
    _text(draw, (957, 78), "HUMAN BALLOTS", size=13, bold=True, fill="#91a4af")

    top25 = summary["top25"]
    if top25:
        draw.rounded_rectangle((38, 158, 1162, 1000), radius=28, fill=PAPER)
        _text(draw, (66, 181), "THE TOP 12", size=23, bold=True, fill=INK)
        _text(draw, (1134, 183), "A PLAYOFF-SIZED CUT", size=15, bold=True, fill=MUTED, anchor="ra")

        top_rows = (
            (top25[0:1], (600,), 205, 210, 54),
            (top25[1:3], (350, 850), 458, 185, 48),
            (top25[3:7], (150, 450, 750, 1050), 650, 145, 44),
            (top25[7:12], (120, 360, 600, 840, 1080), 805, 125, 42),
        )
        for results, centers, top_y, logo_size, badge_size in top_rows:
            for result, center_x in zip(results, centers):
                _draw_ranked_logo(canvas, draw, result, center_x, top_y, logo_size, badge_size)
        _draw_fitted(draw, (600, 425), _team_name(top25[0]["team"]), 420, size=30, min_size=20, bold=True, fill=INK, anchor="ma")

        draw.rounded_rectangle((415, 979, 785, 1021), radius=21, fill=GREEN)
        _text(draw, (600, 1000), "12-TEAM CUT LINE", size=16, bold=True, fill=WHITE, anchor="mm")

        _text(draw, (40, 1045), "13–25", size=23, bold=True, fill=WHITE)
        lower_rows = (
            (top25[12:18], (110, 306, 502, 698, 894, 1090), 1085, 125, 44),
            (top25[18:25], (90, 260, 430, 600, 770, 940, 1110), 1270, 125, 44),
        )
        for results, centers, top_y, logo_size, badge_size in lower_rows:
            for result, center_x in zip(results, centers):
                _draw_ranked_logo(canvas, draw, result, center_x, top_y, logo_size, badge_size, on_dark=True)
        draw.line((40, 1418, 1160, 1418), fill=SURFACE_LIGHT, width=1)
    else:
        _draw_empty_state(draw)

    _text(draw, (40, 1458), "POLL.REDDITCFB.COM", size=15, bold=True, fill=MINT, anchor="lm")
    _text(draw, (1160, 1458), "THE HUMAN TOP 25", size=13, bold=True, fill="#91a4af", anchor="rm")
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
