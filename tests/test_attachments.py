import json
import os
import tempfile
import unittest

from html_pages import build_attachments_page


def attachment_message(index, stamp, filename, mime_type='image/png'):
    return {
        'id': index,
        'guid': f'att-{index}',
        'text': f'msg {index}',
        'date': stamp,
        'is_from_me': index % 2 == 0,
        'sender': 'Me' if index % 2 == 0 else 'Alex',
        'chat_id': ('phone', '15551234567'),
        'attachments': [{
            'filename': filename,
            'mime_type': mime_type,
            'file_path': f'/var/mobile/Media/Photos/{filename}',
            'file_size': 1024,
        }],
    }


def no_attachment_message(index, stamp):
    return {
        'id': index,
        'guid': f'plain-{index}',
        'text': f'plain {index}',
        'date': stamp,
        'is_from_me': True,
        'sender': 'Me',
        'chat_id': ('phone', '15551234567'),
        'attachments': [],
    }


class AttachmentPageTests(unittest.TestCase):
    def setUp(self):
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.output_dir = self.temporary_dir.name
        self.attachment_folder = os.path.join(self.output_dir, 'atts')
        os.makedirs(self.attachment_folder)

    def tearDown(self):
        self.temporary_dir.cleanup()

    def write_photo(self, filename):
        with open(os.path.join(self.attachment_folder, filename), 'wb') as handle:
            handle.write(b'\x89PNG\r\n\x1a\nfake bytes')

    def page_content(self, entries):
        path = build_attachments_page(
            entries,
            self.output_dir,
            self.attachment_folder,
            {},
            'America/New_York',
            (self.attachment_folder,),
        )
        with open(path, encoding='utf-8') as page:
            return page.read()

    def test_empty_attachments_page(self):
        content = self.page_content([
            ('Alex', 'alex', [no_attachment_message(1, '2024-01-01 08:30:00')]),
        ])

        self.assertIn('No attachments were found in the extracted backups.', content)
        self.assertNotIn('<script>', content)
        self.assertNotIn('id="attGrid"', content)

    def test_attachment_card_links_back_to_the_conversation_message(self):
        self.write_photo('pic.png')
        self.write_photo('sam.png')
        self_message = attachment_message(1, '2024-01-02 09:00:00', 'pic.png')
        sam_message = attachment_message(3, '2024-01-04 09:00:00', 'sam.png')
        sam_message['sender'] = 'Sam'
        content = self.page_content([
            ('Alex', 'alex', [self_message, sam_message]),
        ])

        self.assertIn('data-date="2024-01-02"', content)
        self.assertIn('data-time="04:00"', content)
        self.assertIn('data-media="img"', content)
        self.assertIn('href="alex.html?msg=0"', content)
        self.assertIn('View in conversation', content)
        self.assertIn('<div class="att-info">From Alex</div>', content)
        self.assertIn('<div class="att-info">Sam in Alex</div>', content)
        self.assertNotIn('Alex in Alex', content)
        self.assertIn('data-file="pic.png"', content)
        self.assertNotIn('<div class="att-file">', content)
        self.assertIn('<img loading="lazy"', content)
        self.assertIn('<a href="attachments.html">Attachments</a>', content)
        self.assertIn('1 attachments • 1 photos • 0 videos • 0 other files', content)

    def test_video_attachment_is_classified_as_video(self):
        content = self.page_content([
            ('Alex', 'alex', [
                attachment_message(1, '2024-01-02 09:00:00', 'clip.mov', 'video/quicktime'),
            ]),
        ])

        self.assertIn('data-media="video"', content)
        self.assertIn('href="alex.html?msg=0"', content)

    def test_plugin_payload_attachments_are_skipped(self):
        messages = [
            attachment_message(1, '2024-01-02 09:00:00', 'notes.pluginPayloadAttachment', 'application/octet-stream'),
            attachment_message(2, '2024-01-03 09:00:00', 'pic.png'),
        ]
        content = self.page_content([('Alex', 'alex', messages)])

        self.assertNotIn('notes.pluginPayloadAttachment', content)
        self.assertIn('data-date="2024-01-03"', content)
        self.assertIn('1 attachments • 1 photos', content)

    def test_cards_render_in_chronological_order(self):
        messages = [
            attachment_message(1, '2024-03-05 12:00:00', 'late.png'),
            attachment_message(2, '2024-01-02 12:00:00', 'early.png'),
            attachment_message(3, '2024-02-04 12:00:00', 'middle.png'),
        ]
        content = self.page_content([('Alex', 'alex', messages)])

        first = content.index('data-seq="0"')
        second = content.index('data-seq="1"')
        third = content.index('data-seq="2"')
        self.assertLess(first, second)
        self.assertLess(second, third)
        self.assertIn('early.png', content[first:second])
        self.assertIn('middle.png', content[second:third])
        self.assertIn('late.png', content[third:])

    def test_attachments_page_batches_long_lists(self):
        messages = [
            attachment_message(i, f'2024-01-{(i % 28) + 1:02d} 12:00:00', f'photo-{i}.png')
            for i in range(1, 2006)
        ]
        content = self.page_content([('Alex', 'alex', messages)])

        self.assertEqual(content.count('<div class="att-card" '), 2000)
        self.assertIn('id="loadMoreSentinel"', content)
        self.assertIn('Load 2,000 more attachments', content)
        self.assertIn('BATCH_SIZE = 2000', content)
        self.assertIn('const totalAttachments = 2005;', content)
        self.assertIn('2,005 attachments •', content)

        marker = 'id="pendingData">'
        start = content.index(marker) + len(marker) + 1
        end = content.index('</script>', start)
        payload = content[start:end]
        pending = json.loads(payload)

        self.assertEqual(len(pending), 5)
        self.assertEqual(pending[0]['d'], '2024-01-28')
        self.assertIn('photo-1875.png', pending[0]['s'])
        self.assertNotIn('<', payload)
        self.assertIn('\\u003c', payload)

        dates_marker = 'id="allDates">'
        dates_start = content.index(dates_marker) + len(dates_marker) + 1
        dates_end = content.index('</script>', dates_start)
        all_dates = json.loads(content[dates_start:dates_end])
        self.assertIn('2024-01-01', all_dates)
        self.assertIn('2024-01-28', all_dates)

    def test_attachments_page_js_features(self):
        messages = [
            attachment_message(i, f'2024-01-{(i % 28) + 1:02d} 12:00:00', f'photo-{i}.png')
            for i in range(1, 2006)
        ]
        content = self.page_content([('Alex', 'alex', messages)])

        self.assertIn('function entryMatches(m)', content)
        self.assertIn('function renderCards(entries)', content)
        self.assertIn('attTemplate.innerHTML = markup;', content)
        self.assertIn('let pending = pendingDataEl ? JSON.parse(pendingDataEl.textContent) : [];', content)
        self.assertIn('pending = rest.concat(pending);', content)
        self.assertIn('if (pending.length) renderChunk(BATCH_SIZE);', content)
        self.assertNotIn('while (pending.length)', content)
        self.assertIn('IntersectionObserver', content)
        self.assertIn('rootMargin: "400px"', content)
        self.assertIn('function filterAtt(materialize)', content)
        self.assertIn('"Showing " + visible.toLocaleString() + " of " + totalAttachments.toLocaleString() + " attachments"', content)
        self.assertIn('if (noFilters) visible = totalAttachments;', content)
        self.assertIn('while (pending.length && attCards.length < BATCH_SIZE) { renderChunk(BATCH_SIZE); }', content)
        self.assertIn('displayCount = Math.min(attCards.length, BATCH_SIZE);', content)
        self.assertIn('displayCount += entries.length;', content)
        self.assertIn('function applyWindow()', content)
        self.assertIn('.att-card.window-hidden { display: none; }', content)
        self.assertIn('function setAttDateRange(start, end)', content)
        self.assertIn('randomDayButton.addEventListener', content)
        self.assertIn('randomWeekButton.addEventListener', content)
        self.assertIn('clearFiltersButton.addEventListener', content)
        self.assertIn('pending.reverse();', content)
        self.assertIn('Number(a.dataset.seq)', content)
        self.assertIn('function closeLightbox()', content)
        self.assertIn('" • " + card.dataset.file', content)
        self.assertIn('bigImage.src = media.src;', content)
        self.assertIn('if (event.key === "Escape") closeLightbox();', content)
        self.assertIn('<button type="button" id="orderButton">Newest first</button>', content)
        self.assertIn('<option value="img">Photos only</option>', content)
        self.assertIn('<button type="button" id="clearFiltersButton">Clear filters</button>', content)

    def test_conversation_pages_link_to_attachments_page(self):
        from html_pages import build_html

        path = build_html('Alex', [no_attachment_message(1, '2024-01-01 08:30:00')], self.output_dir)
        with open(path, encoding='utf-8') as page:
            content = page.read()

        self.assertIn('<a href="attachments.html">Attachments</a>', content)


if __name__ == '__main__':
    unittest.main()
