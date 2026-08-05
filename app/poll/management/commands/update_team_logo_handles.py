from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from poll.models import Team


TEAM_HANDLE_RENAMES = {
    "arkansaspinebluff": "uapb",
    "centralconnecticutstate": "ccsu",
    "dixiestate": "utahtech",
    "eastcarolina": "ecu",
    "gramblingstate": "grambling",
    "kennesaw": "kennesawstate",
    "mcneesestate": "mcneese",
    "mississippivalleystate": "mvsu",
    "nccentral": "nccu",
    "nichollsstate": "nicholls",
    "southeastmissouristate": "southeastmissouri",
    "tennesseemartin": "utmartin",
    "virginiamilitaryinstitute": "vmi",
    "westernkentucky": "wku",
}


class Command(BaseCommand):
    help = "Update verified legacy team handles to their CDN logo handles."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and report the changes without updating the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        all_handles = set(TEAM_HANDLE_RENAMES) | set(TEAM_HANDLE_RENAMES.values())

        with transaction.atomic():
            teams_by_handle = defaultdict(list)
            for team in Team.objects.select_for_update().filter(handle__in=all_handles):
                teams_by_handle[team.handle].append(team)

            pending_updates = []
            already_migrated = []
            errors = []
            for legacy_handle, cdn_handle in TEAM_HANDLE_RENAMES.items():
                legacy_teams = teams_by_handle[legacy_handle]
                cdn_teams = teams_by_handle[cdn_handle]

                if len(legacy_teams) == 1 and not cdn_teams:
                    pending_updates.append((legacy_teams[0], cdn_handle))
                elif not legacy_teams and len(cdn_teams) == 1:
                    already_migrated.append((legacy_handle, cdn_handle))
                else:
                    errors.append(
                        f"{legacy_handle} -> {cdn_handle}: "
                        f"found {len(legacy_teams)} legacy row(s) and {len(cdn_teams)} CDN row(s)"
                    )

            if errors:
                raise CommandError(
                    "Team logo handle update aborted because the database does not match the expected state:\n"
                    + "\n".join(errors)
                )

            for team, cdn_handle in pending_updates:
                self.stdout.write(f"{team.handle} -> {cdn_handle}")

            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        f"Dry run: {len(pending_updates)} update(s), "
                        f"{len(already_migrated)} already applied."
                    )
                )
                return

            for team, cdn_handle in pending_updates:
                team.handle = cdn_handle
                team.save(update_fields=["handle"])

            self.stdout.write(
                self.style.SUCCESS(
                    f"Updated {len(pending_updates)} team handle(s); "
                    f"{len(already_migrated)} already applied."
                )
            )
