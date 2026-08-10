from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('poll', '0003_reddit_accounts'),
    ]
    operations = [
        migrations.AddField(
            model_name='provisionaluserapplication',
            name='decision_source',
            field=models.CharField(
                blank=True,
                choices=[('MANUAL', 'Manual'), ('AUTOMATIC', 'Automatic')],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='provisionaluserapplication',
            name='screening_flags',
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name='provisionaluserapplication',
            name='screened_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
            ),
        ),
    ]
