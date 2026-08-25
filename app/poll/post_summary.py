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
PAPER = "#f7f3eb"
NAVY = "#081f2c"
GREEN = "#0e8f68"
MINT = "#a7e8ce"
GOLD = "#f1b743"
CORAL = "#e45f58"
INK = "#0d2534"
MUTED = "#657580"
WHITE = "#ffffff"
SURFACE = "#102f40"
SURFACE_LIGHT = "#173b4d"
LINE = "#dcd7ce"


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


def _movement(result):
    change = result.get("rank_diff", 0)
    rank_text = result.get("rank_diff_str", "--")
    if rank_text == "NEW":
        return "NEW", "new"
    if change == 0:
        return "HOLD", "hold"
    return (f"UP {change}", "up") if change > 0 else (f"DOWN {abs(change)}", "down")


def _draw_movement(draw, result, x, y, on_dark=False, anchor="mm", size=11):
    label, state = _movement(result)
    colors = {
        "up": MINT if on_dark else GREEN,
        "down": "#ff8a83" if on_dark else CORAL,
        "new": GOLD,
        "hold": "#91a4af" if on_dark else MUTED,
    }
    _text(draw, (x, y), label, size=size, bold=True, fill=colors[state], anchor=anchor)


def _draw_featured_team(canvas, draw, result, box):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=24, fill=PAPER)
    draw.rounded_rectangle((x1, y1, x1 + 12, y2), radius=6, fill=GREEN)
    _text(draw, (x1 + 38, y1 + 30), "COMMUNITY NO. 1", size=16, bold=True, fill=GREEN)
    _draw_movement(draw, result, x2 - 30, y1 + 41, anchor="rm", size=11)
    _text(draw, (x1 + 38, y1 + 82), "#1", size=63, bold=True, fill=INK)
    _paste_logo(canvas, result["team"].handle, (x2 - 242, y1 + 54, 210, 210), frame=False)
    _draw_fitted(draw, (x1 + 38, y2 - 76), _team_name(result["team"]), x2 - x1 - 76, size=38, min_size=24, bold=True, fill=INK)
    _text(draw, (x1 + 38, y2 - 35), "Top-ranked by r/CFB's human voters", size=14, fill=MUTED)


def _draw_chaser(canvas, draw, result, box):
    x1, y1, x2, y2 = box
    middle = (y1 + y2) / 2
    _text(draw, (x1 + 4, middle), f'#{result["rank"]}', size=24, bold=True, fill=MINT, anchor="lm")
    _paste_logo(canvas, result["team"].handle, (x1 + 64, y1 + 8, 52, 52), border="#d9e1e4")
    _draw_fitted(draw, (x1 + 136, middle), _team_name(result["team"]), x2 - x1 - 255, size=19, min_size=13, bold=True, fill=WHITE, anchor="lm")
    _draw_movement(draw, result, x2 - 18, middle, on_dark=True, anchor="rm", size=11)
    draw.line((x1, y2, x2, y2), fill="#29495a", width=1)


def _draw_ranked_row(canvas, draw, result, box):
    x1, y1, x2, y2 = box
    middle = (y1 + y2) / 2
    _text(draw, (x1 + 3, middle), result["rank"], size=17, bold=True, fill=GREEN, anchor="lm")
    _paste_logo(canvas, result["team"].handle, (x1 + 42, y1 + 5, 36, 36), frame=False)
    _draw_fitted(draw, (x1 + 92, middle), _team_name(result["team"]), x2 - x1 - 205, size=15, min_size=11, bold=True, fill=INK, anchor="lm")
    _draw_movement(draw, result, x2 - 8, middle, anchor="rm", size=10)
    draw.line((x1, y2, x2, y2), fill=LINE, width=1)


