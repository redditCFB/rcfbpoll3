from django.db import migrations


class Migration(migrations.Migration):
    dependencies = []

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE poll_poll ADD COLUMN required boolean NOT NULL DEFAULT FALSE;
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
            """,
            reverse_sql="ALTER TABLE poll_poll DROP COLUMN required;",
        ),
    ]
