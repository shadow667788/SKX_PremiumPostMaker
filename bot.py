from __future__ import annotations

import asyncio
import html
import json
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup

import config as pyconfig
from github_store import GitHubJSONStore

ROOT = Path(__file__).parent
TOKEN = pyconfig.BOT_TOKEN
OWNER_IDS = set(pyconfig.OWNER_IDS)
REQUIRED = pyconfig.REQUIRED_CHANNELS
PRIVATE_REQUIRED = pyconfig.REQUIRED_PRIVATE_CHAT_ID
BRAND = pyconfig.BRAND
store = GitHubJSONStore()
router = Router()
VALID_CUSTOM_EMOJI_IDS: set[str] = set()
CUSTOM_EMOJI_FALLBACKS: dict[str, str] = {}


def em(user_id: str | int, fallback: str = "✦") -> str:
    emoji_id = str(user_id)
    if emoji_id in VALID_CUSTOM_EMOJI_IDS:
        # Telegram requires a valid ordinary emoji alternative in the HTML
        # custom-emoji entity. Use the emoji returned by getCustomEmojiStickers.
        safe_fallback = CUSTOM_EMOJI_FALLBACKS.get(emoji_id, fallback)
        return f'<tg-emoji emoji-id="{emoji_id}">{safe_fallback}</tg-emoji>'
    return fallback


def deco(text: str, count: int = 2) -> str:
    pool = store.emoji_ids or ["5449569374065152798"]
    count = max(count, 3)
    return " ".join(em(x, SAFE_FALLBACKS[i % len(SAFE_FALLBACKS)]) for i, x in enumerate(random.sample(pool, min(count, len(pool))))) + " " + text

def icon_for(label: str, explicit: str | None = None) -> str | None:
    if explicit in VALID_CUSTOM_EMOJI_IDS:
        return explicit
    ids = sorted(VALID_CUSTOM_EMOJI_IDS)
    return ids[abs(hash(label)) % len(ids)] if ids else None


def button(text: str, callback: str, style: str = "primary", icon: str | None = None) -> InlineKeyboardButton:
    icon_id = icon_for(text, icon)
    return InlineKeyboardButton(text=text, callback_data=callback, style=style, icon_custom_emoji_id=icon_id)


def url_button(text: str, url: str, style: str = "primary", icon: str | None = None) -> InlineKeyboardButton:
    icon_id = icon_for(text, icon)
    return InlineKeyboardButton(text=text, url=url, style=style, icon_custom_emoji_id=icon_id)


def kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_kb(owner: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [button("🔥 MAKE POST", "make", "danger"), button("🎨 EMOJI EXTRACTOR", "extract", "danger")],
    ]
    if owner:
        rows.append([button("📣 BROADCAST", "obroadcast", "success"), button("📚 MY POSTS", "posts", "primary")])
    else:
        rows.append([button("📚 MY POSTS", "posts", "primary")])
    rows.append([button("🆘 HELP", "help", "danger"), button("ℹ️ ABOUT BOT", "help", "success")])
    if owner:
        rows.append([button("📊 STATS", "ostats", "danger")])
    return kb(rows)

