"""Regenerate the fictional static website in Example Output."""

import os

from html_pages import (
    build_attachments_page,
    build_birthdays,
    build_birthday_wishes,
    build_call_history,
    build_conversation_entries,
    build_html,
    build_index,
    build_search_index,
    collect_conversation_metrics,
    summarize_messages,
)
from time_zone_utils import DEFAULT_TIME_ZONE


def _message(message_id, text, timestamp, is_from_me, sender, chat_id, participants=()):
    return {
        'id': message_id,
        'guid': f'example-{message_id}',
        'text': text,
        'date': timestamp,
        'is_from_me': is_from_me,
        'sender': sender,
        'chat_id': chat_id,
        'group_participants': list(participants),
        'attachments': [],
    }


def _example_data():
    conversations = {}
    next_message_id = 1

    def add_conversation(name, chat_id, messages, participants=()):
        nonlocal next_message_id
        records = []
        for timestamp, text, is_from_me, sender in messages:
            records.append(
                _message(
                    next_message_id,
                    text,
                    timestamp,
                    is_from_me,
                    sender,
                    chat_id,
                    participants,
                )
            )
            next_message_id += 1
        conversations[chat_id] = {'name': name, 'messages': records}

    contacts = [
        (
            'Ava Patel',
            '5550100103',
            [
                ('2022-06-10 13:00:00', 'Happy birthday, Ava! Hope it is a great one.', True, 'Me'),
                ('2022-06-10 13:14:00', 'Thank you! We are having cake tonight.', False, 'Ava'),
                ('2023-06-10 14:00:00', 'Happy birthday! Ready for another year of adventures?', True, 'Me'),
                ('2024-06-10 13:30:00', 'Happy birthday, Ava! Dinner is on me this weekend.', True, 'Me'),
                ('2024-06-10 13:42:00', 'You remembered! Saturday sounds perfect.', False, 'Ava'),
                ('2025-08-19 18:20:00', 'I sent you the hiking photos.', False, 'Ava'),
                ('2025-08-19 18:24:00', 'These came out great. Thanks!', True, 'Me'),
            ],
        ),
        (
            'Jordan Lee',
            '5550100102',
            [
                ('2022-09-14 13:00:00', 'Happy birthday, Jordan!', True, 'Me'),
                ('2022-09-14 13:10:00', 'Thanks! Coffee soon?', False, 'Jordan'),
                ('2023-06-10 12:00:00', 'Happy birthday! Hope today brings good things.', False, 'Jordan'),
                ('2023-09-14 14:00:00', 'Happy birthday! Hope the new job is treating you well.', True, 'Me'),
                ('2024-06-10 12:30:00', 'Happy birthday! Sending you a big virtual cake.', False, 'Jordan'),
                ('2024-09-14 12:00:00', 'Happy birthday, Jordan! Let us celebrate soon.', True, 'Me'),
                ('2025-06-11 14:05:00', 'The concert was fantastic.', True, 'Me'),
                ('2025-06-11 14:16:00', 'Agreed. Next time we should get seats closer.', False, 'Jordan'),
            ],
        ),
        (
            'Maya Chen',
            '5550100101',
            [
                ('2022-02-21 13:00:00', 'Happy birthday, Maya! Hope you get to relax today.', True, 'Me'),
                ('2022-02-21 13:20:00', 'Thank you! Relaxing with a book right now.', False, 'Maya'),
                ('2023-06-10 11:30:00', 'Happy birthday! Hope you have a lovely day.', False, 'Maya'),
                ('2023-02-21 12:00:00', 'Happy birthday! Wishing you a brilliant year.', True, 'Me'),
                ('2024-02-21 12:15:00', 'Happy birthday, Maya! Let me know when you are free for lunch.', True, 'Me'),
                ('2024-06-10 10:00:00', 'Happy birthday! Hope we can catch up soon.', False, 'Maya'),
                ('2025-06-10 11:30:00', 'Happy birthday! Hope your day is off to a great start.', False, 'Maya'),
                ('2025-06-10 11:42:00', 'It is now. Thanks for the message!', True, 'Me'),
            ],
        ),
        (
            'Noah Brooks',
            '5550100104',
            [
                ('2022-11-03 13:00:00', 'Happy birthday, Noah!', True, 'Me'),
                ('2022-11-03 13:17:00', 'Thanks! I am celebrating with family.', False, 'Noah'),
                ('2023-06-10 15:30:00', 'Happy birthday! Save me a slice of cake.', False, 'Noah'),
                ('2023-11-03 12:00:00', 'Happy birthday! Hope the year ahead is a good one.', True, 'Me'),
                ('2024-11-03 12:00:00', 'Happy birthday, Noah! Have an excellent day.', True, 'Me'),
                ('2025-02-21 20:02:00', 'The game starts at seven.', False, 'Noah'),
                ('2025-02-21 20:10:00', 'I will be there. See you soon!', True, 'Me'),
            ],
        ),
        (
            'Sofia Reyes',
            '5550100105',
            [
                ('2022-03-14 13:00:00', 'Happy birthday, Sofia!', True, 'Me'),
                ('2022-03-14 13:09:00', 'Thank you! The flowers are beautiful.', False, 'Sofia'),
                ('2023-03-14 12:00:00', 'Happy birthday! Hope you have a wonderful day.', True, 'Me'),
                ('2024-03-14 12:00:00', 'Happy birthday, Sofia! Sending lots of good wishes.', True, 'Me'),
                ('2025-03-14 12:00:00', 'Happy birthday! Hope we can celebrate together soon.', True, 'Me'),
                ('2025-03-14 12:22:00', 'Absolutely! Thanks for always remembering.', False, 'Sofia'),
                ('2025-06-10 16:00:00', 'Happy birthday! Hope your day is full of sunshine.', False, 'Sofia'),
            ],
        ),
    ]

    for name, phone_number, messages in contacts:
        add_conversation(name, ('phone', phone_number), messages)

    add_conversation(
        'Weekend Crew',
        ('group', 'example-weekend-crew'),
        [
            ('2023-06-10 15:00:00', 'Happy birthday! We saved you a seat at dinner.', False, 'Ava Patel'),
            ('2023-06-10 15:06:00', 'Thank you all! See you tonight.', True, 'Me'),
            ('2023-06-10 16:20:00', 'I will bring dessert.', False, 'Jordan Lee'),
            ('2024-06-10 16:00:00', 'Happy birthday! The whole crew is cheering for you.', False, 'Sofia Reyes'),
            ('2024-06-10 16:08:00', 'Best group chat ever. Thanks!', True, 'Me'),
            ('2024-08-19 17:00:00', 'Park picnic this Sunday?', False, 'Maya Chen'),
            ('2024-08-19 17:12:00', 'Count me in.', True, 'Me'),
            ('2025-06-10 17:30:00', 'Happy birthday! Your gift is waiting at dinner.', False, 'Noah Brooks'),
            ('2025-06-10 17:35:00', 'You did not have to! Thank you.', True, 'Me'),
        ],
        ('Me', 'Ava Patel', 'Jordan Lee', 'Maya Chen', 'Noah Brooks', 'Sofia Reyes'),
    )
    add_conversation(
        'Book Club',
        ('group', 'example-book-club'),
        [
            ('2023-03-05 12:00:00', 'I finished the mystery novel. What a twist!', True, 'Me'),
            ('2023-03-05 12:13:00', 'I guessed the ending halfway through.', False, 'Maya Chen'),
            ('2023-03-05 12:24:00', 'Next month let us pick something lighter.', False, 'Ava Patel'),
            ('2024-04-12 13:00:00', 'The new reading list is ready.', False, 'Jordan Lee'),
            ('2024-04-12 13:08:00', 'I vote for the travel memoir.', True, 'Me'),
            ('2025-01-18 14:00:00', 'Reminder: book club is at my place on Friday.', False, 'Sofia Reyes'),
            ('2025-01-18 14:10:00', 'Perfect, I will bring snacks.', True, 'Me'),
        ],
        ('Me', 'Ava Patel', 'Jordan Lee', 'Maya Chen', 'Sofia Reyes'),
    )
    add_conversation(
        'Family Chat',
        ('group', 'example-family-chat'),
        [
            ('2022-12-24 15:00:00', 'What time should we arrive tomorrow?', True, 'Me'),
            ('2022-12-24 15:12:00', 'Lunch is at one. Bring your appetite!', False, 'Noah Brooks'),
            ('2023-12-24 16:00:00', 'Happy holidays, everyone!', False, 'Ava Patel'),
            ('2023-12-24 16:07:00', 'Happy holidays! See you tomorrow.', True, 'Me'),
            ('2024-07-04 13:00:00', 'Fireworks start after sunset.', False, 'Jordan Lee'),
            ('2024-07-04 13:10:00', 'I will bring lemonade.', True, 'Me'),
            ('2025-05-25 12:00:00', 'Sunday brunch was a great idea.', False, 'Maya Chen'),
        ],
        ('Me', 'Ava Patel', 'Jordan Lee', 'Maya Chen', 'Noah Brooks'),
    )

    calls = [
        {'date': '2025-06-10 11:30:00', 'contact': 'Maya Chen', 'address': '5550100101', 'phone_number': '5550100101', 'direction': 'Outgoing', 'duration': 245},
        {'date': '2025-06-11 14:05:00', 'contact': 'Jordan Lee', 'address': '5550100102', 'phone_number': '5550100102', 'direction': 'Incoming', 'duration': 98},
        {'date': '2025-08-19 18:20:00', 'contact': 'Ava Patel', 'address': '5550100103', 'phone_number': '5550100103', 'direction': 'Outgoing', 'duration': 512},
        {'date': '2025-02-21 20:02:00', 'contact': 'Noah Brooks', 'address': '5550100104', 'phone_number': '5550100104', 'direction': 'Incoming', 'duration': 76},
        {'date': '2025-03-14 12:00:00', 'contact': 'Sofia Reyes', 'address': '5550100105', 'phone_number': '5550100105', 'direction': 'Outgoing', 'duration': 183},
        {'date': '2025-06-12 09:30:00', 'contact': 'Maya Chen', 'address': '5550100101', 'phone_number': '5550100101', 'direction': 'Missed', 'duration': 0},
    ]
    return conversations, calls


