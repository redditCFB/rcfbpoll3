from django.db import migrations, models


def mark_required_polls(apps, schema_editor):
    schema_editor.execute("""
        UPDATE poll_poll SET required = FALSE;
        WITH season_cutoff AS (
            SELECT seasons.year,
                COALESCE(
                    MAX(seasons.close_date) FILTER (WHERE lower(trim(seasons.week)) = 'week 4'),
                    (
                        SELECT candidate.close_date
                        FROM poll_poll AS candidate
                        WHERE candidate.year = seasons.year
                          AND lower(trim(candidate.week)) <> 'preseason'
                        ORDER BY candidate.close_date
                        OFFSET 3 LIMIT 1
                    )
                ) AS close_date
            FROM poll_poll AS seasons
            GROUP BY seasons.year
        )
        UPDATE poll_poll AS poll
        SET required = TRUE
        FROM season_cutoff
        WHERE poll.year = season_cutoff.year
          AND poll.close_date >= season_cutoff.close_date;
    """)


def unmark_required_polls(apps, schema_editor):
    apps.get_model('poll', 'Poll').objects.all().update(required=False)


class Migration(migrations.Migration):
    dependencies = [('poll', '0001_initial')]

    operations = [
        migrations.AddField(
            model_name='poll',
            name='required',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(mark_required_polls, unmark_required_polls),
    ]
