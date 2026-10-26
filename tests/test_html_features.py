import json
import os
import tempfile
import unittest
from pathlib import Path

from html_pages import (
    build_birthdays,
    build_birthday_wishes,
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

    def test_conversation_page_supports_jump_from_attachments_page(self):
        path = build_html('Alex', self.messages, self.output_dir)

        with open(path, encoding='utf-8') as page:
            content = page.read()

        self.assertIn('data-msg-idx="0"', content)
        self.assertIn('data-msg-idx="2"', content)
        self.assertIn('data-msg-idx=\\"" + m.i + "\\"', content)
        self.assertIn('<section class="jump-bar" id="jumpBar" hidden>', content)
        self.assertIn('id="showAllMessagesButton"', content)
        self.assertIn('const jumpParam = messageQuery.get("msg");', content)
        self.assertIn('const renderLimit = Math.min(totalMessages, jumpIndex + 26);', content)
        self.assertIn('el.classList.toggle("jump-hidden", idx < lowIndex || idx > highIndex);', content)
        self.assertIn('jumpTarget.classList.add("jump-target");', content)
        self.assertIn('jumpTarget.scrollIntoView({ block: "center" });', content)
        self.assertIn('.message.jump-hidden { display: none; }', content)
        self.assertIn('.message.jump-target .bubble', content)
        self.assertIn('<a href="attachments.html">Attachments</a>', content)

    def test_dark_mode_toggle_shared_across_pages(self):
        path = build_html('Alex', self.messages, self.output_dir)
        with open(path, encoding='utf-8') as page:
            content = page.read()

        self.assertIn('<button type="button" id="themeToggle" aria-label="Toggle dark mode" title="Toggle dark mode">☾</button>', content)
        self.assertIn('html.dark body { background: #121417; color: #e5e7eb; }', content)
        self.assertIn(
            'html.dark .stat, html.dark .stats-table, html.dark .line-chart, '
            'html.dark .stat-card, html.dark .filters, html.dark .table-wrap, '
            'html.dark .birthday-search { background: #1c2025; border-color: #3a414d; }',
            content,
        )
        self.assertIn('html.dark .chart-gridline { stroke: #3a414d; }', content)
        self.assertIn('html.dark td { color: #d1d9e2; }', content)
        self.assertIn('html.dark .stat-value { color: #60a5fa; }', content)
        self.assertIn(
            'html.dark .stat span, html.dark .filters label, html.dark .birthday-search label, '
            'html.dark .message-filters label, html.dark .search-filters label { color: #9ca3af; }',
            content,
        )
        self.assertIn('const themeKey = "imsg-theme";', content)
        self.assertIn('document.documentElement.classList.toggle("dark", mode === "dark");', content)
        self.assertIn('localStorage.setItem(themeKey, mode)', content)

        index_stats = summarize_messages(self.messages)
        index_stats['conversations'] = 1
        for path in (
            build_index([], self.output_dir, index_stats),
            build_birthdays([], self.output_dir),
        ):
            with open(path, encoding='utf-8') as page:
                content = page.read()
            self.assertIn('<button type="button" id="themeToggle" aria-label="Toggle dark mode" title="Toggle dark mode">☾</button>', content)
            self.assertIn('document.documentElement.classList.toggle("dark"', content)

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
        self.assertIn('<button type="button" id="clearFiltersButton">Clear filters</button>\n        <div id="messageResultCount" class="message-result-count" aria-live="polite"></div>', content)

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
        self.assertIn(f'<img loading="lazy" src="{Path(sticker_path).as_uri()}"', content)

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
            ['hello </script>', '2024-01-01', '03:30', 0, True, 'Me'],
            ['reply', '2024-01-01', '03:45', 0, False, 'Alex'],
            ['next year', '2025-02-03', '05:15', 0, True, 'Me'],
        ]])
        self.assertIn(
            'JSON.parse(document.getElementById("searchMessageData").textContent)',
            content,
        )
        self.assertIn('new URLSearchParams(window.location.search)', content)
        self.assertIn('link.href = link.dataset.conversationFile', content)
        self.assertIn('href="calls.html">Call history</a>', content)
        self.assertIn('<h2 id="directConversationsHeading">Conversations</h2>', content)
        self.assertIn('<h2 id="groupConversationsHeading">Group conversations</h2>', content)
        self.assertNotIn('<details class="conversation-stats', content)
        self.assertIn('data-sort-key="busiest-day"', content)
        self.assertIn('data-sort-key="longest-gap"', content)
        self.assertIn('data-sort-key="top-participant"', content)
        self.assertIn('data-sort-key="participants"', content)
        self.assertIn('table.tBodies[0].appendChild(row)', content)
        self.assertIn('data-sort-reply-sent=', content)
        self.assertIn('Median sent reply', content)
        self.assertIn('Longest active streak', content)

    def test_search_page_splits_direct_and_group_tables(self):
        group_messages = [
            {
                **self.messages[0],
                'id': 4,
                'chat_id': ('group', 'chat-1'),
                'group_participants': ['Alex', 'Jordan'],
                'attachments': [{'filename': 'photo.jpg'}],
            }
        ]
        conversations = [
            ('Alex', 'Alex', self.messages),
            ('Weekend group', 'Weekend_group', group_messages),
        ]
        path = build_search_index(conversations, self.output_dir)

        with open(path, encoding='utf-8') as page:
            content = page.read()

        direct_table = content.split('<tbody id="conversationList">', 1)[1].split('</tbody>', 1)[0]
        group_table = content.split('<tbody id="groupConversationList">', 1)[1].split('</tbody>', 1)[0]
        self.assertIn('>Alex</a>', direct_table)
        self.assertNotIn('Weekend group', direct_table)
        self.assertIn('>Weekend group</a>', group_table)
        self.assertIn('Alex, Jordan', group_table)
        self.assertIn('filtered-attachment-count">1</span>', group_table)
        self.assertIn('data-sort-top-participant="0"', group_table)
        self.assertNotIn('Median sent reply', group_table)
        self.assertIn('data-sort-key="reply-sent"', content)
        self.assertIn('data-sort-key="participants"', content)
        self.assertLess(content.index('id="conversationList"'), content.index('id="groupConversationList"'))

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
        self.assertIn('["hello \\u003c/script\\u003e","2024-01-01","03:30",2,true,"Me"]', content)
        self.assertIn('messages.filter(function(message)', content)
        self.assertIn('message[0].includes(messageTerm)', content)
        self.assertIn('message[3] || 0', content)
        self.assertIn('item.querySelector(".filtered-message-count").textContent', content)
        self.assertIn('item.querySelector(".filtered-attachment-count").textContent', content)
        self.assertIn('item.querySelector(".filtered-first-date").textContent', content)
        self.assertIn('item.setAttribute("data-sort-messages", matchingMessages.length)', content)
        self.assertIn('item.setAttribute("data-sort-attachments", filteredAttachments)', content)

    def test_birthdays_calendar_uses_outgoing_direct_greetings_and_shows_conflicts(self):
        conversations = [
            ('Alex <Friend>', 'Alex_Friend', [
                {
                    **self.messages[0],
                    'text': 'Happy Birthday!',
                    'date': '2022-06-10 10:00:00',
                    'is_from_me': True,
                },
                {
                    **self.messages[1],
                    'text': 'happy birthday again',
                    'date': '2024-06-10 10:00:00',
                    'is_from_me': True,
                },
                {
                    **self.messages[2],
                    'text': 'Happy Birthday',
                    'date': '2025-07-12 10:00:00',
                    'is_from_me': True,
                },
                {
                    **self.messages[2],
                    'text': "Loved “Happy birthday to you and many many many more. I can't wait to celebrate.”",
                    'date': '2026-07-12 10:00:00',
                    'is_from_me': True,
                },
                {
                    **self.messages[1],
                    'text': 'Happy Birthday to you',
                    'date': '2025-08-01 10:00:00',
                    'is_from_me': False,
                },
                {
                    **self.messages[0],
                    'text': 'Liked "Happy Birthday"',
                    'date': '2025-09-01 10:00:00',
                    'is_from_me': True,
                },
                {
                    **self.messages[0],
                    'text': 'I sent "Happy Birthday" last year',
                    'date': '2025-10-01 10:00:00',
                    'is_from_me': True,
                },
            ]),
            ('Group chat', 'Group_chat', [{
                **self.messages[0],
                'text': 'Happy Birthday',
                'date': '2025-09-01 10:00:00',
                'is_from_me': True,
                'chat_id': ('group', 12),
            }]),
        ]

        path = build_birthdays(conversations, self.output_dir)

        with open(path, encoding='utf-8') as page:
            content = page.read()
        self.assertIn('<title>Inferred birthdays</title>', content)
        self.assertIn(
            'href="Alex_Friend.html?dateFrom=2024-06-10&amp;dateTo=2024-06-10"',
            content,
        )
        self.assertIn(
            'title="2 supporting messages; observed in 2022, 2024; open 2024-06-10"',
            content,
        )
        self.assertIn(
            'href="Alex_Friend.html?dateFrom=2025-07-12&amp;dateTo=2025-07-12"',
            content,
        )
        self.assertIn(
            'title="1 supporting message; observed in 2025; open 2025-07-12"',
            content,
        )
        self.assertIn('Alex &lt;Friend&gt;', content)
        self.assertEqual(content.count('href="Alex_Friend.html?'), 2)
        self.assertIn('grid-template-columns: repeat(2, minmax(0, 1fr))', content)
        self.assertIn('@media (max-width: 640px)', content)
        self.assertIn('@media (max-width: 640px)', content)
        self.assertNotIn('href="Group_chat.html"', content)
        self.assertIn(
            'class="share-link" href="birthday_wishes.html?date=2024-06-10" '
            'title="Share birthday wishes for 2024-06-10"',
            content,
        )

    def test_birthday_wishes_searches_incoming_direct_and_group_messages(self):
        conversations = [
            ('Alex', 'Alex', [
                {
                    **self.messages[1],
                    'text': 'Happy birthday to you and many many many more!',
                    'date': '2022-06-10 10:00:00',
                    'sender': 'Alex Contact',
                    'is_from_me': False,
                },
                {
                    **self.messages[1],
                    'text': 'Happy Birthday!',
                    'date': '2024-06-10 10:00:00',
                    'sender': 'Alex Contact',
                    'is_from_me': False,
                },
                {
                    **self.messages[0],
                    'text': 'Happy Birthday',
                    'date': '2025-06-10 10:00:00',
                    'sender': 'Me',
                    'is_from_me': True,
                },
                {
                    **self.messages[1],
                    'text': '“Happy birthday!”',
                    'date': '2025-06-10 10:00:00',
                    'sender': 'Quoted Contact',
                    'is_from_me': False,
                },
            ]),
            ('Family group', 'Family_group', [{
                **self.messages[1],
                'text': 'Happy birthday!',
                'date': '2023-06-10 10:00:00',
                'sender': 'Sam',
                'is_from_me': False,
                'chat_id': ('group', 'family'),
            }]),
        ]

        path = build_birthday_wishes(conversations, self.output_dir)

        with open(path, encoding='utf-8') as page:
            content = page.read()
        self.assertIn('<title>Birthday wishes</title>', content)
        self.assertIn('id="birthdayDate" type="date" required', content)
        self.assertIn('"Alex Contact","Alex","2022-06-10"', content)
        self.assertIn('"Alex Contact","Alex","2024-06-10"', content)
        self.assertIn('"Sam","Family_group","2023-06-10"', content)
        self.assertNotIn('"Me","Alex","2025-06-10"', content)
        self.assertNotIn('"Quoted Contact","Alex","2025-06-10"', content)
        self.assertIn('document.createElement("details")', content)
        self.assertIn('document.createElement("summary")', content)
        self.assertIn('heading.textContent = sender + " (" + senderWishes.length + " wishes)"', content)
        self.assertIn('wish[2].slice(5) === monthDay', content)
        self.assertIn('link.href = encodeURIComponent(wish[1]) + ".html?"', content)
        self.assertIn('const shareParams = new URLSearchParams(location.search);', content)
        self.assertIn(
            'if (shareParams.get("date")) { birthdayDateInput.value = shareParams.get("date"); '
            'showBirthdayWishes(shareParams.get("date")); }',
            content,
        )

    def test_index_has_per_year_activity_and_overall_stats(self):
        stats = summarize_messages(self.messages)
        stats['conversations'] = 1
        messages = [dict(message) for message in self.messages]
        messages[0]['attachments'] = [{'mime_type': 'image/jpeg'}]
        messages[1]['attachments'] = [{'mime_type': 'video/mp4'}]
        messages[2]['attachments'] = [{'mime_type': 'audio/mp4'}]
        calls = [
            {'date': '2024-01-01 17:00:00', 'direction': 'Incoming', 'duration': 120},
            {'date': '2024-02-01 17:00:00', 'direction': 'Missed', 'duration': 0},
        ]
        path = build_index([('Alex', 'Alex', messages)], self.output_dir, stats, calls=calls)

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
        self.assertIn('Archive overview', content)
        self.assertIn('Average messages per active day', content)
        self.assertIn('Busiest month', content)
        self.assertIn('Messages by year', content)
        self.assertIn('Messages by month', content)
        self.assertIn('Messages by day of week', content)
        self.assertIn('Messages by hour of day', content)
        self.assertEqual(content.count('class="line-chart"'), 6)
        self.assertIn('aria-label="Messages by year"', content)
        self.assertIn('aria-label="Messages by month"', content)
        self.assertIn('aria-label="Messages by day of week"', content)
        self.assertIn('aria-label="Messages by hour of day"', content)
        self.assertIn('aria-label="Calls by year"', content)
        self.assertIn('aria-label="Calls by month"', content)
        self.assertIn('<polyline class="chart-line"', content)
        self.assertIn('<circle class="chart-point"', content)
        self.assertIn('class="chart-interaction"', content)
        self.assertIn('class="chart-focus-point"', content)
        self.assertIn('class="chart-tooltip"', content)
        self.assertIn('addEventListener("pointermove"', content)
        self.assertIn('aria-valuetext', content)
        self.assertIn('event.key === "ArrowRight"', content)
        self.assertIn('chart-gridline', content)
        self.assertIn('1 message</title>', content)
        self.assertIn('January: 2 messages</title>', content)
        self.assertIn('February: 1 message</title>', content)
        self.assertNotIn('2024-01: 2 messages</title>', content)
        self.assertNotIn('bar-list', content)
        self.assertNotIn('Conversation-level statistics', content)
        self.assertNotIn('data-conversation-sort=', content)
        self.assertNotIn('conversationStatsTable', content)
        self.assertIn('Photos and images</td><td>1', content)
        self.assertIn('Videos</td><td>1', content)
        self.assertIn('Audio</td><td>1', content)
        self.assertIn('Call statistics', content)
        self.assertIn('Calls by year', content)
        self.assertIn('Calls by month', content)
        self.assertIn('Total calls</span></div>', content)
        self.assertIn('>1</strong><span>Missed calls', content)
        self.assertIn('2m</strong><span>Average duration of non-missed calls', content)

    def test_index_handles_empty_conversation_and_call_statistics(self):
        stats = summarize_messages([])
        stats['conversations'] = 0
        path = build_index([], self.output_dir, stats)

        with open(path, encoding='utf-8') as page:
            content = page.read()

        self.assertIn('No dated messages are available.', content)
        self.assertIn('No call records are available.', content)
        self.assertIn('0</strong><span>Active days</span>', content)
        self.assertIn('0.0</strong><span>Average messages per active day</span>', content)

    def test_conversation_page_restores_incoming_search_filters(self):
        path = build_html('Alex', self.messages, self.output_dir)

        with open(path, encoding='utf-8') as page:
            content = page.read()

        self.assertIn('messageQueryFields', content)
        self.assertNotIn('backToSearch', content)
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
        self.assertIn('["previous local day","2024-01-01","21:00",0,false,"Alex"]', search_content)

    def test_large_conversations_load_messages_in_2000_message_batches(self):
        messages = [
            {
                'id': index,
                'text': f'message {index}',
                'date': '2024-01-01 08:30:00',
                'is_from_me': index % 2 == 0,
                'sender': 'Me' if index % 2 == 0 else 'Alex',
                'chat_id': ('phone', '15551234567'),
                'attachments': [],
            }
            for index in range(5005)
        ]
        path = build_html('Bulk', messages, self.output_dir)

        with open(path, encoding='utf-8') as page:
            content = page.read()

        # The first batch renders inline HTML; the rest is compact JSON.
        self.assertEqual(content.count('<div class="message '), 2000)
        self.assertIn('<div class="load-more" id="loadMoreSentinel">', content)
        self.assertIn('<button type="button" id="loadMoreButton">Load 2,000 more messages</button>', content)
        self.assertNotIn('Loading more messages', content)
        self.assertIn('const BATCH_SIZE = 2000;', content)
        self.assertIn('function highlightText(source, termHtml)', content)
        self.assertIn('mark { background: #fde68a; color: inherit; padding: 0 1px; border-radius: 3px; }', content)
        self.assertIn('const messageFilters = ["messageTextSearch"', content)
        self.assertIn('IntersectionObserver', content)
        self.assertIn('filterMessages(true);', content)
        # Filtering must render only the entries matching the filter, never the
        # whole conversation, so random day/week/click-to-filter stays fast.
        self.assertIn('function renderEntries(entries)', content)
        self.assertIn('function entryMatches(m)', content)
        # Batch loads must keep non-matching entries in the pending queue so
        # later random day/week picks still find their messages.
        self.assertIn('pending = rest.concat(pending);', content)
        self.assertNotIn('renderEntries(slice.filter(entryMatches));', content)
        self.assertIn('renderEntries(matching);', content)
        # Clearing filters must not materialize 100k+ messages at once (crashes
        # the browser): it renders one chunk and streams the rest on scroll.
        self.assertIn('if (activeCriteria.noFilters) {', content)
        self.assertIn('if (pending.length) renderChunk(BATCH_SIZE);', content)
        self.assertNotIn('while (pending.length) renderChunk(BATCH_SIZE);', content)
        # Huge conversations: push.apply throws RangeError past ~65k args,
        # which kills all filtering; reassignment avoids the argument limit.
        self.assertIn('let pending =', content)
        self.assertIn('pending = rest;', content)
        self.assertNotIn('Array.prototype.push.apply', content)

        payload_start = content.index('id="pendingData">') + len('id="pendingData">')
        payload_end = content.index('</script>', payload_start)
        # Raw '<' in the JSON block (e.g. attachment markup) must be escaped
        # as \u003c so the script element can never terminate early.
        self.assertNotIn('<', content[payload_start:payload_end])
        pending = json.loads(content[payload_start:payload_end])
        self.assertEqual(len(pending), 3005)
        self.assertEqual(pending[0]['x'], 'message 2000')
        self.assertEqual(pending[0]['i'], 2000)
        self.assertEqual(pending[4]['d'], '2024-01-01')

        dates_start = content.index('id="allDates">') + len('id="allDates">')
        dates_end = content.index('</script>', dates_start)
        self.assertEqual(json.loads(content[dates_start:dates_end]), ['2024-01-01'])

    def test_small_conversations_have_no_lazy_payload(self):
        path = build_html('Alex', self.messages, self.output_dir)

        with open(path, encoding='utf-8') as page:
            content = page.read()

        self.assertNotIn('id="pendingData"', content)
        self.assertNotIn('id="loadMoreSentinel"', content)
        self.assertIn('<strong id="messageCount">3</strong> messages', content)

    def test_conversation_header_shows_longest_silence(self):
        path = build_html('Alex', self.messages, self.output_dir)

        with open(path, encoding='utf-8') as page:
            content = page.read()

        self.assertIn('<span>Longest silence · 399d 1h (2024-01-01 → 2025-02-03)</span>', content)

    def test_index_has_fun_analytics_sections(self):
        messages = [dict(message) for message in self.messages]
        messages[1]['date'] = '2024-01-02 07:30:00'
        messages[2]['text'] = 'party time 🎉 🎉'
        stats = summarize_messages(messages)
        stats['conversations'] = 1
        path = build_index([('Alex', 'alex', messages)], self.output_dir, stats)

        with open(path, encoding='utf-8') as page:
            content = page.read()

        self.assertIn('<h2>Conversation habits</h2>', content)
        # 2024-01-01 (messages[0] 03:30 EST) + 2024-01-02 (messages[1] 02:30 EST) are consecutive
        self.assertIn(
            '<div class="stat"><strong>2</strong><span>Longest streak of consecutive active days</span></div>',
            content,
        )
        # hour 2 (messages[1] 02:30 EST) + hour 3 (messages[0] 03:30 EST) = 2
        self.assertIn(
            '<div class="stat"><strong>2</strong><span>Late-night messages (2–4 AM)</span></div>',
            content,
        )
        self.assertIn(
            '<div class="stat"><strong>🎉</strong><span>Most used emoji · 2 uses</span></div>',
            content,
        )
        self.assertIn('<h3>Most used emoji</h3>', content)
        self.assertIn('<td>🎉</td><td>2</td>', content)
        self.assertIn('<h3>Longest silences between messages</h3>', content)
        self.assertIn('<td>398d 2h</td><td>2024-01-02 → 2025-02-03</td>', content)
        self.assertIn(
            '<div class="stat"><strong><a href="alex.html">Alex</a></strong>'
            '<span>Longest silence · 398d 2h (2024-01-02 → 2025-02-03)</span></div>',
            content,
        )
        self.assertIn('<h2>Top Words and Senders by Year</h2>', content)
        self.assertIn('<h3>2024</h3>', content)
        self.assertIn('<h3>2025</h3>', content)
        self.assertIn('<div class="year-columns">', content)
        self.assertIn('<tr><td>hello</td><td>1</td></tr>', content)
        self.assertIn('<tr><td>reply</td><td>1</td></tr>', content)
        self.assertIn('<tr><td>party</td><td>1</td></tr>', content)
        self.assertIn('<tr><td>time</td><td>1</td></tr>', content)
        self.assertIn('<tr><td>Me</td><td>1</td></tr>', content)
        self.assertIn('<tr><td>Alex</td><td>1</td></tr>', content)


if __name__ == '__main__':
    unittest.main()
