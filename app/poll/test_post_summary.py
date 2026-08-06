from datetime import timedelta
from unittest.mock import patch

from django.db import connection
from django.test import RequestFactory, TransactionTestCase
from django.utils import timezone
from PIL import Image

from poll import views
from poll.models import Ballot, BallotEntry, Poll, Result, ResultSet, Team, User


class PostSummaryImageTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.schema_editor() as schema_editor:
            for model in (Team, User, Poll, Ballot, BallotEntry, ResultSet, Result):
                schema_editor.create_model(model)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as schema_editor:
            for model in (Result, ResultSet, BallotEntry, Ballot, Poll, Team, User):
                schema_editor.delete_model(model)
        super().tearDownClass()

    def setUp(self):
        now = timezone.now()
        self.poll = Poll.objects.create(
            year=2026,
            week="Preseason",
            open_date=now - timedelta(days=10),
            close_date=now - timedelta(days=3),
            publish_date=now - timedelta(days=2),
            ap_date=now - timedelta(days=2),
        )
        self.user = User.objects.create(username="summary-voter")
        self.teams = [
            Team.objects.create(
                handle=f"team-{index}",
                name=f"Team {index}",
                conference="Test",
                division="FBS",
                use_for_ballot=True,
                short_name=f"Team {index}",
            )
            for index in range(1, 4)
        ]
        ballot = Ballot.objects.create(
            user=self.user,
            poll=self.poll,
            submission_date=now - timedelta(days=4),
            poll_type=Ballot.BallotType.HUMAN,
            user_type=1,
        )
        BallotEntry.objects.bulk_create([
            BallotEntry(ballot=ballot, team=team, rank=index)
            for index, team in enumerate(self.teams, start=1)
        ])

    def test_renders_valid_png_with_logo_fallbacks(self):
        with patch("poll.post_summary._load_logo", return_value=None):
            response = views.poll_post_summary(
                self._request(is_staff=True), self.poll.id
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        image = Image.open(__import__("io").BytesIO(response.content))
        self.assertEqual(image.size, (1200, 1500))

    def test_image_endpoint_requires_staff(self):
        response = views.poll_post_summary(
            self._request(is_staff=False), self.poll.id
        )

        self.assertEqual(response.status_code, 403)

    def _request(self, is_staff):
        request = RequestFactory().get(f"/poll_post/summary/{self.poll.id}.png")
        request.user = type(
            "FakeUser",
            (),
            {"is_staff": is_staff, "is_anonymous": not is_staff},
        )()
        return request
