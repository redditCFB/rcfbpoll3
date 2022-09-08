from django.contrib import admin
from django.db import models
from django.utils import timezone


class User(models.Model):
    username = models.CharField(max_length=32)
    primary_affiliation = models.ForeignKey('Team', blank=True, null=True, on_delete=models.SET_NULL)
    about_me = models.TextField(blank=True)
    methodology = models.TextField(blank=True)

    def __str__(self):
        return self.username

    @property
    @admin.display(boolean=True, description='Voter?')
    def is_voter(self):
        return UserRole.objects.filter(
            user=self, role=UserRole.Role.VOTER, end_date__isnull=True
        ).exists()

    @property
    @admin.display(boolean=True, description='Provisional?')
    def is_provisional_voter(self):
        return UserRole.objects.filter(
            user=self, role=UserRole.Role.PROVISIONAL, end_date__isnull=True
        ).exists()


class UserRole(models.Model):
    class Role(models.IntegerChoices):
        VOTER = 1, "Voter"
        PROVISIONAL = 2, "Provisional Voter"

    user = models.ForeignKey('User', on_delete=models.CASCADE)
    role = models.IntegerField(choices=Role.choices)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField(blank=True, null=True)


class UserSecondaryAffiliation(models.Model):
    user = models.ForeignKey('User', on_delete=models.CASCADE)
    team = models.ForeignKey('Team', on_delete=models.CASCADE)


class ProvisionalUserApplication(models.Model):
    class Status(models.IntegerChoices):
        OPEN = 1, "Open"
        ACCEPTED = 2, "Accepted"
        REJECTED = 3, "Rejected"

    user = models.ForeignKey('User', on_delete=models.CASCADE)
    submission_date = models.DateTimeField()
    status = models.IntegerField(choices=Status.choices)

    @admin.display(description='User Page')
    def user_page(self):
        return 'https://reddit.com/user/%s/' % self.user.username


class Team(models.Model):
    handle = models.CharField(max_length=60)
    name = models.CharField(max_length=120)
    conference = models.CharField(max_length=60)
    division = models.CharField(max_length=50)
    use_for_ballot = models.BooleanField()
    short_name = models.CharField(max_length=60)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name


