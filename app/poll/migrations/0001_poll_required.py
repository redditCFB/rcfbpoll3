from django.db import migrations


class Migration(migrations.Migration):
    dependencies = []

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE poll_poll ADD COLUMN required boolean NOT NULL DEFAULT FALSE;
                UPDATE poll_poll
                SET required = week ~* '^\\s*week\\s+([4-9]|[1-9][0-9]+)\\s*$';
            """,
            reverse_sql="ALTER TABLE poll_poll DROP COLUMN required;",
        ),
    ]
