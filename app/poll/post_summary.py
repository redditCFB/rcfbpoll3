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


def _paste_logo(canvas, handle, box, border=GREEN):
    x, y, width, height = box
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((x, y, x + width, y + height), fill=WHITE, outline=border, width=3)
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
    draw.rounded_rectangle((x, y, x + width, y + 26), radius=13, fill=fill)
    _text(draw, (x + width / 2, y + 13), value, size=size, bold=True, fill=text_fill, anchor="mm")


def _movement_values(result):
    rank = result.get("rank_diff_str", "--")
    ppv = result.get("ppv_diff", 0)
    rank_color = GREEN if result.get("rank_diff", 0) > 0 else CORAL if result.get("rank_diff", 0) < 0 else MUTED
    rank_text = "NEW" if rank == "NEW" else rank
    ppv_color = GREEN if ppv > 0 else CORAL if ppv < 0 else MUTED
    return rank_text, rank_color, f"{ppv:+.2f} PPV", ppv_color


def _draw_movement_badges(draw, result, x, y, scale=1):
    rank_text, rank_color, ppv_text, ppv_color = _movement_values(result)
    _pill(draw, x, y, rank_text, rank_color, width=int(48 * scale), size=max(10, int(12 * scale)))
    _pill(draw, x + int(54 * scale), y, ppv_text, ppv_color, width=int(80 * scale), size=max(9, int(11 * scale)))


def _draw_top_team(canvas, draw, result, center_x, top_y, logo_size, name_size, movement_scale=1):
    _text(draw, (center_x, top_y - 8), f'#{result["rank"]}', size=30 if logo_size > 120 else 22, bold=True, fill=GOLD, anchor="ms")
    _paste_logo(canvas, result["team"].handle, (center_x - logo_size // 2, top_y, logo_size, logo_size), border=GOLD if result["rank"] == 1 else GREEN)
    _draw_fitted(draw, (center_x, top_y + logo_size + 16), result["team"].name, 250 if logo_size > 120 else 190, size=name_size, min_size=10, bold=True, anchor="ms", fill=WHITE)
    _text(draw, (center_x, top_y + logo_size + 42), f'{result["points"]:,} pts', size=14, fill=MINT, anchor="ms")
    _draw_movement_badges(draw, result, center_x - int(67 * movement_scale), top_y + logo_size + 55, movement_scale)


def _draw_chase_team(canvas, draw, result, box):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=22, fill=WHITE, outline=MINT, width=3)
    _paste_logo(canvas, result["team"].handle, (x1 + 14, y1 + 18, 70, 70))
    _text(draw, (x1 + 98, y1 + 28), f'#{result["rank"]}', size=18, bold=True, fill=GREEN)
    _draw_fitted(draw, (x1 + 98, y1 + 53), result["team"].name, x2 - x1 - 110, size=17, min_size=10, bold=True, fill=INK)
    _draw_movement_badges(draw, result, x1 + 14, y2 - 38, 0.85)


def _draw_polarizing(canvas, draw, summary, box):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=28, fill=LILAC)
    _text(draw, (x1 + 28, y1 + 28), "MOST POLARIZING", size=23, bold=True, fill=NAVY)
    _text(draw, (x1 + 28, y1 + 56), "Highest spread inside the Top 25", size=14, fill=MUTED)
    max_std = max((item["std_dev"] for item in summary["polarizing"]), default=1) or 1
    y = y1 + 92
    for item in summary["polarizing"]:
        _paste_logo(canvas, item["handle"], (x1 + 25, y, 52, 52), border=NAVY)
        _text(draw, (x1 + 88, y + 3), f'#{item["rank"]}', size=15, bold=True, fill=NAVY)
        _draw_fitted(draw, (x1 + 125, y + 5), item["name"], 175, size=17, min_size=10, bold=True, fill=INK)
        _text(draw, (x1 + 88, y + 30), f'spread {item["std_dev"]:.1f}  |  {item["coverage"]:.0%} ranked', size=12, fill=MUTED)
        bar_width = int(150 * item["std_dev"] / max_std)
        draw.rounded_rectangle((x2 - 180, y + 22, x2 - 30, y + 31), radius=5, fill="#d5c8e5")
        draw.rounded_rectangle((x2 - 180, y + 22, x2 - 180 + bar_width, y + 31), radius=5, fill=NAVY)
        y += 62


