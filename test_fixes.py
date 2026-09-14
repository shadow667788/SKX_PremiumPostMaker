import bot

assert bot.parse_destinations('@public https://t.me/public -1001234567890 https://t.me/+private https://t.me/c/123/45') == [
    '@public', '-1001234567890', '__private_link__:https://t.me/+private', '__private_link__:https://t.me/c/123/45'
]
bot.VALID_CUSTOM_EMOJI_IDS = {'1234567890123456789'}
bot.CUSTOM_EMOJI_FALLBACKS = {'1234567890123456789': '🔥'}
assert bot.em('1234567890123456789') == '<tg-emoji emoji-id="1234567890123456789">🔥</tg-emoji>'
assert bot.em('9999999999999999999') == '✦'
print('fix tests passed')
