import bot

assert bot.parse_destinations('@public https://t.me/public -1001234567890 https://t.me/+private https://t.me/c/123/45') == [
    '@public', '-1001234567890', '__private_link__:https://t.me/+private', '__private_link__:https://t.me/c/123/45'
]
bot.VALID_CUSTOM_EMOJI_IDS = {'1234567890123456789'}
bot.CUSTOM_EMOJI_FALLBACKS = {'1234567890123456789': '🔥'}
assert bot.em('1234567890123456789') == '<tg-emoji emoji-id="1234567890123456789">🔥</tg-emoji>'
assert bot.em('9999999999999999999') == '✦'
menu = bot.reply_menu(False)
assert len(menu.keyboard) == 4
assert menu.keyboard[0][0].text == '🔥 MAKE POST'
inline = bot.main_kb(True)
assert len(inline.inline_keyboard) == 4
assert inline.inline_keyboard[0][0].callback_data == 'make'
assert inline.inline_keyboard[1][0].callback_data == 'channel_manager'
assert inline.inline_keyboard[0][0].style == 'danger'
assert inline.inline_keyboard[1][0].style == 'success'
rendered = bot.decorate_text('🔥 My Title 🚀\n😀 First line\nSecond line 💎', 'card', 1)
assert '😀' not in rendered
assert 'My Title' in rendered and 'First line' in rendered and 'Second line' in rendered
assert 'STATUS' not in bot.decorate_text('Title\nBody', 'terminal', 2)
assert 'ENCRYPTED CHANNEL' not in bot.decorate_text('Title\nBody', 'hacker', 2)
print('fix tests passed')
