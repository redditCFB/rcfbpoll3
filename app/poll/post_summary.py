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
BACKGROUND = "#f3f4f6"
INK = "#16202a"
MUTED = "#5d6872"
ACCENT = "#1f8a70"
CARD = "#ffffff"
BORDER = "#d6dbe0"


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


def _truncate(value, length):
    value = str(value)
    return value if len(value) <= length else value[: length - 1] + "…"


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

    most_agreed = sorted(result_rows, key=lambda row: row.std_dev)[:3]
    least_agreed = sorted(result_rows, key=lambda row: row.std_dev, reverse=True)[:3]
    biggest_rise = max(top25, key=lambda row: row["rank_diff"], default=None)
    biggest_fall = min(top25, key=lambda row: row["rank_diff"], default=None)

    return {
        "poll": str(poll),
        "voter_count": len(ballots),
        "top10": top10,
        "biggest_rise": biggest_rise,
        "biggest_fall": biggest_fall,
        "dropped": dropped[:3],
        "most_agreed": [
            _team_payload(row.team, std_dev=row.std_dev) for row in most_agreed
        ],
        "least_agreed": [
            _team_payload(row.team, std_dev=row.std_dev) for row in least_agreed
        ],
        "most_unusual": sorted(
            scored_ballots, key=lambda item: item["score"], reverse=True
        )[:3],
        "least_unusual": sorted(scored_ballots, key=lambda item: item["score"])[:3],
    }


@lru_cache(maxsize=256)
def _load_logo(handle):
    url = settings.TEAM_LOGO_URL_TEMPLATE.format(handle=handle)
    try:
        response = requests.get(url, timeout=(2, 4))
        response.raise_for_status()
        image = Image.open(BytesIO(response.content)).convert("RGBA")
        image.thumbnail((160, 160), Image.Resampling.LANCZOS)
        return image.copy()
    except (OSError, requests.RequestException):
        return None


