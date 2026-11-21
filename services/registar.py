import os
import html
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO_PATH = os.path.join(BASE_DIR, "registar.mp4")
IMAGE_PATH = os.path.join(BASE_DIR, "registar.png")

def is_user_registered(db: dict, user_id: int) -> bool:
    return str(user_id) in db

def register_user_in_db(db: dict, user, daily_limit: int = 200, tier: str = "free", save_func=None) -> dict:
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    uid = str(user.id)
    new_user = {
        "username": user.username or "",
        "first_name": user.first_name or "",
        "tier": tier,
        "banned": False,
        "used": 0,
        "total": daily_limit,
        "last_reset": today,
        "total_checks": 0,
        "successful_checks": 0
    }
    db[uid] = new_user
    if save_func:
        save_func(db)
    return new_user

def get_register_text(user, e_func=None) -> str:
    name = html.escape(user.first_name or "User")
    e_wave = e_func("👋") if e_func else "👋"
    e_warn = e_func("⚠️") if e_func else "⚠️"
    e_zap = e_func("⚡") if e_func else "⚡"

    return (
        f"{e_wave} <b>Welcome, {name}!</b>\n\n"
        f"{e_warn} <b>Registration Required</b>\n"
        f"{e_zap} Send <code>/registar</code> or tap below to register."
    )

def get_register_kb(emoji_id_func=None) -> InlineKeyboardMarkup:
    icon = emoji_id_func("📝") if emoji_id_func else None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Register Now", callback_data="btn_do_register", icon_custom_emoji_id=icon, style="success")]
    ])

CACHED_VIDEO_FILE_ID = "BAACAgQAAxkDAAEBKXxq-0RxOocjFYDsonjIxf5J9RCYIAACPh4AAoNX2VPHTG_GnwlSvj0E"

async def send_registration_screen(event, user, e_func=None, emoji_id_func=None):
    text = get_register_text(user, e_func)
    kb = get_register_kb(emoji_id_func)

    global CACHED_VIDEO_FILE_ID
    if CACHED_VIDEO_FILE_ID:
        try:
            if isinstance(event, Message):
                await event.answer_video(video=CACHED_VIDEO_FILE_ID, caption=text, reply_markup=kb)
            elif isinstance(event, CallbackQuery):
                await event.message.answer_video(video=CACHED_VIDEO_FILE_ID, caption=text, reply_markup=kb)
                await event.answer()
            return
        except Exception:
            pass

    if os.path.exists(VIDEO_PATH):
        video = FSInputFile(VIDEO_PATH)
        sent = None
        if isinstance(event, Message):
            sent = await event.answer_video(video=video, caption=text, reply_markup=kb)
        elif isinstance(event, CallbackQuery):
            sent = await event.message.answer_video(video=video, caption=text, reply_markup=kb)
            await event.answer()
        if sent and getattr(sent, "video", None):
            CACHED_VIDEO_FILE_ID = sent.video.file_id
    elif os.path.exists(IMAGE_PATH):
        photo = FSInputFile(IMAGE_PATH)
        if isinstance(event, Message):
            await event.answer_photo(photo=photo, caption=text, reply_markup=kb)
        elif isinstance(event, CallbackQuery):
            await event.message.answer_photo(photo=photo, caption=text, reply_markup=kb)
            await event.answer()
    else:
        if isinstance(event, Message):
            await event.answer(text, reply_markup=kb)
        elif isinstance(event, CallbackQuery):
            await event.message.answer(text, reply_markup=kb)
            await event.answer()
