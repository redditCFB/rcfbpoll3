from datetime import timedelta
from importlib import import_module

from django.apps import apps
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone

from poll.models import Poll


class PollRequiredMigrationTests(TransactionTestCase):
    def create_poll(self, year, week, day):
        timestamp = timezone.now() + timedelta(days=day)
        return Poll.objects.create(
            year=year,
            week=week,
            open_date=timestamp,
            close_date=timestamp,
            publish_date=timestamp,
            ap_date=timestamp,
        )

    def apply_backfill(self):
        migration = import_module('poll.migrations.0002_poll_required')
        with connection.schema_editor() as schema_editor:
            migration.mark_required_polls(apps, schema_editor)

    def test_week_four_cutoff_is_case_insensitive_and_trims_whitespace(self):
        preseason = self.create_poll(2026, ' Preseason ', 0)
        week_one = self.create_poll(2026, 'week 1', 1)
        week_two = self.create_poll(2026, 'Week 2', 2)
        week_three = self.create_poll(2026, ' WEEK 3 ', 3)
        week_four = self.create_poll(2026, ' wEeK 4 ', 4)
        week_five = self.create_poll(2026, 'Week 5', 5)

        self.apply_backfill()

        self.assertFalse(Poll.objects.get(pk=preseason.pk).required)
        self.assertFalse(Poll.objects.get(pk=week_one.pk).required)
        self.assertFalse(Poll.objects.get(pk=week_two.pk).required)
        self.assertFalse(Poll.objects.get(pk=week_three.pk).required)
        self.assertTrue(Poll.objects.get(pk=week_four.pk).required)
        self.assertTrue(Poll.objects.get(pk=week_five.pk).required)

    def test_fallback_excludes_case_insensitive_trimmed_preseason(self):
        preseason = self.create_poll(2027, ' pReSeAsOn ', 0)
        first = self.create_poll(2027, 'First', 1)
        second = self.create_poll(2027, 'Second', 2)
        third = self.create_poll(2027, 'Third', 3)
        fourth = self.create_poll(2027, 'Fourth', 4)

        self.apply_backfill()

        self.assertFalse(Poll.objects.get(pk=preseason.pk).required)
        self.assertFalse(Poll.objects.get(pk=first.pk).required)
        self.assertFalse(Poll.objects.get(pk=second.pk).required)
        self.assertFalse(Poll.objects.get(pk=third.pk).required)
        self.assertTrue(Poll.objects.get(pk=fourth.pk).required)
