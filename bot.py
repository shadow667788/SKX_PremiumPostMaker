

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
GATE_ENABLED = getattr(pyconfig, "MEMBERSHIP_GATE_ENABLED", True)
CHANNEL_LABELS = getattr(pyconfig, "REQUIRED_CHANNEL_LABELS", REQUIRED)
PRIVATE_INVITE_LINK = getattr(pyconfig, "REQUIRED_PRIVATE_INVITE_LINK", "")
CUSTOM_BUTTON_ICONS = False
_EMOJI_CURSOR = 0


def em(user_id: str | int, fallback: str = "✦") -> str:
    emoji_id = str(user_id)
    if emoji_id in VALID_CUSTOM_EMOJI_IDS:
        # Telegram requires a valid ordinary emoji alternative in the HTML
        # custom-emoji entity. Use the emoji returned by getCustomEmojiStickers.
        safe_fallback = CUSTOM_EMOJI_FALLBACKS.get(emoji_id, fallback)
        return f'<tg-emoji emoji-id="{emoji_id}">{safe_fallback}</tg-emoji>'
    return fallback


def deco(text: str, count: int = 5) -> str:
    pool = store.emoji_ids or ["5449569374065152798"]
    count = max(count, 5)
    ids = rotating_ids(pool, count)
    return " ".join(em(x, SAFE_FALLBACKS[i % len(SAFE_FALLBACKS)]) for i, x in enumerate(ids)) + " " + text

def rotating_ids(pool: list[str], count: int) -> list[str]:
    global _EMOJI_CURSOR
    if not pool: return []
    shuffled = list(dict.fromkeys(pool))
    random.SystemRandom().shuffle(shuffled)
    count = min(count, len(shuffled))
    start = _EMOJI_CURSOR % len(shuffled)
    _EMOJI_CURSOR += max(1, count)
    return [shuffled[(start + i) % len(shuffled)] for i in range(count)]

def icon_for(label: str, explicit: str | None = None) -> str | None:
    if explicit in VALID_CUSTOM_EMOJI_IDS:
        return explicit
    ids = sorted(VALID_CUSTOM_EMOJI_IDS)
    return ids[abs(hash(label)) % len(ids)] if ids else None


def button(text: str, callback: str, style: str = "primary", icon: str | None = None) -> InlineKeyboardButton:
    icon_id = icon_for(text, icon) if CUSTOM_BUTTON_ICONS else None
    return InlineKeyboardButton(text=text, callback_data=callback, style=style, icon_custom_emoji_id=icon_id)


def url_button(text: str, url: str, style: str = "primary", icon: str | None = None) -> InlineKeyboardButton:
    icon_id = icon_for(text, icon) if CUSTOM_BUTTON_ICONS else None
    return InlineKeyboardButton(text=text, url=url, style=style, icon_custom_emoji_id=icon_id)


def kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def edit_ui(message: Message, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    """Edit the existing bot message; fall back to caption editing for banner/media messages."""
    try:
        if message.photo or message.video:
            await message.edit_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=markup)
        else:
            await message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except Exception:
        # Telegram cannot edit a message into another media type; keep the
        # flow alive with one fallback message only in that edge case.
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)


def main_kb(owner: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [button("🔥 MAKE POST", "make", "danger"), button("🎨 EMOJI EXTRACTOR", "extract", "danger")],
        [button("📡 CHANNEL POST MANAGER", "channel_manager", "success")],
    ]
    if owner:
        rows.append([button("🔐 OWNER PANEL", "owner", "danger"), button("📚 MY POSTS", "posts", "primary")])
    else:
        rows.append([button("📚 MY POSTS", "posts", "primary")])
    rows.append([button("🆘 HELP", "help", "danger"), button("ℹ️ ABOUT BOT", "help", "success")])
    return kb(rows)

def reply_menu(owner: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="🔥 MAKE POST"), KeyboardButton(text="🎨 EMOJI EXTRACTOR")],
        [KeyboardButton(text="📡 CHANNEL POST MANAGER")],
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


