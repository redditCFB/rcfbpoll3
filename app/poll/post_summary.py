from functools import lru_cache
from io import BytesIO

import requests
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .models import Ballot, UserRole
from .utils import SCORE_OFFSET, MIN_OUTLIER_FACTOR, get_result_set, get_results_comparison


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


def _analysis_score(ballot, results_dict, top25):
    total_score = 0
    ranked_team_ids = set()
    for entry in ballot.ballotentry_set.all():
        result = results_dict.get(entry.team_id)
        if result:
            score = (26 - entry.rank - result["ppv"]) / max(
                MIN_OUTLIER_FACTOR, result["std_dev"]
            )
            if score > 0:
                score = max(0, score - SCORE_OFFSET)
            else:
                score = min(0, score + SCORE_OFFSET)
        else:
            score = (26 - entry.rank) / MIN_OUTLIER_FACTOR - SCORE_OFFSET
        total_score += abs(score)
        ranked_team_ids.add(entry.team_id)

    for team_id, result in top25.items():
        if team_id not in ranked_team_ids:
            score = max(0, result["ppv"] / max(MIN_OUTLIER_FACTOR, result["std_dev"]) - SCORE_OFFSET)
            total_score += score

    return total_score


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
            "score": _analysis_score(ballot, results_dict, top25_dict),
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


def _draw_card(draw, box, title):
    draw.rounded_rectangle(box, radius=18, fill=CARD, outline=BORDER, width=2)
    _text(draw, (box[0] + 22, box[1] + 24), title, size=22, bold=True, fill=ACCENT)


def _draw_team_metric(canvas, draw, team, label, y, x):
    _paste_logo(canvas, team["handle"] if isinstance(team, dict) else team.handle, (x, y, 58, 58))
    short_name = team["short_name"] if isinstance(team, dict) else _team_name(team)
    _text(draw, (x + 72, y + 7), _truncate(short_name, 18), size=20, bold=True)
    _text(draw, (x + 72, y + 35), label, size=16, fill=MUTED)


def render_post_summary(poll):
    summary = build_post_summary(poll)
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(canvas)

    _text(draw, (60, 54), "/r/CFB POLL", size=26, bold=True, fill=ACCENT)
    _text(draw, (60, 94), summary["poll"], size=52, bold=True)
    _text(draw, (WIDTH - 60, 72), f'{summary["voter_count"]} main ballots', size=20, fill=MUTED, anchor="ra")
    _text(draw, (60, 144), "Top ten, movement, and where voters disagreed", size=22, fill=MUTED)

    table = (45, 185, WIDTH - 45, 980)
    draw.rounded_rectangle(table, radius=20, fill=CARD, outline=BORDER, width=2)
    _text(draw, (75, 220), "THE POLL AT A GLANCE", size=24, bold=True, fill=ACCENT)

    row_y = 265
    for result in summary["top10"]:
        _paste_logo(canvas, result["team"].handle, (72, row_y - 5, 58, 58))
        _text(draw, (54, row_y + 25), result["rank"], size=24, bold=True, anchor="rm")
        _text(draw, (150, row_y + 4), _truncate(result["team"].short_name, 25), size=25, bold=True)
        _text(draw, (150, row_y + 37), f'{result["points"]:,} points · {result["first_place_votes"]} #1 votes', size=16, fill=MUTED)
        movement = result["rank_diff_str"]
        movement_fill = ACCENT if result["rank_diff"] > 0 else "#b44747" if result["rank_diff"] < 0 else MUTED
        _text(draw, (850, row_y + 25), movement, size=24, bold=True, fill=movement_fill, anchor="mm")
        _text(draw, (1110, row_y + 25), f'#{result["rank"]}', size=24, bold=True, anchor="rm")
        row_y += 68

    card_y = 1010
    card_gap = 22
    card_width = (WIDTH - 90 - card_gap) // 2
    left = (45, card_y, 45 + card_width, 1240)
    right = (45 + card_width + card_gap, card_y, WIDTH - 45, 1240)
    _draw_card(draw, left, "CONSENSUS")
    _draw_card(draw, right, "MOVEMENT")

    y = card_y + 68
    for row in summary["most_agreed"]:
        _draw_team_metric(canvas, draw, row, f'agreement σ {row["std_dev"]:.1f}', y, left[0] + 20)
        y += 55

    y = card_y + 68
    if summary["biggest_rise"]:
        rise = summary["biggest_rise"]
        _draw_team_metric(canvas, draw, rise["team"], f'biggest rise · {rise["rank_diff_str"]}', y, right[0] + 20)
        y += 55
    if summary["biggest_fall"]:
        fall = summary["biggest_fall"]
        _draw_team_metric(canvas, draw, fall["team"], f'biggest fall · {fall["rank_diff_str"]}', y, right[0] + 20)
        y += 55
    dropped = ", ".join(item["short_name"] for item in summary["dropped"])
    _text(draw, (right[0] + 20, y + 8), _truncate(f'Dropped: {dropped or "none"}', 34), size=16, fill=MUTED)

    footer_y = 1275
    _draw_card(draw, (45, footer_y, WIDTH - 45, HEIGHT - 45), "VOTER SIGNAL")
    _text(draw, (70, footer_y + 68), "Most unusual ballots", size=20, bold=True)
    _text(draw, (440, footer_y + 68), "Least unusual ballots", size=20, bold=True)
    for index in range(3):
        most = summary["most_unusual"][index] if index < len(summary["most_unusual"]) else None
        least = summary["least_unusual"][index] if index < len(summary["least_unusual"]) else None
        y = footer_y + 112 + index * 48
        if most:
            _text(draw, (70, y), f'{most["username"]}  {most["score"]:.1f}', size=17)
        if least:
            _text(draw, (440, y), f'{least["username"]}  {least["score"]:.1f}', size=17)

    output = BytesIO()
    canvas.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()
