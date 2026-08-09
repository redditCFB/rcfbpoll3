from django.db import migrations, models


def mark_required_polls(apps, schema_editor):
    Poll = apps.get_model('poll', 'Poll')
    Poll.objects.all().update(required=False)
    for year in Poll.objects.values_list('year', flat=True).distinct():
        week_four = Poll.objects.filter(year=year, week__iexact='week 4').order_by('-close_date').first()
        if week_four is not None:
            cutoff = week_four.close_date
        else:
            candidates = list(
                Poll.objects.filter(year=year).exclude(week__iexact='preseason').order_by('close_date')[:4]
            )
            cutoff = candidates[3].close_date if len(candidates) == 4 else None
        if cutoff is not None:
            Poll.objects.filter(year=year, close_date__gte=cutoff).update(required=True)


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