class Poll(models.Model):
    year = models.IntegerField()
    week = models.CharField(max_length=40)
    open_date = models.DateTimeField()
    close_date = models.DateTimeField()
    publish_date = models.DateTimeField()
    ap_date = models.DateTimeField()
    last_week = models.ForeignKey('Poll', blank=True, null=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ('publish_date',)
        indexes = [
            models.Index(fields=['close_date']),
            models.Index(fields=['publish_date'])
        ]

    def __str__(self):
        return '%d %s' % (self.year, self.week)

    @property
    def is_open(self):
        return self.open_date < timezone.now() < self.close_date

    @property
    def is_closed(self):
        return self.close_date < timezone.now()

    @property
    def is_published(self):
        return self.publish_date < timezone.now()


class Ballot(models.Model):
    class BallotType(models.IntegerChoices):
        HUMAN = 1, 'Human'
        COMPUTER = 2, 'Computer'
        HYBRID = 3, 'Hybrid'

    user = models.ForeignKey('User', on_delete=models.PROTECT)
    poll = models.ForeignKey('Poll', on_delete=models.CASCADE)
    submission_date = models.DateTimeField(blank=True, null=True)
    poll_type = models.IntegerField(choices=BallotType.choices, blank=True, null=True)
    user_type = models.IntegerField(choices=UserRole.Role.choices)
    overall_rationale = models.TextField(blank=True)

    def submit(self):
        self.submission_date = timezone.now()
        self.save()

    def retract(self):
        self.submission_date = None
        self.save()

    @property
    @admin.display(boolean=True, description='Submitted?')
    def is_submitted(self):
        return self.submission_date is not None

    def __str__(self):
        return '%s %s' % (self.poll, self.user)

    def get_entries(self):
        return BallotEntry.objects.filter(ballot=self).order_by('rank')


class BallotEntry(models.Model):
    ballot = models.ForeignKey('Ballot', on_delete=models.CASCADE)
    team = models.ForeignKey('Team', on_delete=models.PROTECT)
    rank = models.IntegerField()
    rationale = models.TextField(blank=True)

    @property
    def points(self):
        return 26 - self.rank

    def __str__(self):
        return '%s %d %s' % (self.ballot, self.rank, self.team)


class ResultSet(models.Model):
    poll = models.ForeignKey('Poll', on_delete=models.CASCADE)
    time_calculated = models.DateTimeField()
    human = models.BooleanField(default=True)
    computer = models.BooleanField(default=True)
    hybrid = models.BooleanField(default=True)
    main = models.BooleanField(default=True)
    provisional = models.BooleanField(default=False)
    before_ap = models.BooleanField(default=True)
    after_ap = models.BooleanField(default=True)

    def needs_update(self):
        needs_update = True
        if self.time_calculated > self.poll.publish_date:
            needs_update = False
        else:
            ballots = self._get_ballots()
            last_submission = ballots.aggregate(models.Max('submission_date'))['submission_date__max']
            if last_submission < self.time_calculated:
                needs_update = False
        return needs_update

    def update(self):
        Result.objects.filter(result_set=self).delete()
        ballots = self._get_ballots()
        entries = BallotEntry.objects.filter(ballot__in=ballots)
        calculated_results = entries.values('team').annotate(
            total_points=models.Count('rank') * 26 - models.Sum('rank'),
            std_dev=models.StdDev('rank'),
            votes=models.Count('rank'),
            first_place_votes=models.Count('rank', filter=models.Q(rank=1))
        ).order_by('-total_points')
        results = []
        for i, team_results in enumerate(calculated_results):
            ppv = team_results['total_points'] / ballots.count()
            votes = team_results['votes']
            results.append(
                Result(
                    result_set=self,
                    team=Team.objects.get(pk=team_results['team']),
                    rank=i + 1 if i == 0 or team_results['total_points'] != results[i - 1].points else results[i - 1].rank,
                    first_place_votes=team_results['first_place_votes'],
                    points=team_results['total_points'],
                    points_per_voter=ppv,
                    std_dev=(team_results['std_dev'] * votes + ppv * (ballots.count() - votes)) / ballots.count(),
                    votes=votes
                )
            )
        Result.objects.bulk_create(results)

        self.time_calculated = timezone.now()
        self.save()
        return self.results()

    def results(self):
        return Result.objects.filter(result_set=self).order_by('rank')

    def _get_ballots(self):
        types = []
        if self.human:
            types.append(Ballot.BallotType.HUMAN)
        if self.computer:
            types.append(Ballot.BallotType.COMPUTER)
        if self.hybrid:
            types.append(Ballot.BallotType.HYBRID)

        ballots = Ballot.objects.filter(poll=self.poll, poll_type__in=types, submission_date__isnull=False)

        if not self.before_ap:
            ballots = ballots.exclude(submission_date__lte=self.poll.ap_date)
        if not self.after_ap:
            ballots = ballots.exclude(submission_date__gt=self.poll.ap_date)

        if not self.main:
            ballots = ballots.exclude(user_type=UserRole.Role.VOTER)
        if not self.provisional:
            ballots = ballots.exclude(user_type=UserRole.Role.PROVISIONAL)

        return ballots


class Result(models.Model):
    result_set = models.ForeignKey('ResultSet', on_delete=models.CASCADE)
    team = models.ForeignKey('Team', on_delete=models.PROTECT)
    rank = models.IntegerField()
    first_place_votes = models.IntegerField()
    points = models.IntegerField()
    points_per_voter = models.FloatField()
    std_dev = models.FloatField()
    votes = models.IntegerField()


class AboutPage(models.Model):
    page = models.CharField(max_length=64)
    text = models.TextField()

    def __str__(self):
        return self.page
