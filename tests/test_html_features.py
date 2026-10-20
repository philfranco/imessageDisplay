import tempfile
import unittest

from html_pages import (
    build_html,
    build_index,
    build_search_index,
    summarize_messages,
)


def sample_messages():
    return [
        {
            'id': 1,
            'guid': 'first',
            'text': 'hello </script>',
            'date': '2024-01-01 08:30:00',
            'is_from_me': True,
            'sender': 'Me',
            'chat_id': ('phone', '15551234567'),
            'attachments': [],
        },
        {
            'id': 2,
            'guid': 'second',
            'text': 'reply',
            'date': '2024-01-01 08:45:00',
            'is_from_me': False,
            'sender': 'Alex',
            'chat_id': ('phone', '15551234567'),
            'attachments': [],
        },
        {
            'id': 3,
            'guid': 'third',
            'text': 'next year',
            'date': '2025-02-03 10:15:00',
            'is_from_me': True,
            'sender': 'Me',
            'chat_id': ('phone', '15551234567'),
            'attachments': [],
        },
    ]


class HtmlFeatureTests(unittest.TestCase):
    def setUp(self):
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.output_dir = self.temporary_dir.name
        self.messages = sample_messages()

    def tearDown(self):
        self.temporary_dir.cleanup()

    def test_stats_include_sent_received_and_busiest_day(self):
        stats = summarize_messages(self.messages)

        self.assertEqual(stats['sent'], 2)
        self.assertEqual(stats['received'], 1)
        self.assertEqual(stats['busiest_date'], '2024-01-01')
        self.assertEqual(stats['busiest_count'], 2)
        self.assertEqual(stats['daily_counts']['2025-02-03'], 1)

    def test_conversation_page_has_text_date_and_time_filters(self):
        path = build_html('Alex', self.messages, self.output_dir)

        with open(path, encoding='utf-8') as page:
            content = page.read()

        self.assertIn('id="messageTextSearch"', content)
        self.assertIn('id="messageDateFrom"', content)
        self.assertIn('id="messageDateTo"', content)
        self.assertIn('id="messageTimeFrom"', content)
        self.assertIn('id="messageTimeTo"', content)
        self.assertIn('data-date="2024-01-01"', content)
        self.assertIn('data-time="03:30"', content)
        self.assertIn('America/New_York', content)

    def test_search_page_supports_text_date_and_time_search(self):
        path = build_search_index([('Alex', 'Alex', self.messages)], self.output_dir)

        with open(path, encoding='utf-8') as page:
            content = page.read()

        self.assertIn('id="messageSearchInput"', content)
        self.assertIn('id="dateFromInput"', content)
        self.assertIn('id="dateToInput"', content)
        self.assertIn('id="timeFromInput"', content)
        self.assertIn('id="timeToInput"', content)
        self.assertIn('data-search-messages=', content)
        self.assertIn('\\u003c/script\\u003e', content)
        self.assertIn('new URLSearchParams(window.location.search)', content)
        self.assertIn('link.href = link.dataset.conversationFile', content)

    def test_index_has_per_year_activity_and_overall_stats(self):
        stats = summarize_messages(self.messages)
        stats['conversations'] = 1
        path = build_index([('Alex', 'Alex', self.messages)], self.output_dir, stats)

        with open(path, encoding='utf-8') as page:
            content = page.read()

        self.assertIn('Messages per day', content)
        self.assertIn('data-year="2024"', content)
        self.assertIn('data-year="2025"', content)
        self.assertIn('id="previousYear"', content)
        self.assertIn('id="nextYear"', content)
        self.assertIn('Sent messages', content)
        self.assertIn('Received messages', content)
        self.assertIn('Most messages in one day', content)
        self.assertIn('title="2024-01-01: 2 messages"', content)
        self.assertIn('href="search.html?date=2024-01-01"', content)

    def test_conversation_page_restores_incoming_search_filters(self):
        path = build_html('Alex', self.messages, self.output_dir)

        with open(path, encoding='utf-8') as page:
            content = page.read()

        self.assertIn('messageQueryFields', content)
        self.assertIn('backToSearch.href = "search.html?"', content)
        self.assertIn('messageQuery.get(key)', content)

    def test_eastern_display_applies_standard_and_daylight_offsets(self):
        messages = [
            {
                'id': 1,
                'text': 'winter',
                'date': '2024-01-15 14:00:00',
                'is_from_me': True,
                'sender': 'Me',
                'chat_id': ('phone', '15551234567'),
                'attachments': [],
            },
            {
                'id': 2,
                'text': 'summer',
                'date': '2024-07-15 13:00:00',
                'is_from_me': False,
                'sender': 'Alex',
                'chat_id': ('phone', '15551234567'),
                'attachments': [],
            },
            {
                'id': 3,
                'text': 'previous local day',
                'date': '2024-01-02 02:00:00',
                'is_from_me': False,
                'sender': 'Alex',
                'chat_id': ('phone', '15551234567'),
                'attachments': [],
            },
        ]
        path = build_html('Alex', messages, self.output_dir)

        with open(path, encoding='utf-8') as page:
            content = page.read()
        stats = summarize_messages(messages)

        self.assertIn('data-time="09:00"', content)
        self.assertIn('2024-07-15 09:00:00', content)
        self.assertIn('2024-01-01 21:00:00', content)
        self.assertIn('data-date="2024-01-01"', content)
        self.assertEqual(stats['daily_counts']['2024-01-01'], 1)

        search_path = build_search_index([('Alex', 'Alex', messages)], self.output_dir)
        with open(search_path, encoding='utf-8') as page:
            search_content = page.read()
        self.assertIn(
            '&quot;date&quot;:&quot;2024-01-01&quot;,&quot;time&quot;:&quot;21:00&quot;',
            search_content,
        )


if __name__ == '__main__':
    unittest.main()
