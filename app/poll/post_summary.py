from functools import lru_cache
from io import BytesIO
import os
import tempfile
from pathlib import Path

import requests
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .models import Ballot, UserRole
from .utils import get_outlier_score, get_result_set, get_result_set_record, get_results_comparison


WIDTH = 1200
HEIGHT = 1500
PAPER = "#f5f1e8"
NAVY = "#102333"
GREEN = "#118562"
MINT = "#a9dfc8"
GOLD = "#f1be4b"
CORAL = "#ef6b63"
INK = "#102333"
MUTED = "#52616e"
WHITE = "#ffffff"
LILAC = "#e8ddf5"
PEACH = "#ffe0b2"


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
    return current_size


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
    result_set = get_result_set(poll)
    result_rows = list(result_set)
    top25 = [row for row in comparison if row["rank"] <= 25]
    top10 = top25[:10]
    ballots = list(
        Ballot.objects.filter(
            poll=poll,
            submission_date__isnull=False,
            user_type=UserRole.Role.VOTER,
        )
        .select_related("user")
        .prefetch_related("ballotentry_set__team")
    )

    results_dict = {
        row.team_id: {
            "ppv": row.points_per_voter,
            "std_dev": row.std_dev,
            "rank": row.rank,
        }
        for row in result_rows
    }
    top25_dict = {
        team_id: value for team_id, value in results_dict.items() if value["rank"] <= 25
    }
    scored_ballots = [
        {
            "username": ballot.user.username,
            "ballot_id": ballot.id,
            "score": get_outlier_score(ballot.ballotentry_set.all(), results_dict, top25_dict),
        }
        for ballot in ballots
    ]

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
            votes=row["votes"],
            coverage=row["votes"] / len(ballots) if ballots else 0,
        )
        for row in polarizing
    ]
    biggest_rise = max(top25, key=lambda row: row["rank_diff"], default=None)
    biggest_fall = min(top25, key=lambda row: row["rank_diff"], default=None)
    biggest_ppv_gain = max(top25, key=lambda row: row["ppv_diff"], default=None)
    biggest_ppv_loss = min(top25, key=lambda row: row["ppv_diff"], default=None)

    return {
        "poll": str(poll),
        "voter_count": len(ballots),
        "top25": top25,
        "top10": top10,
        "biggest_rise": biggest_rise,
        "biggest_fall": biggest_fall,
        "biggest_ppv_gain": biggest_ppv_gain,
        "biggest_ppv_loss": biggest_ppv_loss,
        "dropped": dropped[:3],
        "polarizing": polarizing,
        "most_unusual": sorted(scored_ballots, key=lambda item: item["score"], reverse=True)[:3],
        "least_unusual": sorted(scored_ballots, key=lambda item: item["score"])[:3],
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


def _pill(draw, x, y, value, fill, text_fill=WHITE, width=None, size=13):
    value = str(value)
    width = width or max(42, draw.textbbox((0, 0), value, font=_font(size, True))[2] + 20)
    draw.rounded_rectangle((x, y, x + width, y + 30), radius=7, fill=fill)
    _text(draw, (x + width / 2, y + 15), value, size=size, bold=True, fill=text_fill, anchor="mm")


def _draw_rank_movement(draw, result, x, y, size=25):
    change = result.get("rank_diff", 0)
    rank_text = result.get("rank_diff_str", "--")
    color = GREEN if change > 0 else CORAL if change < 0 else MUTED
    if rank_text == "NEW":
        _text(draw, (x, y), "NEW", size=size - 3, bold=True, fill=GOLD, anchor="lm")
        return
    if change == 0:
        _text(draw, (x, y), "—", size=size, bold=True, fill=MUTED, anchor="lm")
        return
    # rank_diff is previous rank minus current rank: positive means the
    # numeric rank decreased, which is an upward improvement.
    direction = 1 if change > 0 else -1
    draw.polygon(
        ((x, y + direction * 6), (x + 12, y - direction * 7), (x + 24, y + direction * 6)),
        fill=color,
    )
    _text(draw, (x + 32, y), str(abs(change)), size=size, bold=True, fill=color, anchor="lm")


def _draw_top_team(canvas, draw, result, center_x, top_y, logo_size, name_size, rank_size):
    _text(draw, (center_x, top_y - 18), f'#{result["rank"]}', size=rank_size, bold=True, fill=GREEN, anchor="ms")
    _paste_logo(canvas, result["team"].handle, (center_x - logo_size // 2, top_y, logo_size, logo_size), border=GOLD if result["rank"] == 1 else GREEN, frame=False)
    _draw_rank_movement(draw, result, center_x + logo_size // 2 + 18, top_y + logo_size // 2, size=27 if logo_size > 150 else 24)


def _draw_team_tile(canvas, draw, result, box, logo_size, show_rank=True, movement=True, frame=False):
    x1, y1, x2, y2 = box
    if frame:
        draw.rounded_rectangle(box, radius=18, fill=WHITE, outline=MINT, width=3)
    logo_x = x1 + 14
    logo_y = y1 + (28 if show_rank else (y2 - y1 - logo_size) // 2)
    if show_rank:
        _text(draw, (logo_x + logo_size // 2, y1 + 10), f'#{result["rank"]}', size=20 if logo_size > 90 else 16, bold=True, fill=MINT, anchor="ms")
    _paste_logo(canvas, result["team"].handle, (logo_x, logo_y, logo_size, logo_size), border=GREEN, frame=frame)
    if movement:
        _draw_rank_movement(draw, result, logo_x + logo_size + 25, logo_y + logo_size // 2, size=27 if logo_size > 90 else 23)


def _draw_polarizing(canvas, draw, summary, box):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=28, fill=LILAC)
    _text(draw, (x1 + 28, y1 + 28), "MOST POLARIZING", size=23, bold=True, fill=NAVY)
    _text(draw, (x1 + 28, y1 + 56), "Highest spread inside the Top 25", size=14, fill=MUTED)
    max_std = max((item["std_dev"] for item in summary["polarizing"]), default=1) or 1
    y = y1 + 80
    for item in summary["polarizing"]:
        _paste_logo(canvas, item["handle"], (x1 + 25, y - 4, 66, 66), border=NAVY)
        _text(draw, (x1 + 105, y + 2), f'#{item["rank"]}', size=16, bold=True, fill=NAVY)
        _draw_fitted(draw, (x1 + 145, y + 4), item["short_name"], 175, size=17, min_size=12, bold=True, fill=INK)
        _text(draw, (x1 + 105, y + 31), f'spread {item["std_dev"]:.1f}  |  {item["coverage"]:.0%} ranked', size=13, fill=MUTED)
        bar_width = int(150 * item["std_dev"] / max_std)
        draw.rounded_rectangle((x2 - 180, y + 25, x2 - 30, y + 36), radius=5, fill="#d5c8e5")
        draw.rounded_rectangle((x2 - 180, y + 25, x2 - 180 + bar_width, y + 36), radius=5, fill=NAVY)
        y += 58


def _draw_momentum(canvas, draw, summary, box):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=28, fill=PEACH)
    _text(draw, (x1 + 28, y1 + 28), "MOMENTUM", size=23, bold=True, fill=NAVY)
    _text(draw, (x1 + 28, y1 + 56), "Biggest points-per-voter swings", size=14, fill=MUTED)
    for index, (label, result, color, sign) in enumerate((
        ("SURGE", summary["biggest_ppv_gain"], GREEN, "+"),
        ("SLIP", summary["biggest_ppv_loss"], CORAL, "-"),
    )):
        y = y1 + 90 + index * 65
        if not result:
            continue
        _paste_logo(canvas, result["team"].handle, (x1 + 25, y - 5, 66, 66), border=color)
        _text(draw, (x1 + 105, y + 1), label, size=13, bold=True, fill=color)
        _draw_fitted(draw, (x1 + 105, y + 22), _team_name(result["team"]), 190, size=18, min_size=13, bold=True, fill=INK)
        _text(draw, (x2 - 35, y + 11), f'{sign}{abs(result["ppv_diff"]):.2f}', size=23, bold=True, fill=color, anchor="ra")
        _text(draw, (x2 - 35, y + 40), f'PPV  |  rank {result["rank_diff_str"]}', size=13, fill=MUTED, anchor="ra")
    dropped = summary["dropped"]
    if dropped:
        _text(draw, (x1 + 28, y2 - 31), "DROPPED", size=13, bold=True, fill=MUTED)
        x = x1 + 115
        for item in dropped:
            _paste_logo(canvas, item["handle"], (x, y2 - 52, 46, 46), border=CORAL)
            x += 58


def _draw_voter_signal(canvas, draw, summary, box):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=28, fill=NAVY)
    _text(draw, (x1 + 28, y1 + 25), "VOTER SIGNAL", size=23, bold=True, fill=MINT)
    _text(draw, (x1 + 28, y1 + 54), "Lower scores are closer to the aggregate poll", size=14, fill="#c7d4da")
    columns = (("MOST UNUSUAL", summary["most_unusual"], CORAL, x1 + 30), ("CLOSEST TO CONSENSUS", summary["least_unusual"], GOLD, x1 + 545))
    for title, voters, color, x in columns:
        _text(draw, (x, y1 + 92), title, size=17, bold=True, fill=color)
        for index, voter in enumerate(voters):
            y = y1 + 108 + index * 38
            draw.rounded_rectangle((x, y, x + 490, y + 30), radius=15, fill="#1b3445")
            _draw_fitted(draw, (x + 16, y + 18), voter["username"], 360, size=16, min_size=10, fill=WHITE, anchor="lm")
            _pill(draw, x + 406, y + 2, f'{voter["score"]:.1f}', color, width=68, size=12)


def render_post_summary(poll):
    summary = build_post_summary(poll)
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, WIDTH, 125), fill=GREEN)
    for offset in (0, 220, 540, 900):
        draw.ellipse((offset, -140, offset + 250, 110), fill="#169b74")

    site_logo = _load_site_logo()
    if site_logo:
        fitted = ImageOps.contain(site_logo, (78, 78))
        canvas.alpha_composite(fitted, (46, 22))
    _text(draw, (142, 32), "/r/CFB POLL", size=25, bold=True, fill=WHITE)
    _text(draw, (142, 63), summary["poll"], size=42, bold=True, fill=WHITE)

    hero = (38, 125, WIDTH - 38, 925)
    draw.rounded_rectangle(hero, radius=34, fill=NAVY)
    for y in range(175, 910, 80):
        draw.line((55, y, WIDTH - 55, y), fill="#1b3445", width=2)

    top25 = summary["top25"]
    if top25:
        _draw_top_team(canvas, draw, top25[0], WIDTH // 2, 218, 180, 27, 31)
    if len(top25) > 1:
        _draw_top_team(canvas, draw, top25[1], 300, 300, 132, 21, 23)
    if len(top25) > 2:
        _draw_top_team(canvas, draw, top25[2], 900, 300, 132, 21, 23)

    for index, result in enumerate(top25[3:8]):
        x = 55 + index * 220
        _draw_team_tile(canvas, draw, result, (x, 475, x + 210, 610), 102, show_rank=True, movement=True, frame=False)

    for index, result in enumerate(top25[8:15]):
        x = 55 + index * 158
        _draw_team_tile(canvas, draw, result, (x, 635, x + 148, 750), 84, show_rank=True, movement=True, frame=False)

    for index, result in enumerate(top25[15:25]):
        x = 50 + index * 111
        _draw_team_tile(canvas, draw, result, (x, 775, x + 104, 900), 88, show_rank=True, movement=False, frame=False)

    _draw_polarizing(canvas, draw, summary, (38, 940, 580, 1215))
    _draw_momentum(canvas, draw, summary, (620, 940, 1162, 1215))
    _draw_voter_signal(canvas, draw, summary, (38, 1220, 1162, 1460))

    _text(draw, (WIDTH // 2, 1480), "For full results, visit poll.redditcfb.com", size=13, fill=MUTED, anchor="mm")
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
