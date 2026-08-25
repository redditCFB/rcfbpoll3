from functools import lru_cache
from io import BytesIO
import os
import tempfile
from pathlib import Path

import requests
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .models import Ballot, UserRole
from .utils import get_result_set, get_result_set_record, get_results_comparison


WIDTH = 1200
HEIGHT = 1500
PAPER = "#f4f0e6"
NAVY = "#0b2231"
GREEN = "#159a72"
MINT = "#a7e8ce"
GOLD = "#f6c64f"
CORAL = "#f16c64"
INK = "#102333"
MUTED = "#607381"
WHITE = "#ffffff"
SURFACE = "#123044"
SURFACE_LIGHT = "#1a3c50"
LINE = "#d9d5cb"
LILAC = "#e7def2"
PEACH = "#ffdfaa"


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


def _team_payload(team, **values):
    payload = {
        "handle": team.handle,
        "name": team.name,
        "short_name": _team_name(team),
    }
    payload.update(values)
    return payload


def build_post_summary(poll):
    comparison = list(get_results_comparison(poll))
    top25 = [row for row in comparison if row["rank"] <= 25]
    voter_count = Ballot.objects.filter(
        poll=poll,
        submission_date__isnull=False,
        user_type=UserRole.Role.VOTER,
    )
    voter_count = voter_count.count()

    dropped = []
    if poll.last_week:
        current_ids = {row["team"].id for row in top25}
        dropped = [
            _team_payload(row.team, rank=row.rank)
            for row in get_result_set(poll.last_week)
            if row.rank <= 25 and row.team_id not in current_ids
        ]

    polarizing = sorted(top25, key=lambda row: row["std_dev"], reverse=True)[:3]
    polarizing = [
        _team_payload(
            row["team"],
            rank=row["rank"],
            std_dev=row["std_dev"],
            coverage=row["votes"] / voter_count if voter_count else 0,
        )
        for row in polarizing
    ]
    biggest_ppv_gain = max(top25, key=lambda row: row["ppv_diff"], default=None)
    biggest_ppv_loss = min(top25, key=lambda row: row["ppv_diff"], default=None)

    return {
        "poll": str(poll),
        "voter_count": voter_count,
        "top25": top25,
        "biggest_ppv_gain": biggest_ppv_gain,
        "biggest_ppv_loss": biggest_ppv_loss,
        "dropped": dropped[:3],
        "polarizing": polarizing,
    }


@lru_cache(maxsize=256)
def _load_logo(handle):
    url = settings.TEAM_LOGO_URL_TEMPLATE.format(handle=handle)
    try:
        response = requests.get(url, timeout=(2, 4))
        response.raise_for_status()
        image = Image.open(BytesIO(response.content)).convert("RGBA")
        image.thumbnail((180, 180), Image.Resampling.LANCZOS)
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


def _draw_movement(draw, result, x, y, compact=False):
    change = result.get("rank_diff", 0)
    rank_text = result.get("rank_diff_str", "--")
    if rank_text == "NEW":
        _text(draw, (x, y), "NEW", size=12 if compact else 14, bold=True, fill=GOLD, anchor="mm")
        return
    if change == 0:
        draw.rounded_rectangle((x - 8, y - 1, x + 8, y + 2), radius=2, fill=MUTED)
        return
    color = GREEN if change > 0 else CORAL
    direction = 1 if change > 0 else -1
    draw.polygon(((x - 9, y + direction * 5), (x, y - direction * 6), (x + 9, y + direction * 5)), fill=color)
    _text(draw, (x + 18, y), abs(change), size=14 if compact else 17, bold=True, fill=color, anchor="lm")


