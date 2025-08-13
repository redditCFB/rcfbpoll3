from datetime import datetime, timedelta
from typing import Dict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from poll.models import UserRole, Ballot, Poll


class Command(BaseCommand):
    help = (
        "End-date UserRole rows based on ballot activity in a given season window.\n"
        "- Active VOTERs with < 7 polls: end_date set\n"
        "- Active PROVISIONALs with 0 polls: end_date set\n"
        "Counts are based on distinct Ballot.poll where Ballot.submission_date is not null,\n"
        "and Poll.open_date is within [--start, --end]."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--start",
            default="2024-08-01",
            help="Start date (YYYY-MM-DD) for the poll window. Default: 2024-08-01",
        )
        parser.add_argument(
            "--end",
            default="2025-01-31",
            help="End date (YYYY-MM-DD, inclusive) for the poll window. Default: 2025-01-31",
        )
        parser.add_argument(
            "--effective",
            default=None,
            help="Effective end_date to set (ISO datetime). Default: now()",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Do not write changes; just print what would happen.",
        )
        parser.add_argument(
            "--min-votes",
            type=int,
            default=7,
            help="Minimum distinct polls required for VOTERs to remain active. Default: 7",
        )

    def _parse_date(self, s: str) -> datetime:
        # Parse YYYY-MM-DD and make it timezone-aware at midnight
        dt = datetime.strptime(s, "%Y-%m-%d")
        return timezone.make_aware(dt)

    def _parse_effective(self, s: str | None) -> datetime:
        if not s:
            return timezone.now()
        # Accept YYYY-MM-DD or full ISO with time
        try:
            # Try full ISO first
            dt = datetime.fromisoformat(s)
        except ValueError:
            # Fallback to date-only
            dt = datetime.strptime(s, "%Y-%m-%d")
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt)
        return dt

    def handle(self, *args, **opts):
        start = self._parse_date(opts["start"])
        # Treat end as inclusive -> use < (end + 1 day)
        end_inclusive = self._parse_date(opts["end"]) + timedelta(days=1)
        effective_end = self._parse_effective(opts["effective"])
        dry_run = opts["dry_run"]
        min_votes = int(opts["min_votes"])

        self.stdout.write(
            f"Window: [{start.isoformat()} .. {end_inclusive.isoformat()}), "
            f"effective end_date: {effective_end.isoformat()}, dry_run={dry_run}"
        )

        # Polls in window (by open_date)
        poll_ids = list(
            Poll.objects.filter(open_date__gte=start, open_date__lt=end_inclusive)
            .values_list("id", flat=True)
        )
        if not poll_ids:
            self.stdout.write(self.style.WARNING("No polls in the given window."))
            return

        # Distinct-poll counts per user for that window
        # Only count submitted ballots
        counts_qs = (
            Ballot.objects.filter(poll_id__in=poll_ids, submission_date__isnull=False)
            .values("user_id")
            .annotate(n_polls=Count("poll", distinct=True))
        )
        # Map: user_id -> #distinct polls
        counts: Dict[int, int] = {row["user_id"]: row["n_polls"] for row in counts_qs}

        # Active roles
        active_voters = list(
            UserRole.objects.select_related("user")
            .filter(role=UserRole.Role.VOTER, end_date__isnull=True)
        )
        active_provisionals = list(
            UserRole.objects.select_related("user")
            .filter(role=UserRole.Role.PROVISIONAL, end_date__isnull=True)
        )

        self.stdout.write(f"Active voters: {len(active_voters)}")
        self.stdout.write(f"Active provisionals: {len(active_provisionals)}")

        voters_to_close = []
        provisionals_to_close = []

        for ur in active_voters:
            n = counts.get(ur.user_id, 0)
            if n < min_votes:
                voters_to_close.append((ur, n))

        for ur in active_provisionals:
            n = counts.get(ur.user_id, 0)
            if n == 0:
                provisionals_to_close.append((ur, n))

        self.stdout.write(self.style.NOTICE(f"VOTERs to close (< {min_votes}): {len(voters_to_close)}"))
        self.stdout.write(self.style.NOTICE(f"PROVISIONALs to close (== 0): {len(provisionals_to_close)}"))

        # Preview a few
        preview_cap = 15
        if voters_to_close:
            self.stdout.write("Examples (VOTER):")
            for ur, n in voters_to_close[:preview_cap]:
                self.stdout.write(f" - user_id={ur.user_id} username={ur.user.username!r} ballots={n}")
        if provisionals_to_close:
            self.stdout.write("Examples (PROVISIONAL):")
            for ur, n in provisionals_to_close[:preview_cap]:
                self.stdout.write(f" - user_id={ur.user_id} username={ur.user.username!r} ballots={n}")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run: no changes written."))
            return

        with transaction.atomic():
            # Update each role's end_date
            for ur, _ in voters_to_close:
                ur.end_date = effective_end
                ur.save(update_fields=["end_date"])
            for ur, _ in provisionals_to_close:
                ur.end_date = effective_end
                ur.save(update_fields=["end_date"])

        self.stdout.write(self.style.SUCCESS(
            f"Done. VOTER end-dated: {len(voters_to_close)}; PROVISIONAL end-dated: {len(provisionals_to_close)}"
        ))
