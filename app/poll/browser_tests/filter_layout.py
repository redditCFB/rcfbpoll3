from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone
from playwright.sync_api import sync_playwright

from poll.models import Ballot, BallotEntry, Poll, Team, User, UserRole


class PollFilterLayoutBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        now = timezone.now()
        self.poll = Poll.objects.create(
            year=now.year,
            week='Browser layout test',
            open_date=now - timedelta(days=2),
            close_date=now + timedelta(days=2),
            publish_date=now - timedelta(days=1),
            ap_date=now,
        )

    def test_filter_checkbox_positions_at_mobile_and_desktop_widths(self):
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(self._read_positions).result()

        self.assertEqual(result['response_status'], 200)
        for width in (320, 360, 390):
            for group_index, group_name, labels in (
                (0, 'Voter Type', ('Voter', 'Provisional')),
                (1, 'Ballot Type', ('Human', 'Computer', 'Hybrid')),
                (2, 'Timing', ('Before the AP', 'After the AP')),
            ):
                self._assert_group_fits_on_one_line(
                    result['mobile'][width][group_index], group_name, labels, width
                )

        for group_index, group_name in enumerate(('Voter Type', 'Ballot Type', 'Timing')):
            metrics = result['desktop'][group_index]
            self.assertNotEqual(
                metrics['options_display'],
                'flex',
                msg=f'{group_name} mobile layout leaked into desktop styles',
            )
            self.assertEqual(
                metrics['options_font_size'],
                '16px',
                msg=f'{group_name} compact mobile font leaked into desktop styles',
            )
            self.assertAlmostEqual(
                metrics['label']['top'],
                metrics['options']['top'],
                delta=1,
                msg=f'{group_name} no longer shares a row with its options on desktop',
            )
            self.assertLessEqual(
                metrics['label']['right'],
                metrics['options']['left'],
                msg=f'{group_name} options no longer follow the heading on desktop',
            )

    def test_team_rankings_tables_fit_phone_viewports(self):
        team = Team.objects.create(
            handle='layout-test-team',
            name='Layout Test Team',
            conference='Test',
            division='Test',
            use_for_ballot=False,
            short_name='TEST',
        )
        for user_type in (UserRole.Role.VOTER, UserRole.Role.PROVISIONAL):
            user = User.objects.create(username='voter-' + ('x' * 26))
            ballot = Ballot.objects.create(
                user=user,
                poll=self.poll,
                submission_date=timezone.now(),
                poll_type=Ballot.BallotType.HUMAN,
                user_type=user_type,
            )
            BallotEntry.objects.create(
                ballot=ballot,
                team=team,
                rank=1,
                rationale=(
                    'A written rationale with a long unbroken word '
                    + ('rationale' * 12)
                    + ' and enough surrounding text to check normal wrapping.'
                ),
            )
        empty_reason_user = User.objects.create(username='empty-rationale')
        empty_reason_ballot = Ballot.objects.create(
            user=empty_reason_user,
            poll=self.poll,
            submission_date=timezone.now(),
            poll_type=Ballot.BallotType.HUMAN,
            user_type=UserRole.Role.VOTER,
        )
        BallotEntry.objects.create(
            ballot=empty_reason_ballot,
            team=team,
            rank=2,
            rationale='',
        )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={'width': 320, 'height': 900}, device_scale_factor=1)
            try:
                page.route('**/*.js', lambda route: route.abort())
                response = page.goto(
                    f'{self.live_server_url}/poll/view/{self.poll.id}/team/{team.id}/',
                    wait_until='domcontentloaded',
                )
                self.assertEqual(response.status, 200)

                first_table = page.locator('.team-rankings-table').first
                self.assertEqual(first_table.locator('thead th').all_inner_texts(), ['User', 'Rank', 'Rationale'])
                self.assertNotIn('No reason submitted', page.locator('body').inner_text())
                empty_reason_row = first_table.locator('tbody tr').nth(1)
                self.assertEqual(empty_reason_row.locator('td').nth(2).inner_text().strip(), '')
                self.assertEqual(empty_reason_row.locator('.team-rankings-rationale-disclosure').count(), 0)

                first_row = first_table.locator('tbody tr').first
                disclosure = first_row.locator('.team-rankings-rationale-disclosure')
                reason = disclosure.locator('.team-rankings-rationale-content')
                self.assertFalse(reason.is_visible())
                self.assertEqual(disclosure.locator('summary').inner_text(), 'Rationale')
                row_height_before = first_row.evaluate('row => row.getBoundingClientRect().height')
                disclosure.locator('summary').click()
                self.assertTrue(reason.is_visible())
                expanded_metrics = disclosure.evaluate(
                    """details => {
                        const summary = details.querySelector('summary').getBoundingClientRect();
                        const rationale = details.querySelector('.team-rankings-rationale-content').getBoundingClientRect();
                        const cell = details.closest('td').getBoundingClientRect();
                        const row = details.closest('tr').getBoundingClientRect();
                        return {summaryBottom: summary.bottom, rationaleTop: rationale.top, cellRight: cell.right,
                            rationaleRight: rationale.right, rowHeight: row.height};
                    }"""
                )
                self.assertGreaterEqual(expanded_metrics['rationaleTop'], expanded_metrics['summaryBottom'])
                self.assertLessEqual(expanded_metrics['rationaleRight'], expanded_metrics['cellRight'])
                self.assertGreater(expanded_metrics['rowHeight'], row_height_before)
                disclosure.locator('summary').click()
                self.assertFalse(reason.is_visible())

                for width in (320, 360, 390, 430, 768, 1024, 1440):
                    page.set_viewport_size({'width': width, 'height': 900})
                    metrics = page.evaluate(
                        """() => {
                            const container = document.querySelector('.container').getBoundingClientRect();
                            return {
                                viewport: document.documentElement.clientWidth,
                                document: document.documentElement.scrollWidth,
                                tables: Array.from(document.querySelectorAll('.team-rankings-table')).map(table => {
                                    const box = table.getBoundingClientRect();
                                    return {left: box.left, right: box.right, width: box.width,
                                        display: getComputedStyle(table).display};
                                }),
                                container: {left: container.left, right: container.right},
                            };
                        }"""
                    )
                    self.assertEqual(len(metrics['tables']), 2)
                    self.assertLessEqual(
                        metrics['document'],
                        width,
                        msg=f'Document overflows at {width}px: {metrics}',
                    )
                    self.assertTrue(all(table['display'] == 'table' for table in metrics['tables']))
                    for table in metrics['tables']:
                        self.assertGreaterEqual(table['left'], metrics['container']['left'] - 1)
                        self.assertLessEqual(
                            table['right'],
                            metrics['container']['right'] + 1,
                            msg=f'Team rankings table exceeds its container at {width}px: {metrics}',
                        )
                    rationale_disclosure = page.locator('.team-rankings-table').first.locator(
                        '.team-rankings-rationale-disclosure'
                    ).first
                    rationale_full = page.locator('.team-rankings-table').first.locator(
                        '.team-rankings-rationale-full'
                    ).first
                    self.assertEqual(rationale_disclosure.is_visible(), width < 768)
                    self.assertEqual(rationale_full.is_visible(), width >= 768)
            finally:
                browser.close()

    def _read_positions(self):
        result = {'mobile': {}, 'desktop': {}}
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(
                viewport={'width': 320, 'height': 900},
                device_scale_factor=1,
            )
            try:
                page.route('**/*.js', lambda route: route.abort())
                response = page.goto(
                    f'{self.live_server_url}/poll/view/{self.poll.id}/'
                    '?main=on&provisional=on&human=on&computer=on&hybrid=on'
                    '&before_ap=on&after_ap=on',
                    wait_until='domcontentloaded',
                )
                result['response_status'] = response.status
                page.locator('#collapseOne.show').wait_for()

                for width in (320, 360, 390):
                    page.set_viewport_size({'width': width, 'height': 900})
                    page.wait_for_function(
                        "getComputedStyle(document.querySelector('.poll-filter-options')).display === 'flex'"
                    )
                    result['mobile'][width] = [
                        self._group_metrics(page, group_index)
                        for group_index in range(3)
                    ]

                page.set_viewport_size({'width': 1024, 'height': 900})
                page.wait_for_function(
                    "getComputedStyle(document.querySelector('.poll-filter-options')).display !== 'flex'"
                )
                result['desktop'] = [
                    self._group_metrics(page, group_index)
                    for group_index in range(3)
                ]
            finally:
                browser.close()
        return result

    def _assert_group_fits_on_one_line(self, metrics, group_name, expected_labels, width):
        self.assertEqual(metrics['label_text'], list(expected_labels))
        self.assertEqual(len(metrics['labels']), len(expected_labels))
        self.assertEqual(len(metrics['inputs']), len(expected_labels))
        self.assertTrue(all(box['checked'] for box in metrics['inputs']))
        label_tops = [label['top'] for label in metrics['labels']]
        self.assertLessEqual(
            max(label_tops) - min(label_tops),
            1,
            msg=f'{group_name} options wrap at {width}px: {metrics}',
        )
        input_tops = [box['top'] for box in metrics['inputs']]
        self.assertLessEqual(
            max(input_tops) - min(input_tops),
            1,
            msg=f'{group_name} checkboxes wrap at {width}px: {metrics}',
        )
        self.assertLessEqual(
            max(label['height'] for label in metrics['labels']),
            25,
            msg=f'{group_name} option text wraps at {width}px: {metrics}',
        )
        self.assertGreaterEqual(
            min(label['left'] for label in metrics['labels']),
            metrics['options']['left'] - 1,
            msg=f'{group_name} options overflow their container at {width}px: {metrics}',
        )
        self.assertLessEqual(
            max(label['right'] for label in metrics['labels']),
            metrics['options']['right'] + 1,
            msg=f'{group_name} options overflow their container at {width}px: {metrics}',
        )
        self.assertGreaterEqual(
            min(box['left'] for box in metrics['inputs']),
            metrics['options']['left'] - 1,
            msg=f'{group_name} checkboxes overflow their container at {width}px: {metrics}',
        )
        self.assertLessEqual(
            max(box['right'] for box in metrics['inputs']),
            metrics['options']['right'] + 1,
            msg=f'{group_name} checkboxes overflow their container at {width}px: {metrics}',
        )
        self.assertGreaterEqual(
            metrics['options']['left'],
            0,
            msg=f'{group_name} options start outside the viewport at {width}px: {metrics}',
        )
        self.assertLessEqual(
            metrics['options']['right'],
            width,
            msg=f'{group_name} options extend past the viewport at {width}px: {metrics}',
        )

    @staticmethod
    def _group_metrics(page, index):
        return page.locator('.poll-filter-row').nth(index).evaluate(
            """group => {
                const rect = element => {
                    const box = element.getBoundingClientRect();
                    return {top: box.top, left: box.left, right: box.right, height: box.height};
                };
                const labels = Array.from(group.querySelectorAll('.form-check-label'));
                const inputs = Array.from(group.querySelectorAll('.form-check-input'));
                const options = group.querySelector('.poll-filter-options');
                return {
                    label: rect(group.querySelector('.poll-filter-label')),
                    options: rect(options),
                    labels: labels.map(rect),
                    label_text: labels.map(label => label.innerText.trim()),
                    inputs: inputs.map(input => ({...rect(input), checked: input.checked})),
                    options_display: getComputedStyle(options).display,
                    options_font_size: getComputedStyle(options).fontSize,
                };
            }"""
        )
