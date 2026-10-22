import json
import os
import tempfile
import unittest
from pathlib import Path

from html_pages import (
    build_html,
    build_index,
    build_search_index,
    summarize_messages,
)
from sms_database import normalize_attachment_paths


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
        self.assertIn('id="messageCount"', content)
        self.assertIn('id="attachmentCount"', content)
        self.assertIn('data-attachment-count="0"', content)
        self.assertIn('visibleAttachments += Number(item.dataset.attachmentCount || 0)', content)
        self.assertIn('activity-card', content)
        self.assertIn('Messages per day in this conversation', content)
        self.assertIn('data-year="2024"', content)
        self.assertIn('data-year="2025"', content)
        self.assertIn('id="conversationPreviousYear"', content)
        self.assertIn('id="conversationNextYear"', content)
        self.assertIn('data-calendar-date="2024-01-01"', content)
        self.assertIn('messageDateFrom").value = day.dataset.calendarDate', content)

    def test_sticker_cache_attachment_is_rendered_as_conversation_image(self):
        sticker_root = os.path.join(
            self.output_dir,
            'extracted_backup',
            'HomeDomain',
            'Library',
            'SMS',
            'StickerCache',
        )
        sticker_relative_path = os.path.join('sticker', 'sticker.png')
        sticker_path = os.path.join(sticker_root, sticker_relative_path)
        os.makedirs(os.path.dirname(sticker_path))
        with open(sticker_path, 'wb') as sticker:
            sticker.write(b'png image')

        attachments = normalize_attachment_paths(
            {
                2: [{
                    'filename': '~/Library/SMS/StickerCache/sticker/sticker.png',
                    'mime_type': 'image/png',
                }]
            },
            os.path.join(self.output_dir, 'extracted_backup', 'MediaDomain'),
            sticker_root,
        )
        messages = [dict(self.messages[1], attachments=attachments[2])]

        path = build_html('Alex', messages, self.output_dir)

        with open(path, encoding='utf-8') as page:
            content = page.read()
        self.assertIn(f'<img src="{Path(sticker_path).as_uri()}"', content)

    def test_conversation_counts_and_calendar_are_scoped_to_its_messages(self):
        messages = sample_messages()
        messages[0]['attachments'] = [{'filename': 'one.jpg'}, {'filename': 'two.jpg'}]
        messages[2]['attachments'] = [{'filename': 'three.jpg'}]
        path = build_html('Alex', messages, self.output_dir)

        with open(path, encoding='utf-8') as page:
            content = page.read()

        self.assertIn('<strong id="messageCount">3</strong> messages', content)
        self.assertIn('<strong id="attachmentCount">3</strong> attachments', content)
        self.assertIn('data-attachment-count="2"', content)
        self.assertIn('data-attachment-count="1"', content)
        self.assertIn('data-year="2024"', content)
        self.assertIn('data-year="2025"', content)
        self.assertIn('title="2024-01-01: 2 messages"', content)
        self.assertIn('title="2025-02-03: 1 messages"', content)

    def test_search_page_supports_text_date_and_time_search(self):
        path = build_search_index([('Alex', 'Alex', self.messages)], self.output_dir)

        with open(path, encoding='utf-8') as page:
            content = page.read()

        self.assertIn('id="messageSearchInput"', content)
        self.assertIn('id="dateFromInput"', content)
        self.assertIn('id="dateToInput"', content)
        self.assertIn('id="timeFromInput"', content)
        self.assertIn('id="timeToInput"', content)
        self.assertIn('id="randomDayButton">Go to a random day</button>', content)
        self.assertIn('randomDayButton.disabled = availableDates.size === 0', content)
        self.assertIn('const randomDate = dates[Math.floor(Math.random() * dates.length)]', content)
        self.assertIn('dateFromInput.value = randomDate', content)
        self.assertIn('dateToInput.value = randomDate', content)
        self.assertIn('randomDayStatus.textContent = "Showing conversations from " + randomDate', content)
        self.assertIn(
            'window.addEventListener("pageshow", function() { filterConversations(); });',
            content,
        )
        self.assertIn('type="application/json"', content)
        self.assertIn('data-search-index="0"', content)
        self.assertNotIn('data-search-messages=', content)
        self.assertIn('\\u003c/script\\u003e', content)
        payload_start = content.index('id="searchMessageData" type="application/json">') + len(
            'id="searchMessageData" type="application/json">'
        )
        payload_end = content.index('</script>', payload_start)
        search_data = json.loads(content[payload_start:payload_end])
        self.assertEqual(search_data, [[
            ['hello </script>', '2024-01-01', '03:30', 0],
            ['reply', '2024-01-01', '03:45', 0],
            ['next year', '2025-02-03', '05:15', 0],
        ]])
        self.assertIn(
            'JSON.parse(document.getElementById("searchMessageData").textContent)',
            content,
        )
        self.assertIn('new URLSearchParams(window.location.search)', content)
        self.assertIn('link.href = link.dataset.conversationFile', content)
        self.assertIn('href="calls.html">Call history</a>', content)

    def test_search_page_applies_message_filters_to_row_counts_and_dates(self):
        messages = sample_messages()
        messages[0]['attachments'] = [{'filename': 'one.jpg'}, {'filename': 'two.jpg'}]
        messages[1]['attachments'] = [{'filename': 'three.jpg'}]
        messages[2]['attachments'] = [{'filename': 'later.jpg'}]
        path = build_search_index([('Alex', 'Alex', messages)], self.output_dir)

        with open(path, encoding='utf-8') as page:
            content = page.read()

        self.assertIn('class="filtered-message-count">3</span>', content)
        self.assertIn('class="filtered-attachment-count">4</span>', content)
        self.assertIn('["hello \\u003c/script\\u003e","2024-01-01","03:30",2]', content)
        self.assertIn('messages.filter(function(message)', content)
        self.assertIn('message[0].includes(messageTerm)', content)
        self.assertIn('message[3] || 0', content)
        self.assertIn('item.querySelector(".filtered-message-count").textContent', content)
        self.assertIn('item.querySelector(".filtered-attachment-count").textContent', content)
        self.assertIn('item.querySelector(".filtered-first-date").textContent', content)
        self.assertIn('item.setAttribute("data-sort-messages", matchingMessages.length)', content)
        self.assertIn('item.setAttribute("data-sort-attachments", filteredAttachments)', content)

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
        self.assertIn('href="calls.html">Call history</a>', content)

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
        self.assertIn('["previous local day","2024-01-01","21:00",0]', search_content)


if __name__ == '__main__':
    unittest.main()
