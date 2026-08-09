from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('poll', '0002_poll_required')]

    operations = [
        migrations.CreateModel(
            name='RedditAccount',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('username', models.CharField(max_length=64, unique=True)),
                ('encrypted_refresh_token', models.TextField(editable=False)),
                ('granted_scopes', models.JSONField(default=list)),
                ('authorized_at', models.DateTimeField(blank=True, null=True)),
                ('last_verified_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='RedditRoleAssignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[('NOTIFICATIONS', 'Notifications'), ('APPLICATION_REVIEW', 'Application review'), ('RESULTS_PUBLISHER', 'Results publisher')], max_length=32, unique=True)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='role_assignments', to='poll.redditaccount')),
            ],
            options={'ordering': ('role',)},
        ),
    ]