def reply_menu(owner: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="🔥 MAKE POST"), KeyboardButton(text="🎨 EMOJI EXTRACTOR")],
        [KeyboardButton(text="📣 BROADCAST"), KeyboardButton(text="📚 MY POSTS")],
        [KeyboardButton(text="🆘 HELP"), KeyboardButton(text="ℹ️ ABOUT BOT")],
    ]
    if owner:
        rows.append([KeyboardButton(text="📊 STATS")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


async def is_member(bot: Bot, user_id: int, chat: str | int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=chat, user_id=user_id)
        return member.status in {"creator", "administrator", "member", "restricted"}
    except Exception:
        return False


async def membership_screen(bot: Bot, user_id: int) -> tuple[bool, str]:
    if not pyconfig.MEMBERSHIP_GATE_ENABLED:
        return True, ""
    checks: list[tuple[str | int, str]] = [(x, str(x)) for x in REQUIRED] + [(PRIVATE_REQUIRED, "Private group")]
    missing = [label for chat, label in checks if not await is_member(bot, user_id, chat)]
    if not missing:
        return True, ""
    return False, "\n".join(f"• {x}" for x in missing)


class Wizard(StatesGroup):
    text = State(); media = State(); photo = State(); video = State(); button_choice = State(); button_name = State(); button_url = State(); design = State(); preview = State(); destinations = State()
class OwnerFlow(StatesGroup):
    add_emojis = State(); broadcast = State(); add_owner = State(); remove_owner = State()


async def welcome(message: Message, bot: Bot) -> None:
    ok, missing = await membership_screen(bot, message.from_user.id)
    if not ok:
        links = "\n".join(f"• {x}" for x in REQUIRED)
        await message.answer(deco("<b>SKX TALHA ACCESS GATE</b>") + f"\n\nPehle tamam channels/group join karein:\n{links}\n• Private group: <code>{PRIVATE_REQUIRED}</code>\n\nPhir Verify dabayein.", reply_markup=kb([[button("✓ Verify Membership", "verify", "success")]]))
        return
    user = await store.load_user(message.from_user.id)
    user["created_at"] = user.get("created_at") or datetime.now(timezone.utc).isoformat()
    user["username"] = message.from_user.username
    user.setdefault("history", []).append({"event": "start", "at": datetime.now(timezone.utc).isoformat()})
    await store.save_user(message.from_user.id, user)
    await message.answer(deco(f"<b>{BRAND}</b>") + "\n\nPremium post creation suite ready.", reply_markup=main_kb(message.from_user.id in OWNER_IDS))


@router.message(Command("start"))
async def start(message: Message, bot: Bot): await welcome(message, bot)

@router.message(StateFilter(None), F.text == "🔥 MAKE POST")
async def reply_make(message: Message, state: FSMContext):
    await state.clear(); await state.set_state(Wizard.text)
    await message.answer(deco("<b>MAKE POST</b>") + "\n\nApni post ka text/caption bhejein.")

@router.message(StateFilter(None), F.text == "📚 MY POSTS")
async def reply_posts(message: Message):
    user = await store.load_user(message.from_user.id)
    await message.answer(deco(f"<b>MY POSTS</b>\n\nSaved posts: {len(user.get('posts', []))}"), reply_markup=main_kb(message.from_user.id in OWNER_IDS))

@router.message(StateFilter(None), F.text == "🎨 EMOJI EXTRACTOR")
async def reply_extract(message: Message):
    await message.answer(deco("<b>EMOJI EXTRACTOR</b>\n\nPremium emoji wala message forward karein."), reply_markup=main_kb(message.from_user.id in OWNER_IDS))

@router.message(StateFilter(None), F.text.in_({"🆘 HELP", "ℹ️ ABOUT BOT"}))
async def reply_help(message: Message):
    await message.answer(deco("<b>HELP</b>\n\nMake Post → media → button → design → preview → publish."), reply_markup=main_kb(message.from_user.id in OWNER_IDS))

@router.message(StateFilter(None), F.text == "📊 STATS")
async def reply_stats(message: Message):
    if message.from_user.id not in OWNER_IDS: return
    files = list((ROOT / "data_cache").glob("*.json")); users = posts = 0
    for file in files:
        try:
            data = json.loads(file.read_text(encoding="utf-8")); users += 1; posts += len(data.get("posts", []))
        except Exception: pass
    await message.answer(deco(f"<b>BOT STATS</b>\n\nUsers: {users}\nPosts: {posts}\nEmoji pool: {len(store.emoji_ids)}"), reply_markup=main_kb(True))

@router.message(StateFilter(None), F.text == "📣 BROADCAST")
async def reply_broadcast(message: Message, state: FSMContext):
    if message.from_user.id not in OWNER_IDS: return
    await state.set_state(OwnerFlow.broadcast)
    await message.answer("Broadcast message bhejein.")

@router.callback_query(F.data == "verify")
async def verify(call: CallbackQuery, bot: Bot):
    ok, missing = await membership_screen(bot, call.from_user.id)
    if not ok:
        await call.answer("Abhi kuch destinations missing hain.", show_alert=True)
        await call.message.edit_text(deco("<b>ACCESS NOT READY</b>") + f"\n\nMissing:\n{missing}", reply_markup=kb([[button("↻ Verify Again", "verify", "success")]]))
    else:
        await call.answer("Verified")
        await call.message.edit_text(deco("<b>ACCESS GRANTED</b>") + "\n\nWelcome to your premium workspace.", reply_markup=main_kb(call.from_user.id in OWNER_IDS))

@router.callback_query(F.data == "make")
async def make(call: CallbackQuery, state: FSMContext):
    await state.clear(); await state.set_state(Wizard.text)
    await call.message.edit_text(deco("<b>MAKE POST</b>") + "\n\nApni post ka text/caption bhejein.", reply_markup=kb([[button("× Cancel", "cancel", "danger")]]))

@router.message(Wizard.text)
async def post_text(message: Message, state: FSMContext):
    await state.update_data(text=message.text or message.caption or "")
    await state.set_state(Wizard.media)
    await message.answer(deco("<b>MEDIA LAYER</b>") + "\n\nPhoto ya video add karni hai?", reply_markup=kb([[button("＋ Add Photo", "add_photo", "success"), button("＋ Add Video", "add_video", "success")], [button("Skip", "media_skip", "primary"), button("Delete", "cancel", "danger")]]))

@router.callback_query(Wizard.media, F.data == "add_photo")
async def add_photo(call: CallbackQuery, state: FSMContext): await state.set_state(Wizard.photo); await call.message.edit_text(deco("<b>ADD PHOTO</b>") + "\n\nAb photo bhejein.")
@router.callback_query(Wizard.media, F.data == "add_video")
async def add_video(call: CallbackQuery, state: FSMContext): await state.set_state(Wizard.video); await call.message.edit_text(deco("<b>ADD VIDEO</b>") + "\n\nAb video bhejein.")
@router.callback_query(Wizard.media, F.data == "media_skip")
async def media_skip(call: CallbackQuery, state: FSMContext): await state.update_data(media_type=None, media_id=None); await ask_button(call.message, state)
@router.message(Wizard.photo, F.photo)
async def got_photo(message: Message, state: FSMContext): await state.update_data(media_type="photo", media_id=message.photo[-1].file_id); await ask_button(message, state)
@router.message(Wizard.video, F.video)
async def got_video(message: Message, state: FSMContext): await state.update_data(media_type="video", media_id=message.video.file_id); await ask_button(message, state)

async def ask_button(message: Message, state: FSMContext):
    await state.set_state(Wizard.button_choice)
    await message.answer(deco("<b>BUTTON LAYER</b>") + "\n\nPost mein inline button add karna hai?", reply_markup=kb([[button("Yes, Add Button", "btn_yes", "success")], [button("No, Skip", "btn_no", "primary")]]))

@router.callback_query(Wizard.button_choice, F.data == "btn_yes")
async def btn_yes(call: CallbackQuery, state: FSMContext): await state.set_state(Wizard.button_name); await call.message.edit_text(deco("<b>BUTTON LABEL</b>") + "\n\nButton ka naam bhejein.")
@router.callback_query(Wizard.button_choice, F.data == "btn_no")
async def btn_no(call: CallbackQuery, state: FSMContext): await state.update_data(button_name=None, button_url=None); await choose_design(call.message, state)
@router.message(Wizard.button_name)
async def btn_name(message: Message, state: FSMContext): await state.update_data(button_name=message.text[:64]); await state.set_state(Wizard.button_url); await message.answer(deco("<b>BUTTON LINK</b>") + "\n\nHTTPS ya Telegram link bhejein.")
@router.message(Wizard.button_url)
async def btn_url(message: Message, state: FSMContext):
    if not re.match(r"^(https?://|tg://)", message.text or ""): await message.answer("Valid HTTPS ya tg:// link bhejein."); return
    await state.update_data(button_url=message.text); await choose_design(message, state)

async def choose_design(message: Message, state: FSMContext):
    await state.set_state(Wizard.design)
    await message.answer(deco("<b>DESIGN ENGINE</b>") + "\n\nPost ka visual style choose karein.", reply_markup=kb([[button("▣ Terminal Style", "design_terminal", "primary")], [button("◇ Premium Card", "design_card", "success")], [button("⌁ Hacker Style", "design_hacker", "danger")]]))

@router.callback_query(Wizard.design, F.data.startswith("design_"))
async def design(call: CallbackQuery, state: FSMContext):
    await state.update_data(design=call.data.removeprefix("design_")); await state.set_state(Wizard.preview); await show_preview(call.message, state)

KEYWORDS = {"warning": ["warning", "alert", "danger", "caution"], "tech": ["code", "python", "bot", "api", "tech"], "offer": ["offer", "sale", "free", "deal", "price"], "news": ["news", "update", "announcement"], "gaming": ["game", "gaming", "play"], "hacker": ["hack", "security", "cyber", "terminal"]}
SAFE_FALLBACKS = ["🔥", "⚡", "🚀", "💎", "🌟", "🛡️", "🎯", "🧿", "🛰️", "💠"]
OLD_EMOJI_RE = re.compile(r"[\U0001F1E0-\U0001FAFF\U00002600-\U000027BF\u200d\ufe0f]+")

def split_title_body(text: str) -> tuple[str, str]:
    lines = [OLD_EMOJI_RE.sub("", line).strip() for line in text.splitlines() if OLD_EMOJI_RE.sub("", line).strip()]
    if not lines:
        return "Untitled Post", ""
    return lines[0][:96], "\n".join(lines[1:]) or lines[0]

def dense_lines(body: str, marks: list[str]) -> str:
    lines = [OLD_EMOJI_RE.sub("", line).strip() for line in body.splitlines() if OLD_EMOJI_RE.sub("", line).strip()]
    if not lines:
        lines = [" "]
    return "\n".join(f"{marks[i % len(marks)]} <b>{html.escape(line)}</b> {marks[(i + 1) % len(marks)]}" for i, line in enumerate(lines))

def decorate_text(text: str, style: str, refresh: int = 0) -> str:
    low = text.lower(); category = "general"
    for key, words in KEYWORDS.items():
        if any(w in low for w in words): category = key; break
    pool = store.emoji_ids or ["5449569374065152798"]
    random.seed(f"{text}:{style}:{refresh}")
    chosen = random.sample(pool, min(7, len(pool)))
    while len(chosen) < 7:
        chosen.append(pool[len(chosen) % len(pool)])
    marks = [em(x, SAFE_FALLBACKS[i % len(SAFE_FALLBACKS)]) for i, x in enumerate(chosen)]
    title, body = split_title_body(text)
    safe_title, line_body = html.escape(title), dense_lines(body, marks)
    if style == "terminal":
        plain_lines = [OLD_EMOJI_RE.sub("", line).strip() for line in body.splitlines() if OLD_EMOJI_RE.sub("", line).strip()] or [" "]
        terminal_body = "\n".join("│ " + html.escape(line) for line in plain_lines)
        return "<pre>┌────────────────────────┐\n│  " + safe_title + "\n├────────────────────────┤\n│  STATUS : ONLINE\n│  MODE   : " + category.upper() + "\n├────────────────────────┤\n" + terminal_body + "\n└─$ _</pre>\n" + " ".join(marks)
    if style == "hacker":
        return "<pre>╔════[ ENCRYPTED CHANNEL ]════╗\n║ " + safe_title + "\n╠══ SIGNAL : ████████ 100%\n║  NODE   : " + category.upper() + "\n║  ACCESS : GRANTED\n╠═════════════════════════════╣</pre>\n" + line_body + "\n<pre>╚════[ TRANSMISSION CLOSED ]══╝</pre>\n" + " ".join(marks)
    return "╭━━━━━━━━━━━━━━━━━━━━━━━━╮\n" + marks[0] + "  <b>" + safe_title + "</b>  " + marks[1] + "\n╰━━━━━━━━━━━━━━━━━━━━━━━━╯\n\n" + line_body + "\n\n╭─ ✦ ─ ✦ ─ ✦ ─ ✦ ─ ✦ ─╮\n" + "  ".join(marks[2:]) + "\n╰━━━━━━━━━━━━━━━━━━━━━━━━╯"

async def show_preview(message: Message, state: FSMContext):
    data = await state.get_data(); refresh = data.get("refresh", 0); rendered = decorate_text(data.get("text", ""), data.get("design", "card"), refresh)
    rows = [[button("↻ Refresh Emoji", "refresh", "primary"), button("Change Design", "change_design", "success")], [button("Delete Post", "cancel", "danger"), button("✓ Done", "done", "success")], [button("Publish this post to my channel", "publish", "primary")]]
    if data.get("button_name") and data.get("button_url"):
        rows.insert(0, [url_button(data["button_name"], data["button_url"], "success")])
    markup = kb(rows)
    if data.get("media_type") == "photo": await message.answer_photo(data["media_id"], caption=rendered, reply_markup=markup)
    elif data.get("media_type") == "video": await message.answer_video(data["media_id"], caption=rendered, reply_markup=markup)
    else: await message.answer(rendered, reply_markup=markup)
    await state.set_state(Wizard.preview)

async def send_final_post(message: Message, data: dict) -> None:
    rendered = decorate_text(data.get("text", ""), data.get("design", "card"), data.get("refresh", 0))
    markup = None
    if data.get("button_name") and data.get("button_url"):
        # Inline buttons support Telegram's primary/success/danger styles.
        markup = kb([[url_button(data["button_name"], data["button_url"], "success")]])
    if data.get("media_type") == "photo":
        await message.answer_photo(data["media_id"], caption=rendered, reply_markup=markup)
    elif data.get("media_type") == "video":
        await message.answer_video(data["media_id"], caption=rendered, reply_markup=markup)
    else:
        await message.answer(rendered, reply_markup=markup)

@router.callback_query(Wizard.preview, F.data == "refresh")
async def refresh(call: CallbackQuery, state: FSMContext): data=await state.get_data(); await state.update_data(refresh=data.get("refresh",0)+1); await call.message.delete(); await show_preview(call.message, state)
@router.callback_query(Wizard.preview, F.data == "change_design")
async def change_design(call: CallbackQuery, state: FSMContext): await choose_design(call.message, state)
@router.callback_query(Wizard.preview, F.data == "done")
async def done(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user = await store.load_user(call.from_user.id)
    user.setdefault("posts", []).append({"text": data.get("text"), "created_at": datetime.now(timezone.utc).isoformat()})
    await store.save_user(call.from_user.id, user)
    await send_final_post(call.message, data)
    await state.clear()
    await call.message.answer(deco("<b>POST READY</b>") + "\n\nAapki final post inbox mein deliver kar di gayi hai.", reply_markup=main_kb(call.from_user.id in OWNER_IDS))

@router.callback_query(Wizard.preview, F.data == "publish")
async def publish_start(call: CallbackQuery, state: FSMContext): await state.set_state(Wizard.destinations); await call.message.answer(deco("<b>MULTI-PUBLISH</b>") + "\n\nEk hi message mein channel/group links ya private chat IDs bhejein. Bot sab detect karega.\n\nPrivate destination ke liye pehle bot ko admin banayein. Har destination new line par dena behtar hai.", reply_markup=kb([[button("Cancel", "cancel", "danger")]]))

def parse_destinations(raw: str) -> list[str]:
    """Convert user input into Bot API chat_id values.

    Bot API accepts @public_channel_username or an integer chat ID. It does
    not accept t.me invite URLs as chat_id, so private invite links are kept
    as a diagnostic token and the user is told to provide the -100... ID.
    """
    tokens = re.findall(r"(?:https?://t\.me/[A-Za-z0-9_+/-]+|@[A-Za-z0-9_]+|-100\d+)", raw)
    result: list[str] = []
    for token in tokens:
        if token.startswith("-100") or token.startswith("@"):
            value = token
        else:
            slug = token.rstrip("/").split("/", 3)[-1]
            value = f"@{slug}" if slug and not slug.startswith(("+", "joinchat", "c/")) else f"__private_link__:{token}"
        if value not in result:
            result.append(value)
    return result

@router.message(Wizard.destinations)
async def publish_destinations(message: Message, state: FSMContext, bot: Bot):
    raw = message.text or ""
    targets = parse_destinations(raw)
    data=await state.get_data(); rendered=decorate_text(data.get("text",""),data.get("design","card"),data.get("refresh",0)); results=[]
    for target in targets[:pyconfig.MAX_DESTINATIONS_PER_POST]:
        if target.startswith("__private_link__:"):
            results.append(f"❌ {target.removeprefix('__private_link__:')}: Private invite link se chat_id nahi milta; -100... ID bhejein")
            continue
        chat = int(target) if target.startswith("-100") else target
        try:
            # Public @usernames are valid Bot API chat_id values. Invite URLs
            # are not chat IDs; private chats must be supplied as -100... IDs.
            chat_info = await bot.get_chat(chat_id=chat)
            resolved_chat = chat_info.id
            member=await bot.get_chat_member(resolved_chat, (await bot.get_me()).id)
            if member.status not in {"administrator","creator"}: results.append(f"❌ {target}: Bot ko admin karein"); continue
            markup=None
            if data.get("button_name") and data.get("button_url"): markup=kb([[url_button(data["button_name"], data["button_url"], "primary")]])
            if data.get("media_type")=="photo": await bot.send_photo(resolved_chat,data["media_id"],caption=rendered,reply_markup=markup)
            elif data.get("media_type")=="video": await bot.send_video(resolved_chat,data["media_id"],caption=rendered,reply_markup=markup)
            else: await bot.send_message(resolved_chat,rendered,reply_markup=markup)
            results.append(f"✅ {target}: Published")
        except Exception as exc: results.append(f"❌ {target}: {str(exc)[:80]}")
    user = await store.load_user(message.from_user.id)
    user.setdefault("destinations", [])
    user["destinations"] = list(dict.fromkeys(user["destinations"] + [x for x in targets if any(x in r and r.startswith("✅") for r in results)]))
    await store.save_user(message.from_user.id, user)
    await message.answer(deco("<b>PUBLISH REPORT</b>")+"\n\n"+("\n".join(results) if results else "Koi valid link/ID detect nahi hua.")); await state.clear()

@router.callback_query(F.data == "cancel")
async def cancel(call: CallbackQuery, state: FSMContext): await state.clear(); await call.message.answer(deco("Draft deleted."), reply_markup=main_kb(call.from_user.id in OWNER_IDS))

@router.callback_query(F.data == "owner")
async def owner_panel(call: CallbackQuery):
    if call.from_user.id not in OWNER_IDS: await call.answer("Access denied", show_alert=True); return
    await call.message.edit_text(deco("<b>OWNER CONTROL CENTER</b>") + "\n\nSecure administration tools.", reply_markup=kb([[button("Broadcast", "obroadcast", "danger"), button("Stats", "ostats", "primary")],[button("Add Emoji IDs", "oemoji", "success")],[button("Add Owner", "oadd", "primary"),button("Remove Owner", "oremove", "danger")],[button("Back", "back", "primary")]]))

@router.callback_query(F.data == "ostats")
async def ostats(call: CallbackQuery):
    if call.from_user.id not in OWNER_IDS: return
    files = list((ROOT / "data_cache").glob("*.json"))
    users = posts = destinations = 0
    for file in files:
        try:
            data = json.loads(file.read_text(encoding="utf-8")); users += 1; posts += len(data.get("posts", [])); destinations += len(data.get("destinations", []))
        except Exception: pass
    await call.message.answer(deco(f"<b>BOT STATS</b>\n\nUsers: {users}\nPosts: {posts}\nRegistered destinations: {destinations}\nEmoji pool: {len(store.emoji_ids)}"), reply_markup=main_kb(True))
@router.callback_query(F.data == "oemoji")
async def oemoji(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in OWNER_IDS: return
    await state.set_state(OwnerFlow.add_emojis); await call.message.answer("Emoji IDs ek hi message mein bhejein, spaces/commas/new lines supported hain.")
@router.message(OwnerFlow.add_emojis)
async def save_emojis(message: Message, state: FSMContext):
    if message.from_user.id not in OWNER_IDS: return
    ids=re.findall(r"\d{10,}",message.text or ""); await store.save_emojis(store.emoji_ids+ids); await state.clear(); await message.answer(deco(f"{len(ids)} IDs added. Total pool: {len(store.emoji_ids)}"), reply_markup=main_kb(True))
@router.callback_query(F.data == "oadd")
async def oadd(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in OWNER_IDS:return
    await state.set_state(OwnerFlow.add_owner); await call.message.answer("New owner ka numeric Telegram ID bhejein.")
@router.message(OwnerFlow.add_owner)
async def add_owner(message: Message, state: FSMContext):
    if message.from_user.id not in OWNER_IDS:return
    try:
        OWNER_IDS.add(int(message.text)); await store.save_owner_ids(OWNER_IDS - pyconfig.OWNER_IDS); await state.clear(); await message.answer("Owner added aur GitHub metadata mein save ho gaya.",reply_markup=main_kb(True))
    except ValueError: await message.answer("Numeric ID bhejein.")
@router.callback_query(F.data == "oremove")
async def oremove(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in OWNER_IDS:return
    await state.set_state(OwnerFlow.remove_owner); await call.message.answer("Remove karne wale owner ka numeric ID bhejein. Current owner IDs: "+", ".join(map(str,OWNER_IDS)))
@router.message(OwnerFlow.remove_owner)
async def remove_owner(message: Message, state: FSMContext):
    if message.from_user.id not in OWNER_IDS:return
    try:
        candidate=int(message.text)
        if candidate in pyconfig.OWNER_IDS: await message.answer("Primary owner protected hai."); return
        OWNER_IDS.discard(candidate); await store.save_owner_ids(OWNER_IDS - pyconfig.OWNER_IDS); await state.clear(); await message.answer("Owner removed aur GitHub metadata update ho gaya.",reply_markup=main_kb(True))
    except ValueError: await message.answer("Numeric ID bhejein.")
@router.callback_query(F.data == "obroadcast")
async def obroadcast(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in OWNER_IDS:return
    await state.set_state(OwnerFlow.broadcast); await call.message.answer("Broadcast message bhejein. Yeh registered user files ke users ko DM karega; channel broadcast ke liye destination IDs wali list paste karein.")
@router.message(OwnerFlow.broadcast)
async def broadcast(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id not in OWNER_IDS:return
    cache=list((ROOT/"data_cache").glob("*.json")); sent=0
    channel_sent = 0
    destinations = set()
    for file in cache:
        try:
            data=json.loads(file.read_text()); uid=int(file.stem); await bot.copy_message(uid,message.chat.id,message.message_id); sent+=1
            destinations.update(data.get("destinations", []))
        except Exception: pass
    for target in destinations:
        try:
            chat = int(target) if str(target).startswith("-100") else target
            resolved = (await bot.get_chat(chat_id=chat)).id
            member = await bot.get_chat_member(resolved, (await bot.get_me()).id)
            if member.status in {"administrator", "creator"}:
                await bot.copy_message(resolved, message.chat.id, message.message_id); channel_sent += 1
        except Exception: pass
    await state.clear(); await message.answer(deco(f"Broadcast complete. DM sent: {sent}\nChannel/group sent: {channel_sent}"),reply_markup=main_kb(True))

@router.callback_query(F.data == "posts")
async def posts(call: CallbackQuery):
    user=await store.load_user(call.from_user.id); total=len(user.get("posts",[])); await call.message.answer(deco(f"<b>MY POSTS</b>\n\nSaved posts: {total}"),reply_markup=main_kb(call.from_user.id in OWNER_IDS))
@router.callback_query(F.data == "extract")
async def extract(call: CallbackQuery): await call.message.answer(deco("<b>EMOJI EXTRACTOR</b>\n\nPremium emoji wale message ko forward karein ya custom emoji entity wala text bhejein. IDs ko owner panel se pool mein add kiya ja sakta hai."),reply_markup=main_kb(call.from_user.id in OWNER_IDS))
@router.callback_query(F.data == "help")
async def help_(call: CallbackQuery): await call.message.answer(deco("<b>HELP</b>\n\nMake Post → media → button → design → preview → publish. Private channels/groups mein bot ko pehle admin karein."),reply_markup=main_kb(call.from_user.id in OWNER_IDS))
@router.callback_query(F.data == "back")
async def back(call: CallbackQuery): await call.message.edit_text(deco(BRAND),reply_markup=main_kb(True))
@router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery): await call.answer()

async def main() -> None:
    if TOKEN == "PUT_BOT_TOKEN_HERE": raise RuntimeError("Set BOT_TOKEN in config.py")
    await store.initialize()
    persisted = await store.load_meta()
    OWNER_IDS.update(int(x) for x in persisted.get("owner_ids", []))
    bot=Bot(TOKEN,default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    global VALID_CUSTOM_EMOJI_IDS, CUSTOM_EMOJI_FALLBACKS
    try:
        for start in range(0, len(store.emoji_ids), 50):
            chunk = store.emoji_ids[start:start + 50]
            try:
                stickers = await bot.get_custom_emoji_stickers(custom_emoji_ids=chunk)
                for sticker in stickers:
                    if sticker.custom_emoji_id:
                        emoji_id = str(sticker.custom_emoji_id)
                        VALID_CUSTOM_EMOJI_IDS.add(emoji_id)
                        if sticker.emoji:
                            CUSTOM_EMOJI_FALLBACKS[emoji_id] = sticker.emoji
            except Exception:
                # An invalid ID can reject a whole request; isolate it without
                # preventing the remaining valid premium IDs from working.
                for emoji_id in chunk:
                    try:
                        stickers = await bot.get_custom_emoji_stickers(custom_emoji_ids=[emoji_id])
                        for sticker in stickers:
                            if sticker.custom_emoji_id:
                                emoji_id = str(sticker.custom_emoji_id)
                                VALID_CUSTOM_EMOJI_IDS.add(emoji_id)
                                if sticker.emoji:
                                    CUSTOM_EMOJI_FALLBACKS[emoji_id] = sticker.emoji
                    except Exception:
                        continue
    except Exception:
        VALID_CUSTOM_EMOJI_IDS = set()
    dp=Dispatcher(); dp.include_router(router)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__": asyncio.run(main())