def _draw_featured_team(canvas, draw, result, box):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=30, fill=GREEN)
    draw.ellipse((x2 - 220, y1 + 30, x2, y1 + 250), fill="#20a77e")
    _text(draw, (x1 + 30, y1 + 28), "THIS WEEK'S NO. 1", size=18, bold=True, fill="#d8f5e9")
    _text(draw, (x1 + 30, y1 + 73), "#1", size=66, bold=True, fill=WHITE)
    _draw_movement(draw, result, x1 + 125, y1 + 99)
    _paste_logo(canvas, result["team"].handle, (x1 + 188, y1 + 56, 205, 205), frame=False)
    _draw_fitted(draw, (x1 + 30, y2 - 74), _team_name(result["team"]), x2 - x1 - 60, size=37, min_size=23, bold=True, fill=WHITE)
    _text(draw, (x1 + 30, y2 - 35), "The r/CFB community's top-ranked team", size=15, fill="#d8f5e9")


def _draw_contender(canvas, draw, result, box):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=24, fill=SURFACE_LIGHT)
    _text(draw, (x1 + 22, y1 + 22), f'#{result["rank"]}', size=30, bold=True, fill=MINT)
    _draw_movement(draw, result, x1 + 80, y1 + 40, compact=True)
    _paste_logo(canvas, result["team"].handle, (x2 - 118, y1 + 20, 94, 94), frame=False)
    _draw_fitted(draw, (x1 + 22, y2 - 37), _team_name(result["team"]), x2 - x1 - 44, size=21, min_size=14, bold=True, fill=WHITE)


def _draw_ranked_row(canvas, draw, result, box):
    x1, y1, x2, y2 = box
    _text(draw, (x1 + 4, (y1 + y2) / 2), result["rank"], size=20, bold=True, fill=GREEN, anchor="lm")
    _paste_logo(canvas, result["team"].handle, (x1 + 38, y1 + 8, 48, 48), frame=False)
    _draw_fitted(draw, (x1 + 96, y1 + 22), _team_name(result["team"]), x2 - x1 - 144, size=16, min_size=11, bold=True, fill=INK, anchor="lm")
    _draw_movement(draw, result, x2 - 28, (y1 + y2) / 2, compact=True)
    draw.line((x1, y2, x2, y2), fill=LINE, width=1)


def _draw_momentum(canvas, draw, summary, box):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=28, fill=PEACH)
    _text(draw, (x1 + 28, y1 + 26), "MOMENTUM", size=22, bold=True, fill=NAVY)
    _text(draw, (x1 + 28, y1 + 55), "Biggest points-per-voter moves", size=14, fill=MUTED)
    rows = (("RISING", summary["biggest_ppv_gain"], GREEN, "+"), ("FALLING", summary["biggest_ppv_loss"], CORAL, "−"))
    for index, (label, result, color, sign) in enumerate(rows):
        if not result:
            continue
        y = y1 + 85 + index * 77
        _paste_logo(canvas, result["team"].handle, (x1 + 28, y, 62, 62), border=color)
        _text(draw, (x1 + 108, y + 5), label, size=12, bold=True, fill=color)
        _draw_fitted(draw, (x1 + 108, y + 30), _team_name(result["team"]), 235, size=19, min_size=13, bold=True, fill=INK)
        _text(draw, (x2 - 28, y + 26), f'{sign}{abs(result["ppv_diff"]):.2f}', size=25, bold=True, fill=color, anchor="ra")
        _text(draw, (x2 - 28, y + 52), "points per voter", size=12, fill=MUTED, anchor="ra")
    if summary["dropped"]:
        _text(draw, (x1 + 28, y2 - 27), "OUT THIS WEEK", size=12, bold=True, fill=MUTED)
        names = "  •  ".join(item["short_name"] for item in summary["dropped"])
        _draw_fitted(draw, (x1 + 150, y2 - 27), names, x2 - x1 - 180, size=14, min_size=10, bold=True, fill=INK)


