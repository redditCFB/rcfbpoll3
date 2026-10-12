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
                voter_rows = first_table.locator('tbody > tr:not(.team-rankings-expanded-rationale)')
                empty_reason_row = voter_rows.nth(1)
                self.assertEqual(empty_reason_row.locator('td').nth(2).inner_text().strip(), '')
                self.assertEqual(empty_reason_row.locator('.team-rankings-rationale-toggle').count(), 0)

                first_row = voter_rows.first
                toggle = first_row.locator('.team-rankings-rationale-toggle')
                reason_id = toggle.get_attribute('aria-controls')
                rationale_row = page.locator(f'#{reason_id}')
                reason = rationale_row.locator('.team-rankings-rationale-content')
                self.assertFalse(reason.is_visible())
                self.assertEqual(toggle.inner_text(), 'Rationale')
                self.assertEqual(toggle.get_attribute('aria-expanded'), 'false')
                alignment = first_row.evaluate(
                    """row => {
                        const user = row.cells[0].querySelector('a').getBoundingClientRect();
                        const toggle = row.querySelector('.team-rankings-rationale-toggle').getBoundingClientRect();
                        const rankRange = document.createRange();
                        rankRange.selectNodeContents(row.cells[1]);
                        const rank = rankRange.getBoundingClientRect();
                        return {userTop: user.top, toggleTop: toggle.top, rankTop: rank.top};
                    }"""
                )
                self.assertLessEqual(abs(alignment['toggleTop'] - alignment['userTop']), 3)
                self.assertLessEqual(abs(alignment['toggleTop'] - alignment['rankTop']), 3)
                toggle.click()
                self.assertTrue(reason.is_visible())
                self.assertEqual(toggle.get_attribute('aria-expanded'), 'true')
                block_backgrounds = rationale_row.evaluate(
                    """row => {
                        const block = row.closest('tbody');
                        const nextBlock = block.nextElementSibling;
                        const accent = cell => getComputedStyle(cell).getPropertyValue('--bs-table-accent-bg').trim();
                        return {
                            voter: accent(block.rows[0].cells[0]),
                            rationale: accent(row.cells[0]),
                            nextVoter: accent(nextBlock.rows[0].cells[0]),
                        };
                    }"""
                )
                self.assertEqual(block_backgrounds['voter'], block_backgrounds['rationale'])
                self.assertNotEqual(block_backgrounds['voter'], block_backgrounds['nextVoter'])
                expanded_metrics = rationale_row.evaluate(
                    """row => {
                        const cell = row.cells[0].getBoundingClientRect();
                        const table = row.closest('table').getBoundingClientRect();
                        const rationale = row.querySelector('.team-rankings-rationale-content').getBoundingClientRect();
                        return {colspan: row.cells[0].colSpan, cellLeft: cell.left, cellRight: cell.right,
                            tableLeft: table.left, tableRight: table.right,
                            rationaleLeft: rationale.left, rationaleRight: rationale.right};
                    }"""
                )
                self.assertEqual(expanded_metrics['colspan'], 3)
                self.assertAlmostEqual(expanded_metrics['cellLeft'], expanded_metrics['tableLeft'], delta=1)
                self.assertAlmostEqual(expanded_metrics['cellRight'], expanded_metrics['tableRight'], delta=1)
                self.assertGreater(expanded_metrics['rationaleRight'] - expanded_metrics['rationaleLeft'], 0.85 * (
                    expanded_metrics['tableRight'] - expanded_metrics['tableLeft']
                ))
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 320)
                toggle.click()
                self.assertFalse(reason.is_visible())
                self.assertEqual(toggle.get_attribute('aria-expanded'), 'false')

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
                    rationale_toggle = page.locator('.team-rankings-table').first.locator(
                        '.team-rankings-rationale-toggle'
                    ).first
                    rationale_full = page.locator('.team-rankings-table').first.locator(
                        '.team-rankings-rationale-full'
                    ).first
                    self.assertEqual(rationale_toggle.is_visible(), width < 768)
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


class BallotComparisonLayoutBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        now = timezone.now()
        self.poll = Poll.objects.create(
            year=now.year,
            week='Ballot comparison browser test',
            open_date=now - timedelta(days=2),
            close_date=now + timedelta(days=2),
            publish_date=now - timedelta(days=1),
            ap_date=now - timedelta(days=2),
        )
        teams = [
            Team.objects.create(
                handle=f'comparison-team-{rank}',
                name=f'Comparison Team {rank}',
                conference='Test',
                division='Test',
                use_for_ballot=False,
                short_name=f'TEAM{rank:02d}',
            )
            for rank in range(1, 26)
        ]

        for user_type, prefix in (
            (UserRole.Role.VOTER, 'main'),
            (UserRole.Role.PROVISIONAL, 'provisional'),
        ):
            for voter_number in range(1, 6):
                user = User.objects.create(username=f'{prefix}-voter-{voter_number}')
                ballot = Ballot.objects.create(
                    user=user,
                    poll=self.poll,
                    submission_date=now - timedelta(hours=1),
                    poll_type=Ballot.BallotType.HUMAN,
                    user_type=user_type,
                )
                BallotEntry.objects.bulk_create([
                    BallotEntry(
                        ballot=ballot,
                        team=teams[(rank + voter_number - 2) % len(teams)],
                        rank=rank,
                    )
                    for rank in range(1, len(teams) + 1)
                ])

    def test_phone_ballots_are_readable_without_page_wide_horizontal_scrolling(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={'width': 320, 'height': 900}, device_scale_factor=1)
            try:
                page.route('**/*.js', lambda route: route.abort())
                for user_type, prefix in (
                    (UserRole.Role.VOTER, 'main'),
                    (UserRole.Role.PROVISIONAL, 'provisional'),
                ):
                    response = page.goto(
                        f'{self.live_server_url}/poll/ballots/{self.poll.id}/{user_type}/',
                        wait_until='domcontentloaded',
                    )
                    self.assertEqual(response.status, 200)

                    for width in (320, 360, 390, 430, 575, 576, 767, 768, 1024, 1440):
                        page.set_viewport_size({'width': width, 'height': 900})
                        metrics = page.evaluate(
                            """() => ({
                                document: document.documentElement.scrollWidth,
                                desktop: getComputedStyle(document.querySelector('.ballot-comparison-desktop')).display,
                                mobileDisplay: getComputedStyle(document.querySelector('.ballot-comparison-mobile')).display,
                                mobileScroll: document.querySelector('.ballot-comparison-mobile').scrollWidth,
                                mobileClient: document.querySelector('.ballot-comparison-mobile').clientWidth,
                            })"""
                        )
                        self.assertLessEqual(
                            metrics['document'],
                            width,
                            msg=f'{prefix} ballot page overflows at {width}px: {metrics}',
                        )
                        if width < 768:
                            self.assertEqual(metrics['desktop'], 'none')
                            self.assertNotEqual(metrics['mobileDisplay'], 'none')
                            self.assertLessEqual(
                                metrics['mobileScroll'],
                                metrics['mobileClient'],
                                msg=f'Mobile ballot table scrolls horizontally at {width}px: {metrics}',
                            )
                            mobile_table = page.locator('.ballot-comparison-mobile-table')
                            self.assertTrue(mobile_table.is_visible())
                            self.assertEqual(mobile_table.locator('thead th').count(), 6)
                            self.assertEqual(mobile_table.locator('thead th').first.inner_text(), 'Rank')
                            for voter_number in range(1, 6):
                                heading = mobile_table.locator('thead th').nth(voter_number)
                                voter_name = heading.locator('.ballot-comparison-mobile-voter-name')
                                self.assertEqual(
                                    voter_name.inner_text().strip(),
                                    f'{prefix}-voter-{voter_number}',
                                )
                                self.assertEqual(
                                    voter_name.evaluate('element => getComputedStyle(element).writingMode'),
                                    'vertical-rl',
                                )
                                self.assertNotEqual(
                                    voter_name.evaluate('element => getComputedStyle(element).transform'),
                                    'none',
                                )

                            rows = mobile_table.locator('tbody tr')
                            self.assertEqual(rows.count(), 25)
                            self.assertTrue(all(row.locator('td').count() == 5 for row in rows.all()))
                            first_row_links = rows.first.locator('td a')
                            last_row_links = rows.last.locator('td a')
                            self.assertEqual(first_row_links.count(), 5)
                            self.assertEqual(last_row_links.count(), 5)
                            for voter_index in range(5):
                                self.assertEqual(
                                    first_row_links.nth(voter_index).get_attribute('aria-label'),
                                    f'Rank 1: TEAM{voter_index + 1:02d}',
                                )
                            self.assertEqual(last_row_links.first.get_attribute('aria-label'), 'Rank 25: TEAM25')
                            self.assertEqual(last_row_links.last.get_attribute('aria-label'), 'Rank 25: TEAM04')
                            self.assertEqual(mobile_table.locator('tbody img').count(), 125)
                            self.assertTrue(all(
                                not text.strip()
                                for row in rows.all()
                                for text in row.locator('td').all_inner_texts()
                            ))
                        else:
                            self.assertNotEqual(metrics['desktop'], 'none')
                            self.assertEqual(metrics['mobileDisplay'], 'none')
                            self.assertEqual(
                                page.locator('.ballot-comparison-desktop table tr').count(),
                                26,
                            )
            finally:
                browser.close()