def _paste_logo(canvas, handle, box):
    x, y, width, height = box
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((x, y, x + width, y + height), radius=width // 5, fill="#ffffff", outline=BORDER)
    logo = _load_logo(handle)
    if logo:
        fitted = ImageOps.contain(logo, (width - 18, height - 18))
        canvas.alpha_composite(fitted, (x + (width - fitted.width) // 2, y + (height - fitted.height) // 2))
    else:
        _text(draw, (x + width // 2, y + height // 2), handle[:3].upper(), size=24, bold=True, anchor="mm", fill=ACCENT)


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


def _draw_card(draw, box, title, subtitle=None):
    draw.rounded_rectangle(box, radius=18, fill=CARD, outline=BORDER, width=2)
    _text(draw, (box[0] + 22, box[1] + 20), title, size=22, bold=True, fill=ACCENT)
    if subtitle:
        _text(draw, (box[0] + 22, box[1] + 50), subtitle, size=15, fill=MUTED)


def _draw_team_metric(canvas, draw, team, label, y, x, width=0):
    _paste_logo(canvas, team["handle"] if isinstance(team, dict) else team.handle, (x, y, 52, 52))
    short_name = team["short_name"] if isinstance(team, dict) else _team_name(team)
    _text(draw, (x + 65, y + 3), _truncate(short_name, 18), size=19, bold=True)
    _text(draw, (x + 65, y + 29), label, size=15, fill=MUTED)


def _movement_label(result, kind):
    ppv = result.get("ppv_diff", 0)
    ppv_text = f'{ppv:+.2f} PPV'
    return f'{kind} {result["rank_diff_str"]} · {ppv_text}'


def _draw_pyramid_team(canvas, draw, result, box, name_size):
    x1, y1, x2, y2 = box
    compact = x2 - x1 < 200
    draw.rounded_rectangle(box, radius=15, fill=CARD, outline=BORDER, width=2)
    logo_size = 52 if compact else 64
    _paste_logo(canvas, result["team"].handle, (x1 + 8 if compact else x1 + 12, y1 + 18, logo_size, logo_size))
    text_x = x1 + 66 if compact else x1 + 88
    _text(draw, (text_x, y1 + 24), f'#{result["rank"]}', size=16 if compact else 18, bold=True, fill=ACCENT)
    _text(draw, (text_x, y1 + 47), _truncate(result["team"].short_name, 8 if compact else 15), size=name_size if not compact else 13, bold=True)
    stats = f'{result["points"]:,} pts' if compact else f'{result["points"]:,} pts · {result["first_place_votes"]} #1'
    _text(draw, (text_x, y1 + 78), stats, size=11 if compact else 13, fill=MUTED)


def render_post_summary(poll):
    summary = build_post_summary(poll)
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(canvas)

    site_logo = _load_site_logo()
    if site_logo:
        fitted = ImageOps.contain(site_logo, (68, 68))
        canvas.alpha_composite(fitted, (48, 35))
    _text(draw, (132, 48), "/r/CFB POLL", size=25, bold=True, fill=ACCENT)
    _text(draw, (132, 80), summary["poll"], size=46, bold=True)
    _text(draw, (WIDTH - 55, 61), f'{summary["voter_count"]} main ballots', size=19, fill=MUTED, anchor="ra")
    _text(draw, (132, 132), "A visual snapshot of the poll", size=20, fill=MUTED)

    pyramid = (45, 180, WIDTH - 45, 760)
    draw.rounded_rectangle(pyramid, radius=20, fill="#e8f2ef", outline="#b8d8ce", width=2)
    _text(draw, (75, 213), "THE TOP TEN", size=24, bold=True, fill=ACCENT)
    _text(draw, (WIDTH - 75, 218), "logos scale with rank", size=15, fill=MUTED, anchor="ra")

    rows = []
    cursor = 0
    for count in (1, 3, 6):
        rows.append(summary["top10"][cursor:cursor + count])
        cursor += count
    y = 265
    tier_specs = ((250, 120, 21, 12), (250, 110, 19, 10), (170, 95, 15, 8))
    for row_index, row in enumerate(rows):
        tile_width, tile_height, name_size, gap = tier_specs[row_index]
        row_width = len(row) * tile_width + max(0, len(row) - 1) * gap
        x = (WIDTH - row_width) // 2
        for result in row:
            _draw_pyramid_team(canvas, draw, result, (x, y, x + tile_width, y + tile_height), 21 if row_index < 2 else 18)
            x += tile_width + gap
        y += tile_height + 15

    card_y = 785
    card_gap = 22
    card_width = (WIDTH - 90 - card_gap) // 2
    left = (45, card_y, 45 + card_width, 1050)
    right = (45 + card_width + card_gap, card_y, WIDTH - 45, 1050)
    _draw_card(draw, left, "WHERE VOTERS DISAGREED", "Highest ranking spread")
    _draw_card(draw, right, "MOVEMENT", "Rank change + points per voter")

    y = card_y + 78
    for row in summary["least_agreed"]:
        _draw_team_metric(canvas, draw, row, f'disagreement σ {row["std_dev"]:.1f}', y, left[0] + 20)
        y += 55

    y = card_y + 78
    if summary["biggest_rise"]:
        rise = summary["biggest_rise"]
        _draw_team_metric(canvas, draw, rise["team"], _movement_label(rise, "rise"), y, right[0] + 20)
        y += 55
    if summary["biggest_fall"]:
        fall = summary["biggest_fall"]
        _draw_team_metric(canvas, draw, fall["team"], _movement_label(fall, "fall"), y, right[0] + 20)
        y += 55
    dropped = ", ".join(item["short_name"] for item in summary["dropped"])
    _text(draw, (right[0] + 20, y + 5), _truncate(f'Dropped: {dropped or "none"}', 34), size=15, fill=MUTED)

    footer_y = 1075
    _draw_card(draw, (45, footer_y, WIDTH - 45, HEIGHT - 45), "VOTER SIGNAL", "The ballots furthest from /r/CFB consensus")
    _text(draw, (70, footer_y + 78), "MOST UNUSUAL", size=18, bold=True, fill=INK)
    _text(draw, (440, footer_y + 78), "MOST TYPICAL", size=18, bold=True, fill=INK)
    for index in range(3):
        most = summary["most_unusual"][index] if index < len(summary["most_unusual"]) else None
        least = summary["least_unusual"][index] if index < len(summary["least_unusual"]) else None
        y = footer_y + 115 + index * 45
        if most:
            _text(draw, (70, y), f'{most["username"]}  {most["score"]:.1f}', size=16)
        if least:
            _text(draw, (440, y), f'{least["username"]}  {least["score"]:.1f}', size=16)

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