def main():
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Example Output')
    os.makedirs(output_dir, exist_ok=True)

    conversations, calls = _example_data()
    entries = [
        (display_name, filename, conversations[key]['messages'])
        for key, display_name, filename in build_conversation_entries(conversations)
    ]
    all_messages = [
        message
        for _, _, messages in entries
        for message in messages
    ]
    overall_stats = summarize_messages(all_messages, DEFAULT_TIME_ZONE)
    overall_stats['conversations'] = len(entries)

    for display_name, filename, messages in entries:
        build_html(display_name, messages, output_dir, output_filename=filename)
    build_attachments_page(entries, output_dir, None, {}, DEFAULT_TIME_ZONE, ())
    conversation_metrics = collect_conversation_metrics(entries, DEFAULT_TIME_ZONE)
    build_index(
        entries,
        output_dir,
        overall_stats,
        DEFAULT_TIME_ZONE,
        calls=calls,
        conversation_metrics=conversation_metrics,
    )
    build_search_index(
        entries,
        output_dir,
        DEFAULT_TIME_ZONE,
        conversation_metrics=conversation_metrics,
    )
    build_birthdays(entries, output_dir, DEFAULT_TIME_ZONE)
    build_birthday_wishes(entries, output_dir, DEFAULT_TIME_ZONE)
    build_call_history(calls, output_dir, DEFAULT_TIME_ZONE)
    print(f'Regenerated fictional example website: {output_dir}')


if __name__ == '__main__':
    main()
