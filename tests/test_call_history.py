import datetime
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
        self.assertIn('10:00', content)
        self.assertIn('1:05', content)

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