def _draw_polarizing(canvas, draw, summary, box):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=28, fill=LILAC)
    _text(draw, (x1 + 28, y1 + 26), "THE DEBATE", size=22, bold=True, fill=NAVY)
    _text(draw, (x1 + 28, y1 + 55), "Top 25 teams voters disagree on most", size=14, fill=MUTED)
    max_std = max((item["std_dev"] for item in summary["polarizing"]), default=1) or 1
    for index, item in enumerate(summary["polarizing"]):
        y = y1 + 88 + index * 63
        _paste_logo(canvas, item["handle"], (x1 + 28, y - 5, 50, 50), border=NAVY)
        _text(draw, (x1 + 94, y + 4), f'#{item["rank"]}', size=14, bold=True, fill=NAVY)
        _draw_fitted(draw, (x1 + 132, y + 4), item["short_name"], 190, size=17, min_size=11, bold=True, fill=INK)
        _text(draw, (x1 + 94, y + 29), f'{item["coverage"]:.0%} of ballots', size=12, fill=MUTED)
        bar_width = int(160 * item["std_dev"] / max_std)
        draw.rounded_rectangle((x2 - 190, y + 16, x2 - 30, y + 27), radius=6, fill="#cec3dc")
        draw.rounded_rectangle((x2 - 190, y + 16, x2 - 190 + bar_width, y + 27), radius=6, fill=NAVY)


def _draw_empty_state(draw):
    _text(draw, (WIDTH / 2, 520), "Results coming soon", size=42, bold=True, fill=WHITE, anchor="mm")
    _text(draw, (WIDTH / 2, 565), "The next community Top 25 will appear here.", size=19, fill=MINT, anchor="mm")


def render_post_summary(poll):
    summary = build_post_summary(poll)
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), NAVY)
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((865, -210, 1275, 200), fill=SURFACE)
    draw.ellipse((1010, -95, 1260, 155), fill=SURFACE_LIGHT)

    site_logo = _load_site_logo()
    if site_logo:
        fitted = ImageOps.contain(site_logo, (82, 82))
        canvas.alpha_composite(fitted, (40, 35))
    _text(draw, (142, 37), "THE r/CFB COMMUNITY POLL", size=18, bold=True, fill=MINT)
    _draw_fitted(draw, (142, 68), summary["poll"], 690, size=44, min_size=30, bold=True, fill=WHITE)
    draw.rounded_rectangle((936, 47, 1157, 103), radius=28, fill=SURFACE_LIGHT)
    _text(draw, (1046, 65), summary["voter_count"], size=24, bold=True, fill=WHITE, anchor="ma")
    _text(draw, (1046, 88), "BALLOTS", size=11, bold=True, fill=MINT, anchor="ma")

    top25 = summary["top25"]
    if top25:
        _draw_featured_team(canvas, draw, top25[0], (38, 150, 470, 515))
        contender_boxes = ((494, 150, 820, 327), (836, 150, 1162, 327), (494, 339, 820, 515), (836, 339, 1162, 515))
        for result, box in zip(top25[1:5], contender_boxes):
            _draw_contender(canvas, draw, result, box)

        draw.rounded_rectangle((38, 540, 1162, 1068), radius=30, fill=PAPER)
        _text(draw, (66, 566), "THE TOP 25", size=22, bold=True, fill=NAVY)
        _text(draw, (1134, 571), "WEEK-OVER-WEEK MOVEMENT", size=11, bold=True, fill=MUTED, anchor="ra")
        rows = top25[5:25]
        column_width = 267
        for index, result in enumerate(rows):
            column = index // 5
            row = index % 5
            x1 = 66 + column * 273
            y1 = 620 + row * 82
            _draw_ranked_row(canvas, draw, result, (x1, y1, x1 + column_width, y1 + 65))

        _draw_momentum(canvas, draw, summary, (38, 1094, 588, 1418))
        _draw_polarizing(canvas, draw, summary, (612, 1094, 1162, 1418))
    else:
        _draw_empty_state(draw)

    _text(draw, (45, 1462), "POLL.REDDITCFB.COM", size=15, bold=True, fill=MINT, anchor="lm")
    _text(draw, (1155, 1462), "25 TEAMS  •  HUMAN BALLOTS  •  EVERY WEEK", size=13, fill="#a9bac4", anchor="rm")
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
