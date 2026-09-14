# Reference and Telegram API findings

Reference image: https://i.postimg.cc/GtGrn7RG/Screenshot-20260915-014646.jpg
The reference shows a dark premium card, title-first content, varied emoji accents, bold/italic hierarchy, and a bottom reply keyboard with colorful menu buttons.

Video analysis: /home/ubuntu/skx_talha_bot/video_Screen_Recording_20260914_234158_analysis_20260914_203913.md
The flow shows Make Post, media, inline button name and URL, preview with the user URL button at the bottom, refresh/delete/done controls, and distinct post designs.

Official Telegram API: https://core.telegram.org/bots/api
Relevant rules: HTML custom emoji syntax is <tg-emoji emoji-id="5368324170671202286">👍</tg-emoji>; a valid ordinary fallback emoji is required and should come from the sticker emoji field. getCustomEmojiStickers validates IDs. sendMessage chat_id accepts integer IDs or public @username, not t.me invite URLs. Private invite links must be converted/provided as the numeric -100... chat ID. The current bot validates IDs, stores Telegram fallback emojis, parses public links to @usernames, and reports private invite links as requiring -100... IDs.