def _draw_momentum(canvas, draw, summary, box):
    x1, y1, x2, y2 = box
    _text(draw, (x1, y1), "BIGGEST MOVES", size=19, bold=True, fill=WHITE)
    _text(draw, (x1, y1 + 27), "Change in points per voter", size=12, fill="#91a4af")
    rows = (("RISING", summary["biggest_ppv_gain"], GREEN, "+"), ("FALLING", summary["biggest_ppv_loss"], CORAL, "−"))
    for index, (label, result, color, sign) in enumerate(rows):
        if not result:
            continue
        y = y1 + 58 + index * 67
        _paste_logo(canvas, result["team"].handle, (x1, y, 52, 52), border="#d9e1e4")
        _text(draw, (x1 + 70, y + 6), label, size=10, bold=True, fill=MINT if label == "RISING" else "#ff8a83")
        _draw_fitted(draw, (x1 + 70, y + 30), _team_name(result["team"]), 230, size=17, min_size=12, bold=True, fill=WHITE)
        _text(draw, (x2, y + 24), f'{sign}{abs(result["ppv_diff"]):.2f}', size=21, bold=True, fill=MINT if label == "RISING" else "#ff8a83", anchor="ra")
    if summary["dropped"]:
        _text(draw, (x1, y2 - 5), "OUT", size=10, bold=True, fill="#91a4af", anchor="ls")
        names = "  •  ".join(item["short_name"] for item in summary["dropped"])
        _draw_fitted(draw, (x1 + 42, y2 - 5), names, x2 - x1 - 42, size=12, min_size=9, bold=True, fill=WHITE, anchor="ls")


def _draw_polarizing(canvas, draw, summary, box):
    x1, y1, x2, y2 = box
    _text(draw, (x1, y1), "MOST DEBATED", size=19, bold=True, fill=WHITE)
    _text(draw, (x1, y1 + 27), "Largest ballot-to-ballot spread", size=12, fill="#91a4af")
    for index, item in enumerate(summary["polarizing"]):
        y = y1 + 58 + index * 53
        _paste_logo(canvas, item["handle"], (x1, y, 42, 42), border="#d9e1e4")
        _text(draw, (x1 + 58, y + 9), f'#{item["rank"]}', size=11, bold=True, fill=MINT)
        _draw_fitted(draw, (x1 + 93, y + 9), item["short_name"], 215, size=15, min_size=10, bold=True, fill=WHITE)
        _text(draw, (x2, y + 20), f'{item["coverage"]:.0%} ranked  •  spread {item["std_dev"]:.1f}', size=11, fill="#b6c4cc", anchor="ra")


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
        _draw_featured_team(canvas, draw, top25[0], (38, 158, 558, 500))
        draw.rounded_rectangle((582, 158, 1162, 500), radius=24, fill=SURFACE)
        _text(draw, (610, 182), "THE CHASERS", size=16, bold=True, fill=WHITE)
        _text(draw, (1134, 186), "WEEK-OVER-WEEK", size=10, bold=True, fill="#91a4af", anchor="ra")
        for index, result in enumerate(top25[1:5]):
            y1 = 216 + index * 67
            _draw_chaser(canvas, draw, result, (610, y1, 1134, y1 + 58))

        draw.rounded_rectangle((38, 524, 1162, 1112), radius=24, fill=PAPER)
        _text(draw, (66, 550), "FULL RANKING", size=20, bold=True, fill=NAVY)
        _text(draw, (1134, 554), "MOVEMENT SINCE LAST POLL", size=10, bold=True, fill=MUTED, anchor="ra")
        draw.line((600, 600, 600, 1085), fill=LINE, width=1)
        rows = top25[5:25]
        for index, result in enumerate(rows):
            column = index // 10
            row = index % 10
            x1 = 66 + column * 562
            y1 = 604 + row * 47
            _draw_ranked_row(canvas, draw, result, (x1, y1, x1 + 506, y1 + 42))

        draw.rounded_rectangle((38, 1136, 1162, 1418), radius=24, fill=SURFACE)
        draw.line((600, 1164, 600, 1390), fill="#29495a", width=1)
        _draw_momentum(canvas, draw, summary, (66, 1163, 562, 1388))
        _draw_polarizing(canvas, draw, summary, (632, 1163, 1134, 1388))
    else:
        _draw_empty_state(draw)

    _text(draw, (40, 1460), "POLL.REDDITCFB.COM", size=14, bold=True, fill=MINT, anchor="lm")
    _text(draw, (1160, 1460), "25 TEAMS  /  HUMAN BALLOTS  /  EVERY WEEK", size=11, fill="#91a4af", anchor="rm")
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
