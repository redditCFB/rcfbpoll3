from django.db import models
from django.utils import timezone


class User(models.Model):
    username = models.CharField(max_length=32)
    primary_affiliation = models.ForeignKey('Team', blank=True, null=True, on_delete=models.SET_NULL)

    def __str__(self):
        return self.username

    @property
    def is_voter(self):
        return UserRole.objects.filter(
            user=self, role=UserRole.Role.VOTER, end_date__isnull=True
        )

    @property
    def is_provisional_voter(self):
        return UserRole.objects.filter(
            user=self, role=UserRole.Role.PROVISIONAL, end_date__isnull=True
        )


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
    user = models.ForeignKey('User', on_delete=models.CASCADE)
    submission_date = models.DateTimeField()


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
    week = models.CharField(40)
    open_date = models.DateTimeField()
    close_date = models.DateTimeField()
    publish_date = models.DateTimeField()
    last_week = models.ForeignKey('Poll', blank=True, null=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ('publish_date',)

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
    overall_rationale = models.TextField(blank=True)

    def submit(self):
        self.submission_date = timezone.now()
        self.save()

    def retract(self):
        self.submission_date = None
        self.save()

    @property
    def is_submitted(self):
        return self.submission_date is not None

    def __str__(self):
        return '%s %s' % (self.poll, self.user)


class BallotEntry(models.Model):
    ballot = models.ForeignKey('Ballot', on_delete=models.CASCADE)
    team = models.ForeignKey('Team', on_delete=models.PROTECT)
    rank = models.IntegerField()
    rationale = models.TextField(blank=True)

    def __str__(self):
        return '%s %d %s' % (self.ballot, self.rank, self.team)


class ResultSet(models.Model):
    poll = models.ForeignKey('Poll', on_delete=models.CASCADE)
    human = models.BooleanField(default=True)
    computer = models.BooleanField(default=True)
    hybrid = models.BooleanField(default=True)
    main = models.BooleanField(default=True)
    provisional = models.BooleanField(default=False)
    before_ap = models.BooleanField(default=True)
    after_ap = models.BooleanField(default=True)


class Result(models.Model):
    result_set = models.ForeignKey('ResultSet', on_delete=models.CASCADE)
    team = models.ForeignKey('Team', on_delete=models.PROTECT)
    rank = models.IntegerField()
    first_place_votes = models.IntegerField()
    points = models.IntegerField()
    points_per_voter = models.FloatField()
    std_dev = models.FloatField()
