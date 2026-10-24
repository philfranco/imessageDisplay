import datetime
import json
import os
import sqlite3
import tempfile
import unittest

from call_history import fetch_call_history
from html_pages import build_call_history


def make_call_database(path, calls):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(
        'CREATE TABLE ZCALLRECORD ('
        'Z_PK INTEGER PRIMARY KEY, ZADDRESS TEXT, ZDATE REAL, ZDURATION REAL, '
        'ZORIGINATED INTEGER, ZANSWERED INTEGER, ZCALLTYPE INTEGER)'
    )
    connection.executemany(
        'INSERT INTO ZCALLRECORD '
        '(Z_PK, ZADDRESS, ZDATE, ZDURATION, ZORIGINATED, ZANSWERED, ZCALLTYPE) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        calls,
    )
    connection.commit()
    connection.close()


class CallHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.output_dir = self.temporary_dir.name

    def tearDown(self):
        self.temporary_dir.cleanup()

    def test_reads_calls_resolves_contacts_and_deduplicates_backups(self):
        timestamp = datetime.datetime(
            2025, 1, 15, 15, 0, tzinfo=datetime.timezone.utc
        ).timestamp() - 978307200
        database_one = os.path.join(self.output_dir, 'one', 'CallHistory.storedata')
        database_two = os.path.join(self.output_dir, 'two', 'CallHistory.storedata')
        record = (1, '+1 (555) 123-4567', timestamp, 125.0, 0, 1, 1)
        missed = (2, '555-765-4321', timestamp + 3600, 0.0, 0, 0, 1)
        make_call_database(database_one, [record, missed])
        make_call_database(database_two, [record])

        calls = fetch_call_history([
            (database_one, {'5551234567': 'Alex'}),
            (database_two, {'5551234567': 'Alex'}),
        ])

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]['contact'], '555-765-4321')
        self.assertEqual(calls[0]['direction'], 'Missed')
        self.assertEqual(calls[1]['contact'], 'Alex')
        self.assertEqual(calls[1]['phone_number'], '5551234567')
        self.assertEqual(calls[1]['date'], '2025-01-15 15:00:00')
        self.assertEqual(calls[1]['duration'], 125.0)

    def test_call_history_page_has_navigation_search_and_timezone_rendering(self):
        calls = [{
            'date': '2025-01-15 15:00:00',
            'address': '+15551234567',
            'phone_number': '5551234567',
            'contact': 'Alex & Jordan',
            'duration': 65,
            'direction': 'Incoming',
        }]

        path = build_call_history(calls, self.output_dir)

        with open(path, encoding='utf-8') as page:
            content = page.read()
        self.assertIn('Call history', content)
        self.assertIn('href="search.html"', content)
        self.assertIn('Search contact or number', content)
        self.assertIn('From date', content)
        self.assertIn('Alex &amp; Jordan', content)
        self.assertIn('Go to a random day', content)
        self.assertIn('Go to a random week', content)
        self.assertIn('Clear filters', content)
        self.assertIn('10:00', content)
        self.assertIn('1:05', content)

    def test_call_history_page_batches_large_tables_with_lazy_loading(self):
        calls = [
            {
                'date': f'2025-01-{index % 28 + 1:02d} 15:00:00',
                'address': '111',
                'phone_number': '111',
                'contact': f'Caller {index}',
                'duration': 60,
                'direction': 'Incoming',
            }
            for index in range(2005)
        ]

        path = build_call_history(calls, self.output_dir)

        with open(path, encoding='utf-8') as page:
            content = page.read()
        self.assertEqual(content.count('<tr class="call-row"'), 2000)
        self.assertIn('id="loadMoreSentinel"', content)
        self.assertIn('Load 2,000 more calls', content)
        self.assertIn('const BATCH_SIZE = 2000;', content)
        self.assertIn('let pending =', content)
        self.assertIn('function renderRows(entries)', content)
        self.assertIn('function entryMatches(m)', content)
        self.assertIn('pending = rest.concat(pending);', content)
        self.assertIn('if (pending.length) renderChunk(BATCH_SIZE);', content)
        self.assertIn('<template id="callTemplate"></template>', content)
        # tr rows cannot be parsed from a bare template fragment; wrap in a table.
        self.assertIn('callTemplate.innerHTML = "<table><tbody>" + markup + "</tbody></table>";', content)
        self.assertIn('callTemplate.content.querySelector("tbody");', content)
        # Click-to-sort headers for every column.
        self.assertIn('<th class="sortable" data-sort="datetime">Date and time</th>', content)
        self.assertIn('<th class="sortable" data-sort="duration">Duration</th>', content)
        self.assertIn('function rowValue(row, key)', content)
        self.assertIn('function sortRows(key)', content)
        # Active filters auto-sort by date ascending, showing the blue ▲ on Date and time.
        self.assertNotIn('markFilterColumns', content)
        self.assertNotIn('filter-mark', content)
        self.assertIn('function applySort(key, dir)', content)
        self.assertIn('if (!noFilters) applySort("datetime", 1);', content)
        # Quotes in the generated selector must stay balanced; a raw " here is a JS syntax error.
        self.assertIn("document.querySelector('.sortable[data-sort=\"' + key + '\"]');", content)
        self.assertIn('list.appendChild(loadMoreSentinel);', content)
        self.assertIn('.sortable { cursor: pointer; user-select: none; }', content)
        self.assertIn('IntersectionObserver', content)
        self.assertIn('Showing " + visible.toLocaleString() + " of " + totalCalls.toLocaleString()', content)
        # Random day/week buttons must pick from dates that actually have calls.
        self.assertIn('Go to a random day', content)
        self.assertIn('Go to a random week', content)
        self.assertIn('const availableCallDates = new Set(allDatesEl ? JSON.parse(allDatesEl.textContent) : []);', content)
        self.assertIn('setCallDateRange(randomDate, randomDate);', content)
        self.assertIn('setCallDateRange(formatDate(monday), formatDate(sunday));', content)
        self.assertIn('<button type="button" id="clearFiltersButton">Clear filters</button>', content)

        payload_start = content.index('id="pendingData">') + len('id="pendingData">')
        payload_end = content.index('</script>', payload_start)
        # Raw '<' must be escaped as \\u003c so the data block cannot terminate.
        self.assertNotIn('<', content[payload_start:payload_end])
        pending = json.loads(content[payload_start:payload_end])
        self.assertEqual(len(pending), 5)
        self.assertIn('Caller 2000', pending[0]['r'])
        self.assertEqual(pending[0]['d'], '2025-01-13')

    def test_call_history_page_explains_when_no_calls_are_available(self):
        path = build_call_history([], self.output_dir)

        with open(path, encoding='utf-8') as page:
            content = page.read()
        self.assertIn('No call history was found', content)

    def test_call_history_statistics_rank_contacts_and_count_call_directions(self):
        calls = [
            {
                'date': f'2025-01-{day:02d} 15:00:00',
                'address': number,
                'phone_number': number,
                'contact': name,
                'duration': duration,
                'direction': direction,
            }
            for day, number, name, duration, direction in (
                (1, '111', 'Alex', 60, 'Incoming'),
                (2, '111', 'Alex', 60, 'Outgoing'),
                (3, '111', 'Alex', 60, 'Missed'),
                (4, '222', 'Jordan', 300, 'Incoming'),
                (5, '333', 'Casey', 240, 'Outgoing'),
                (6, '444', 'Morgan', 30, 'Outgoing'),
                (7, '555', 'Riley', 10, 'Incoming'),
                (8, '666', 'Taylor', 5, 'Outgoing'),
            )
        ]

        path = build_call_history(calls, self.output_dir)

        with open(path, encoding='utf-8') as page:
            content = page.read()
        self.assertIn('<h2>Incoming calls</h2>', content)
        self.assertIn('<p class="stat-value">4</p>', content)
        self.assertIn('<h2>Outgoing calls</h2>', content)
        self.assertIn('<p class="stat-value">4</p>', content)
        self.assertIn('Top 5 by number of calls', content)
        self.assertIn('Top 5 by call duration', content)
        self.assertLess(content.index('<span>Alex</span><strong>3 calls</strong>'),
                        content.index('<span>Jordan</span><strong>1 call</strong>'))
        self.assertLess(content.index('<span>Jordan</span><strong>5:00</strong>'),
                        content.index('<span>Casey</span><strong>4:00</strong>'))
        self.assertNotIn('<span>Taylor</span><strong>1 call</strong>', content)


if __name__ == '__main__':
    unittest.main()