async def user_can_manage(bot: Bot, chat_id: int | str, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status in {"creator", "administrator"}
    except Exception:
        return False


async def membership_screen(bot: Bot, user_id: int) -> tuple[bool, str]:
    if not GATE_ENABLED:
        return True, ""
    checks: list[tuple[str | int, str]] = list(zip(REQUIRED, CHANNEL_LABELS)) + [(PRIVATE_REQUIRED, "🔒 Private group")]
    missing = [label for chat, label in checks if not await is_member(bot, user_id, chat)]
    if not missing:
        return True, ""
    return False, "\n".join(f"• {x}" for x in missing)

def join_button_rows() -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []
    for index, destination in enumerate(REQUIRED, 1):
        url = destination if destination.startswith("http") else f"https://t.me/{destination.lstrip('@')}"
        rows.append([url_button(f"🟢 JOIN {CHANNEL_LABELS[index - 1]}", url, "success")])
    if PRIVATE_INVITE_LINK:
        rows.append([url_button("🔴 JOIN PRIVATE GROUP", PRIVATE_INVITE_LINK, "danger")])
    rows.append([button("✅ VERIFY MEMBERSHIP", "verify", "success")])
    return rows


class Wizard(StatesGroup):
    text = State(); media = State(); photo = State(); video = State(); button_choice = State(); button_name = State(); button_url = State(); button_style = State(); design = State(); preview = State(); destinations = State()
class OwnerFlow(StatesGroup):
    add_emojis = State(); broadcast = State(); broadcast_all = State(); broadcast_users = State(); broadcast_channels = State(); add_owner = State(); remove_owner = State()
class ChannelManagerFlow(StatesGroup):
    add = State(); remove = State(); post = State()


async def welcome(message: Message, bot: Bot) -> None:
    ok, missing = await membership_screen(bot, message.from_user.id)
    if not ok:
        links = "\n".join(f"• {x}" for x in REQUIRED)
        await message.answer_photo(pyconfig.BANNER_URL, caption=deco("<b>SKX TALHA ACCESS GATE</b>") + f"\n\nPehle tamam channels/group join karein:\n{links}\n• Private group: <code>{PRIVATE_REQUIRED}</code>\n\nPhir Verify dabayein.", reply_markup=kb(join_button_rows()), parse_mode=ParseMode.HTML)
        return
    user = await store.load_user(message.from_user.id)
    user["created_at"] = user.get("created_at") or datetime.now(timezone.utc).isoformat()
    user["username"] = message.from_user.username
    user.setdefault("history", []).append({"event": "start", "at": datetime.now(timezone.utc).isoformat()})
    await store.save_user(message.from_user.id, user)
    await message.answer_photo(pyconfig.BANNER_URL, caption=deco(f"<b>{BRAND}</b>") + "\n\nPremium post creation suite ready.", reply_markup=main_kb(message.from_user.id in OWNER_IDS), parse_mode=ParseMode.HTML)


@router.message(Command("start"))
async def start(message: Message, bot: Bot): await welcome(message, bot)

@router.message(StateFilter(None), F.text == "🔥 MAKE POST")
async def reply_make(message: Message, state: FSMContext):
    await state.clear(); await state.update_data(channel_manager=False, normal_mode=False); await state.set_state(Wizard.text)
    await message.answer(deco("<b>MAKE POST</b>") + "\n\nApni post ka text/caption bhejein.")

@router.message(StateFilter(None), F.text == "📚 MY POSTS")
async def reply_posts(message: Message):
    user = await store.load_user(message.from_user.id)
    await message.answer(deco(f"<b>MY POSTS</b>\n\nSaved posts: {len(user.get('posts', []))}"), reply_markup=main_kb(message.from_user.id in OWNER_IDS))

@router.message(StateFilter(None), F.text == "📡 CHANNEL POST MANAGER")
async def reply_channel_manager(message: Message):
    await channel_manager_screen(message, message.from_user.id)

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
        await edit_ui(call.message, deco("<b>ACCESS NOT READY</b>") + f"\n\nMissing:\n{missing}", kb(join_button_rows()))
    else:
        await call.answer("Verified")
        await edit_ui(call.message, deco("<b>ACCESS GRANTED</b>") + "\n\nWelcome to your premium workspace.", main_kb(call.from_user.id in OWNER_IDS))

@router.callback_query(F.data == "make")
async def make(call: CallbackQuery, state: FSMContext):
    await state.clear(); await state.update_data(channel_manager=False, normal_mode=False); await state.set_state(Wizard.text)
    await edit_ui(call.message, deco("<b>MAKE POST</b>") + "\n\nApni post ka text/caption bhejein.", kb([[button("× Cancel", "cancel", "danger")]]))

async def channel_manager_screen(message: Message, user_id: int, edit: bool = False) -> None:
    user = await store.load_user(user_id)
    destinations = user.get("destinations", [])
    listed = "\n".join(f"• {x} ✅ Bot admin hai" for x in destinations) or "Abhi koi channel/group add nahi hai."
    text = "📡 <b>CHANNEL POST MANAGER</b> 🛠️" + f"\n\nAapke verified channels/groups:\n{listed}\n\nNaya channel add karne ke baad bot ko administrator zaroor banayein."
    markup = kb([
        [button("➕ ADD CHANNEL/GROUP", "cm_add", "success")],
        [button("➖ REMOVE CHANNEL/GROUP", "cm_remove", "danger")],
        [button("✍️ CREATE CHANNEL POST", "cm_post", "primary")],
        [button("⬅ BACK", "back", "danger")]])
    if edit: await edit_ui(message, text, markup)
    else: await message.answer(text, reply_markup=markup)

@router.callback_query(F.data == "channel_manager")
async def channel_manager(call: CallbackQuery):
    await call.answer(); await channel_manager_screen(call.message, call.from_user.id, edit=True)

@router.callback_query(F.data == "cm_add")
async def cm_add(call: CallbackQuery, state: FSMContext):
    await state.set_state(ChannelManagerFlow.add)
    await call.answer(); await edit_ui(call.message, "Channel ka @username ya -100... chat ID bhejein. Private invite link ke bajaye chat ID dein.", kb([[button("Cancel", "cancel", "danger")]]))

@router.message(ChannelManagerFlow.add)
async def cm_add_save(message: Message, state: FSMContext, bot: Bot):
    targets = parse_destinations(message.text or "")
    if not targets or targets[0].startswith("__private_link__:"):
        await message.answer("Valid public @username ya -100... chat ID bhejein."); return
    target = targets[0]
    try:
        chat = int(target) if target.startswith("-100") else target
        info = await bot.get_chat(chat_id=chat)
        me = await bot.get_me(); member = await bot.get_chat_member(info.id, me.id)
        if member.status not in {"administrator", "creator"}:
            await message.answer("Pehle is channel/group mein bot ko administrator banayein."); return
        if not await user_can_manage(bot, info.id, message.from_user.id):
            await message.answer("Security check failed: aap is channel/group ke admin ya owner nahi hain. Sirf apne managed destinations add kar sakte hain."); return
        user = await store.load_user(message.from_user.id)
        user["destinations"] = list(dict.fromkeys(user.get("destinations", []) + [str(info.id) if str(info.id).startswith("-100") else target]))
        user.setdefault("history", []).append({"event": "destination_added", "chat_id": str(info.id), "at": datetime.now(timezone.utc).isoformat()})
        await store.save_user(message.from_user.id, user); await state.clear(); await channel_manager_screen(message, message.from_user.id)
    except Exception as exc:
        await message.answer(f"Channel verify nahi hua: {str(exc)[:120]}")

@router.callback_query(F.data == "cm_remove")
async def cm_remove(call: CallbackQuery, state: FSMContext):
    await state.set_state(ChannelManagerFlow.remove); await call.answer(); await edit_ui(call.message, "Remove karne wale channel ka @username ya -100... chat ID bhejein.", kb([[button("Cancel", "cancel", "danger")]]))

@router.message(ChannelManagerFlow.remove)
async def cm_remove_save(message: Message, state: FSMContext):
    targets = parse_destinations(message.text or "")
    if not targets: await message.answer("Valid channel username ya chat ID bhejein."); return
    user = await store.load_user(message.from_user.id)
    before = user.get("destinations", []); user["destinations"] = [x for x in before if x not in targets]
    await store.save_user(message.from_user.id, user); await state.clear(); await channel_manager_screen(message, message.from_user.id)

@router.callback_query(F.data == "cm_post")
async def cm_post(call: CallbackQuery, state: FSMContext):
    user = await store.load_user(call.from_user.id)
    if not user.get("destinations"):
        await call.answer("Pehle kam az kam ek channel/group add karein.", show_alert=True); return
    await state.clear(); await state.update_data(channel_manager=True, normal_mode=True); await state.set_state(ChannelManagerFlow.post)
    await call.answer(); await edit_ui(call.message, deco("<b>CHANNEL POST</b>") + "\n\nApni post ka text/caption bhejein.", kb([[button("Cancel", "cancel", "danger")]]))

@router.message(ChannelManagerFlow.post)
async def cm_post_text(message: Message, state: FSMContext):
    await state.update_data(text=message.text or message.caption or "", channel_manager=True)
    await state.set_state(Wizard.media); await message.answer(deco("<b>MEDIA LAYER</b>") + "\n\nPhoto ya video add karni hai?", reply_markup=kb([[button("＋ Add Photo", "add_photo", "success"), button("＋ Add Video", "add_video", "success")], [button("Skip", "media_skip", "primary"), button("Delete", "cancel", "danger")]]))

@router.message(Wizard.text)
async def post_text(message: Message, state: FSMContext):
    await state.update_data(text=message.text or message.caption or "")
    await state.set_state(Wizard.media)
    await message.answer(deco("<b>MEDIA LAYER</b>") + "\n\nPhoto ya video add karni hai?", reply_markup=kb([[button("＋ Add Photo", "add_photo", "success"), button("＋ Add Video", "add_video", "success")], [button("Skip", "media_skip", "primary"), button("Delete", "cancel", "danger")]]))

@router.callback_query(Wizard.media, F.data == "add_photo")
async def add_photo(call: CallbackQuery, state: FSMContext): await state.set_state(Wizard.photo); await edit_ui(call.message, deco("<b>ADD PHOTO</b>") + "\n\nAb photo bhejein.", kb([[button("Cancel", "cancel", "danger")]]))
@router.callback_query(Wizard.media, F.data == "add_video")
async def add_video(call: CallbackQuery, state: FSMContext): await state.set_state(Wizard.video); await edit_ui(call.message, deco("<b>ADD VIDEO</b>") + "\n\nAb video bhejein.", kb([[button("Cancel", "cancel", "danger")]]))
@router.callback_query(Wizard.media, F.data == "media_skip")
async def media_skip(call: CallbackQuery, state: FSMContext): await state.update_data(media_type=None, media_id=None); await ask_button(call.message, state)
@router.message(Wizard.photo, F.photo)
async def got_photo(message: Message, state: FSMContext): await state.update_data(media_type="photo", media_id=message.photo[-1].file_id); await ask_button(message, state)
@router.message(Wizard.video, F.video)
async def got_video(message: Message, state: FSMContext): await state.update_data(media_type="video", media_id=message.video.file_id); await ask_button(message, state)

async def ask_button(message: Message, state: FSMContext):
    await state.update_data(buttons=[])
    await state.set_state(Wizard.button_choice)
    await message.answer(deco("<b>BUTTON LAYER</b>") + "\n\nJitne buttons chahen add karein. Har button ka label, link aur rank/style choose hoga.", reply_markup=kb([[button("Yes, Add Button", "btn_yes", "success")], [button("No, Skip", "btn_no", "primary")]]))

@router.callback_query(Wizard.button_choice, F.data == "btn_yes")
async def btn_yes(call: CallbackQuery, state: FSMContext):
    await state.set_state(Wizard.button_name)
    await call.answer()
    await call.message.answer(deco("<b>BUTTON LABEL</b>") + "\n\nButton ka naam bhejein.")

@router.callback_query(Wizard.button_choice, F.data == "btn_no")
async def btn_no(call: CallbackQuery, state: FSMContext):
    # Preserve all buttons collected so far when continuing to design.
    await choose_design(call.message, state)

@router.message(Wizard.button_name)
async def btn_name(message: Message, state: FSMContext):
    await state.update_data(pending_button_name=(message.text or "")[:64])
    await state.set_state(Wizard.button_url)
    await message.answer(deco("<b>BUTTON LINK</b>") + "\n\nHTTPS ya Telegram link bhejein.")

@router.message(Wizard.button_url)
async def btn_url(message: Message, state: FSMContext):
    if not re.match(r"^(https?://|tg://)", message.text or ""):
        await message.answer("Valid HTTPS ya tg:// link bhejein."); return
    await state.update_data(pending_button_url=message.text)
    await state.set_state(Wizard.button_style)
    await message.answer(deco("<b>BUTTON RANK / STYLE</b>") + "\n\nIs button ka rank choose karein.", reply_markup=kb([[button("Success", "style_success", "success")], [button("Danger", "style_danger", "danger")], [button("Primary", "style_primary", "primary")]]))

@router.callback_query(Wizard.button_style, F.data.in_({"style_success", "style_danger", "style_primary"}))
async def button_style(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    buttons = list(data.get("buttons", []))
    if len(buttons) >= 100:
        await call.answer("Maximum 100 buttons allowed by Telegram.", show_alert=True); return
    style = call.data.removeprefix("style_")
    buttons.append({"name": data.get("pending_button_name", "Button"), "url": data.get("pending_button_url", ""), "style": style})
    await state.update_data(buttons=buttons, pending_button_name=None, pending_button_url=None)
    await state.set_state(Wizard.button_choice)
    await call.answer("Button added")
    await call.message.answer(deco(f"<b>BUTTON {len(buttons)} ADDED</b>") + "\n\nAur button add karna hai?", reply_markup=kb([[button("＋ Add Another Button", "btn_yes", "success")], [button("Continue to Design", "btn_no", "primary")]]))

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

def decorate_text(text: str, style: str, refresh: int = 0, premium: bool = True) -> str:
    pool = store.emoji_ids or ["5449569374065152798"]
    chosen = rotating_ids(pool, 12)
    while len(chosen) < 12:
        chosen.append(pool[len(chosen) % len(pool)])
    marks = [em(x, SAFE_FALLBACKS[i % len(SAFE_FALLBACKS)]) if premium else SAFE_FALLBACKS[i % len(SAFE_FALLBACKS)] for i, x in enumerate(chosen)]
    title, body = split_title_body(text)
    safe_title, line_body = html.escape(title), dense_lines(body, marks)
    if style == "terminal":
        plain_lines = [OLD_EMOJI_RE.sub("", line).strip() for line in body.splitlines() if OLD_EMOJI_RE.sub("", line).strip()] or [" "]
        terminal_body = "\n".join("│ " + html.escape(line) for line in plain_lines)
        return "<pre>┌────────────────────────┐\n│  " + safe_title + "\n├────────────────────────┤\n" + terminal_body + "\n└─$ _</pre>\n" + " ".join(marks)
    if style == "hacker":
        return "<pre>╔══════════════════════════╗\n║  " + safe_title + "\n╠══ ████████████ 100% ════╣</pre>\n" + line_body + "\n<pre>╚══════════════════════════╝</pre>\n" + " ".join(marks)
    return "╭━━━━━━━━━━━━━━━━━━━━━━━━╮\n" + marks[0] + "  <b>" + safe_title + "</b>  " + marks[1] + "\n╰━━━━━━━━━━━━━━━━━━━━━━━━╯\n\n" + line_body + "\n\n╭─ ✦ ─ ✦ ─ ✦ ─ ✦ ─ ✦ ─╮\n" + "  ".join(marks[2:]) + "\n╰━━━━━━━━━━━━━━━━━━━━━━━━╯"

def post_buttons(data: dict) -> list[list[InlineKeyboardButton]]:
    items = data.get("buttons") or []
    if not items and data.get("button_name") and data.get("button_url"):
        items = [{"name": data["button_name"], "url": data["button_url"], "style": "success"}]
    return [[url_button(item.get("name", "Button"), item.get("url", ""), item.get("style", "primary"))] for item in items if item.get("url")]


async def show_preview(message: Message, state: FSMContext):
    data = await state.get_data(); refresh = data.get("refresh", 0); rendered = decorate_text(data.get("text", ""), data.get("design", "card"), refresh, premium=not data.get("normal_mode", False))
    rows = [[button("↻ Refresh Emoji", "refresh", "primary"), button("Change Design", "change_design", "success")], [button("Delete Post", "cancel", "danger"), button("✓ Done", "done", "success")]]
    if data.get("channel_manager"):
        rows.append([button("✅ CONFIRM PUBLISH TO MY CHANNELS", "cm_confirm_publish", "success")])
    button_rows = post_buttons(data)
    if button_rows:
        rows = button_rows + rows
    markup = kb(rows)
    if data.get("media_type") == "photo": await message.answer_photo(data["media_id"], caption=rendered, reply_markup=markup)
    elif data.get("media_type") == "video": await message.answer_video(data["media_id"], caption=rendered, reply_markup=markup)
    else: await message.answer(rendered, reply_markup=markup)
    await state.set_state(Wizard.preview)

async def send_final_post(message: Message, data: dict) -> None:
    rendered = decorate_text(data.get("text", ""), data.get("design", "card"), data.get("refresh", 0), premium=not data.get("normal_mode", False))
    markup = None
    button_rows = post_buttons(data)
    if button_rows:
        markup = kb(button_rows)
    if data.get("media_type") == "photo":
        await message.answer_photo(data["media_id"], caption=rendered, parse_mode=ParseMode.HTML, reply_markup=markup)
    elif data.get("media_type") == "video":
        await message.answer_video(data["media_id"], caption=rendered, parse_mode=ParseMode.HTML, reply_markup=markup)
    else:
        await message.answer(rendered, parse_mode=ParseMode.HTML, reply_markup=markup)

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
    await edit_ui(call.message, deco("<b>POST READY</b>") + "\n\nAapki final post inbox mein deliver kar di gayi hai.", main_kb(call.from_user.id in OWNER_IDS))

@router.callback_query(Wizard.preview, F.data == "publish")
async def publish_start(call: CallbackQuery, state: FSMContext): await state.set_state(Wizard.destinations); await edit_ui(call.message, deco("<b>MULTI-PUBLISH</b>") + "\n\nEk hi message mein channel/group links ya private chat IDs bhejein. Bot sab detect karega.\n\nPrivate destination ke liye pehle bot ko admin banayein. Har destination new line par dena behtar hai.", kb([[button("Cancel", "cancel", "danger")]]))

@router.callback_query(Wizard.preview, F.data == "cm_confirm_publish")
async def cm_confirm_publish(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data(); user = await store.load_user(call.from_user.id); targets = user.get("destinations", [])
    rendered = decorate_text(data.get("text", ""), data.get("design", "card"), data.get("refresh", 0), premium=False); results = []
    for target in targets[:pyconfig.MAX_DESTINATIONS_PER_POST]:
        try:
            chat = int(target) if str(target).startswith("-100") else target
            info = await bot.get_chat(chat_id=chat); me = await bot.get_me(); member = await bot.get_chat_member(info.id, me.id)
            if member.status not in {"administrator", "creator"}: results.append(f"❌ {target}: Bot ko admin karein"); continue
            if not await user_can_manage(bot, info.id, call.from_user.id): results.append(f"❌ {target}: Aap is destination ke admin/owner nahi hain"); continue
            button_rows = post_buttons(data)
            markup = kb(button_rows) if button_rows else None
            if data.get("media_type") == "photo": await bot.send_photo(info.id, data["media_id"], caption=rendered, parse_mode=ParseMode.HTML, reply_markup=markup)
            elif data.get("media_type") == "video": await bot.send_video(info.id, data["media_id"], caption=rendered, parse_mode=ParseMode.HTML, reply_markup=markup)
            else: await bot.send_message(info.id, rendered, parse_mode=ParseMode.HTML, reply_markup=markup)
            results.append(f"✅ {target}: Published")
        except Exception as exc: results.append(f"❌ {target}: {str(exc)[:80]}")
    user.setdefault("posts", []).append({"text": data.get("text"), "created_at": datetime.now(timezone.utc).isoformat(), "channel_manager": True})
    await store.save_user(call.from_user.id, user); await state.clear()
    await edit_ui(call.message, deco("<b>CHANNEL PUBLISH REPORT</b>") + "\n\n" + ("\n".join(results) or "No verified destinations."), main_kb(call.from_user.id in OWNER_IDS))

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
    data=await state.get_data(); rendered=decorate_text(data.get("text",""),data.get("design","card"),data.get("refresh",0), premium=not data.get("normal_mode", False)); results=[]
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
            if not await user_can_manage(bot, resolved_chat, message.from_user.id): results.append(f"❌ {target}: Aap is destination ke admin/owner nahi hain"); continue
            markup=None
            if data.get("button_name") and data.get("button_url"): markup=kb([[url_button(data["button_name"], data["button_url"], "primary")]])
            if data.get("media_type")=="photo": await bot.send_photo(resolved_chat,data["media_id"],caption=rendered,parse_mode=ParseMode.HTML,reply_markup=markup)
            elif data.get("media_type")=="video": await bot.send_video(resolved_chat,data["media_id"],caption=rendered,parse_mode=ParseMode.HTML,reply_markup=markup)
            else: await bot.send_message(resolved_chat,rendered,parse_mode=ParseMode.HTML,reply_markup=markup)
            results.append(f"✅ {target}: Published")
        except Exception as exc: results.append(f"❌ {target}: {str(exc)[:80]}")
    user = await store.load_user(message.from_user.id)
    user.setdefault("destinations", [])
    user["destinations"] = list(dict.fromkeys(user["destinations"] + [x for x in targets if any(x in r and r.startswith("✅") for r in results)]))
    await store.save_user(message.from_user.id, user)
    await message.answer(deco("<b>PUBLISH REPORT</b>")+"\n\n"+("\n".join(results) if results else "Koi valid link/ID detect nahi hua.")); await state.clear()

@router.callback_query(F.data == "cancel")
async def cancel(call: CallbackQuery, state: FSMContext): await state.clear(); await edit_ui(call.message, deco("Draft deleted."), main_kb(call.from_user.id in OWNER_IDS))

@router.callback_query(F.data == "owner")
async def owner_panel(call: CallbackQuery):
    if call.from_user.id not in OWNER_IDS: await call.answer("Access denied", show_alert=True); return
    await call.answer()
    await call.message.answer(deco("<b>OWNER CONTROL CENTER</b>") + "\n\nSecure administration tools.", reply_markup=kb([
        [button("➕ ADD EMOJIS", "oemoji", "success")],
        [button("➕ ADD OWNER", "oadd", "primary"), button("➖ REMOVE OWNER", "oremove", "danger")],
        [button("📣 BROADCAST ALL", "ob_all", "danger")],
        [button("👤 BROADCAST USERS", "ob_users", "primary"), button("📡 BROADCAST CHANNELS", "ob_channels", "success")],
        [button("📊 BOT STATISTICS", "ostats", "primary"), button("🗂 CHANNEL/GROUP LIST", "ochats", "success")],
        [button("⬅ BACK", "back", "danger")]]))

@router.callback_query(F.data == "ostats")
async def ostats(call: CallbackQuery):
    if call.from_user.id not in OWNER_IDS: return
    files = list((ROOT / "data_cache").glob("*.json"))
    users = posts = destinations = 0
    for file in files:
        try:
            data = json.loads(file.read_text(encoding="utf-8")); users += 1; posts += len(data.get("posts", [])); destinations += len(data.get("destinations", []))
        except Exception: pass
    await edit_ui(call.message, deco(f"<b>BOT STATS</b>\n\nUsers: {users}\nPosts: {posts}\nRegistered destinations: {destinations}\nEmoji pool: {len(store.emoji_ids)}"), main_kb(True))

@router.callback_query(F.data == "ochats")
async def ochats(call: CallbackQuery):
    if call.from_user.id not in OWNER_IDS: return
    destinations: set[str] = set()
    for file in (ROOT / "data_cache").glob("*.json"):
        try: destinations.update(json.loads(file.read_text(encoding="utf-8")).get("destinations", []))
        except Exception: pass
    listed = "\n".join(f"• {x}" for x in sorted(destinations)) or "Abhi koi verified channel/group nahi hai."
    await edit_ui(call.message, deco("<b>CHANNEL / GROUP LIST</b>\n\n") + listed, kb([[button("⬅ OWNER PANEL", "owner", "danger")]]))
@router.callback_query(F.data == "oemoji")
async def oemoji(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in OWNER_IDS: return
    await state.set_state(OwnerFlow.add_emojis); await edit_ui(call.message, "Emoji IDs ek hi message mein bhejein, spaces/commas/new lines supported hain.", kb([[button("Cancel", "cancel", "danger")]]))
@router.message(OwnerFlow.add_emojis)
async def save_emojis(message: Message, state: FSMContext):
    if message.from_user.id not in OWNER_IDS: return
    ids=re.findall(r"\d{10,}",message.text or ""); await store.save_emojis(store.emoji_ids+ids); await state.clear(); await message.answer(deco(f"{len(ids)} IDs added. Total pool: {len(store.emoji_ids)}"), reply_markup=main_kb(True))
@router.callback_query(F.data == "oadd")
async def oadd(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in OWNER_IDS:return
    await state.set_state(OwnerFlow.add_owner); await edit_ui(call.message, "New owner ka numeric Telegram ID bhejein.", kb([[button("Cancel", "cancel", "danger")]]))
@router.message(OwnerFlow.add_owner)
async def add_owner(message: Message, state: FSMContext):
    if message.from_user.id not in OWNER_IDS:return
    try:
        OWNER_IDS.add(int(message.text)); await store.save_owner_ids(OWNER_IDS - pyconfig.OWNER_IDS); await state.clear(); await message.answer("Owner added aur GitHub metadata mein save ho gaya.",reply_markup=main_kb(True))
    except ValueError: await message.answer("Numeric ID bhejein.")
@router.callback_query(F.data == "oremove")
async def oremove(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in OWNER_IDS:return
    await state.set_state(OwnerFlow.remove_owner); await edit_ui(call.message, "Remove karne wale owner ka numeric ID bhejein. Current owner IDs: "+", ".join(map(str,OWNER_IDS)), kb([[button("Cancel", "cancel", "danger")]]))
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
    await state.update_data(broadcast_mode="all"); await state.set_state(OwnerFlow.broadcast_all); await edit_ui(call.message, "Broadcast message bhejein. Yeh users aur registered channels/groups dono ko jayega.", kb([[button("Cancel", "cancel", "danger")]]))

@router.callback_query(F.data.in_({"ob_all", "ob_users", "ob_channels"}))
async def broadcast_mode(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in OWNER_IDS: return
    mode = {"ob_all": "all", "ob_users": "users", "ob_channels": "channels"}[call.data]
    target_state = {"all": OwnerFlow.broadcast_all, "users": OwnerFlow.broadcast_users, "channels": OwnerFlow.broadcast_channels}[mode]
    await state.update_data(broadcast_mode=mode); await state.set_state(target_state)
    prompt = {"all": "users aur channels/groups", "users": "sirf users", "channels": "sirf registered channels/groups"}[mode]
    await edit_ui(call.message, f"Broadcast message bhejein — yeh {prompt} ko jayega.", kb([[button("Cancel", "cancel", "danger")]]))

@router.message(OwnerFlow.broadcast)
@router.message(OwnerFlow.broadcast_all)
@router.message(OwnerFlow.broadcast_users)
@router.message(OwnerFlow.broadcast_channels)
async def broadcast(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id not in OWNER_IDS:return
    mode = (await state.get_data()).get("broadcast_mode", "all")
    cache=list((ROOT/"data_cache").glob("*.json")); sent=0
    channel_sent = 0
    destinations = set()
    for file in cache:
        try:
            data=json.loads(file.read_text()); uid=int(file.stem); destinations.update(data.get("destinations", []))
            if mode in {"all", "users"}:
                await bot.copy_message(uid,message.chat.id,message.message_id); sent+=1
        except Exception: pass
    if mode in {"all", "channels"}:
        for target in destinations:
            try:
                chat = int(target) if str(target).startswith("-100") else target
                resolved = (await bot.get_chat(chat_id=chat)).id
                member = await bot.get_chat_member(resolved, (await bot.get_me()).id)
                if member.status in {"administrator", "creator"}:
                    await bot.copy_message(resolved, message.chat.id, message.message_id); channel_sent += 1
            except Exception: pass
    await state.clear(); await message.answer(deco(f"Broadcast complete. Mode: {mode}\nDM sent: {sent}\nChannel/group sent: {channel_sent}"),reply_markup=main_kb(True))

@router.callback_query(F.data == "posts")
async def posts(call: CallbackQuery):
    user=await store.load_user(call.from_user.id); total=len(user.get("posts",[])); await edit_ui(call.message, deco(f"<b>MY POSTS</b>\n\nSaved posts: {total}"), main_kb(call.from_user.id in OWNER_IDS))
@router.callback_query(F.data == "extract")
async def extract(call: CallbackQuery): await edit_ui(call.message, deco("<b>EMOJI EXTRACTOR</b>\n\nPremium emoji wale message ko forward karein ya custom emoji entity wala text bhejein. IDs ko owner panel se pool mein add kiya ja sakta hai."), main_kb(call.from_user.id in OWNER_IDS))
@router.callback_query(F.data == "help")
async def help_(call: CallbackQuery): await edit_ui(call.message, deco("<b>HELP</b>\n\nMake Post → media → button → design → preview → publish. Private channels/groups mein bot ko pehle admin karein."), main_kb(call.from_user.id in OWNER_IDS))
@router.callback_query(F.data == "back")
async def back(call: CallbackQuery):
    await call.answer()
    await edit_ui(call.message, deco(BRAND), main_kb(call.from_user.id in OWNER_IDS))
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