def _draw_momentum(canvas, draw, summary, box):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=28, fill=PEACH)
    _text(draw, (x1 + 28, y1 + 28), "MOMENTUM", size=23, bold=True, fill=NAVY)
    _text(draw, (x1 + 28, y1 + 56), "Biggest points-per-voter swings", size=14, fill=MUTED)
    for index, (label, result, color, sign) in enumerate((
        ("SURGE", summary["biggest_ppv_gain"], GREEN, "+"),
        ("SLIP", summary["biggest_ppv_loss"], CORAL, "-"),
    )):
        y = y1 + 90 + index * 75
        if not result:
            continue
        _paste_logo(canvas, result["team"].handle, (x1 + 25, y, 52, 52), border=color)
        _text(draw, (x1 + 90, y + 1), label, size=12, bold=True, fill=color)
        _draw_fitted(draw, (x1 + 90, y + 20), result["team"].name, 190, size=17, min_size=10, bold=True, fill=INK)
        _text(draw, (x2 - 35, y + 11), f'{sign}{abs(result["ppv_diff"]):.2f}', size=22, bold=True, fill=color, anchor="ra")
        _text(draw, (x2 - 35, y + 38), f'PPV  |  rank {result["rank_diff_str"]}', size=12, fill=MUTED, anchor="ra")
    dropped = summary["dropped"]
    if dropped:
        _text(draw, (x1 + 28, y2 - 29), "DROPPED", size=11, bold=True, fill=MUTED)
        x = x1 + 105
        for item in dropped:
            _paste_logo(canvas, item["handle"], (x, y2 - 43, 28, 28), border=CORAL)
            x += 38


def _draw_voter_signal(canvas, draw, summary, box):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=28, fill=NAVY)
    _text(draw, (x1 + 28, y1 + 25), "VOTER SIGNAL", size=23, bold=True, fill=MINT)
    _text(draw, (x1 + 28, y1 + 54), "Lower scores are closer to the aggregate poll", size=14, fill="#c7d4da")
    columns = (("MOST UNUSUAL", summary["most_unusual"], CORAL, x1 + 30), ("CLOSEST TO CONSENSUS", summary["least_unusual"], GOLD, x1 + 545))
    for title, voters, color, x in columns:
        _text(draw, (x, y1 + 92), title, size=17, bold=True, fill=color)
        for index, voter in enumerate(voters):
            y = y1 + 125 + index * 50
            draw.rounded_rectangle((x, y, x + 490, y + 36), radius=18, fill="#1b3445")
            _draw_fitted(draw, (x + 16, y + 18), voter["username"], 360, size=16, min_size=10, fill=WHITE, anchor="lm")
            _pill(draw, x + 406, y + 5, f'{voter["score"]:.1f}', color, width=68, size=12)


def render_post_summary(poll):
    summary = build_post_summary(poll)
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, WIDTH, 180), fill=GREEN)
    for offset in (0, 220, 540, 900):
        draw.ellipse((offset, -110, offset + 260, 150), fill="#169b74")

    site_logo = _load_site_logo()
    if site_logo:
        fitted = ImageOps.contain(site_logo, (92, 92))
        canvas.alpha_composite(fitted, (48, 34))
    _text(draw, (158, 47), "/r/CFB POLL", size=27, bold=True, fill=WHITE)
    _text(draw, (158, 82), summary["poll"], size=47, bold=True, fill=WHITE)

    hero = (38, 180, WIDTH - 38, 850)
    draw.rounded_rectangle(hero, radius=34, fill=NAVY)
    for y in range(230, 835, 80):
        draw.line((55, y, WIDTH - 55, y), fill="#1b3445", width=2)
    _text(draw, (70, 214), "THE TOP TEN", size=21, bold=True, fill=MINT)

    top10 = summary["top10"]
    if top10:
        _draw_top_team(canvas, draw, top10[0], WIDTH // 2, 248, 142, 28, 0.95)
    if len(top10) > 1:
        _draw_top_team(canvas, draw, top10[1], 300, 298, 104, 21, 0.82)
    if len(top10) > 2:
        _draw_top_team(canvas, draw, top10[2], 900, 298, 104, 21, 0.82)

    chase = top10[3:10]
    for row_index, row in enumerate((chase[:4], chase[4:])):
        tile_width = 250
        gap = 16
        row_width = len(row) * tile_width + max(0, len(row) - 1) * gap
        x = (WIDTH - row_width) // 2
        y = 510 + row_index * 135
        for result in row:
            _draw_chase_team(canvas, draw, result, (x, y, x + tile_width, y + 108))
            x += tile_width + gap

    _draw_polarizing(canvas, draw, summary, (38, 875, 580, 1150))
    _draw_momentum(canvas, draw, summary, (620, 875, 1162, 1150))
    _draw_voter_signal(canvas, draw, summary, (38, 1175, 1162, 1460))

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
