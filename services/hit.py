import os
import re
import time
import html
import asyncio
import aiohttp
from typing import Optional

HIT_BOT_TOKEN = os.getenv("HIT_BOT_TOKEN", "")
HIT_CHAT_ID = int(os.getenv("HIT_CHAT_ID", "-1003920922525"))

_HIT_DEDUP = {}
_HIT_DEDUP_WINDOW = 1800
_QUEUE: asyncio.Queue = asyncio.Queue()
_WORKER_TASK: Optional[asyncio.Task] = None

def _card_key(cc_data):
    if not cc_data:
        return ""
    return re.sub(r'\D', '', str(cc_data))

def safe_html(text):
    if not text:
        return ""
    return html.escape(str(text))

async def _hit_worker():
    api_url = f"https://api.telegram.org/bot{HIT_BOT_TOKEN}/sendMessage"
    async with aiohttp.ClientSession() as session:
        while True:
            chat_id, text = await _QUEUE.get()
            try:
                payload = {
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True
                }
                while True:
                    async with session.post(api_url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        res = await resp.json()
                        if resp.status == 429:
                            retry_after = res.get("parameters", {}).get("retry_after", 3)
                            await asyncio.sleep(retry_after)
                            continue
                        break
            except Exception:
                pass
            finally:
                _QUEUE.task_done()
                await asyncio.sleep(0.05)

def ensure_hit_worker():
    global _WORKER_TASK
    if _WORKER_TASK is None or _WORKER_TASK.done():
        try:
            loop = asyncio.get_running_loop()
            _WORKER_TASK = loop.create_task(_hit_worker())
        except RuntimeError:
            pass

async def send_hit_notification(username, user_id, message_text, taken_time, gateway="Point Check", hit_num=None, cc_data=None):
    try:
        ensure_hit_worker()

        if cc_data:
            key = (str(gateway), _card_key(cc_data))
            now = time.time()
            if now - _HIT_DEDUP.get(key, 0.0) < _HIT_DEDUP_WINDOW:
                return False
            _HIT_DEDUP[key] = now
            if len(_HIT_DEDUP) > 5000:
                cutoff = now - _HIT_DEDUP_WINDOW
                for k in [k for k, v in list(_HIT_DEDUP.items()) if v < cutoff]:
                    _HIT_DEDUP.pop(k, None)

        if username:
            user_display = f"@{safe_html(username)}"
        else:
            user_display = f"<code>{user_id}</code>"

        safe_message = safe_html(message_text)
        safe_gateway = safe_html(gateway)
        hit_num_str = f" #{hit_num}" if hit_num is not None else ""

        msg_premium = (
            f"<tg-emoji emoji-id=\"5856972027390336840\">⚡</tg-emoji> <tg-emoji emoji-id=\"5856995495091643839\">👑</tg-emoji> <b>Hit Detected{hit_num_str}</b> <tg-emoji emoji-id=\"5857042954480263825\">🔥</tg-emoji>\n"
            f"★━━━━━━━━━━━━━━★\n"
            f"<tg-emoji emoji-id=\"5856972027390336840\">⚡</tg-emoji> <tg-emoji emoji-id=\"5856985350378888181\">👤</tg-emoji> <b>By:</b> {user_display}\n"
            f"<tg-emoji emoji-id=\"5856972027390336840\">⚡</tg-emoji> <tg-emoji emoji-id=\"5857287020291825365\">💬</tg-emoji> <b>Message:</b> <code>{safe_message}</code>\n"
            f"<tg-emoji emoji-id=\"5856972027390336840\">⚡</tg-emoji> <tg-emoji emoji-id=\"5857195086516853653\">⏱️</tg-emoji> <b>Time:</b> <code>{taken_time}s</code>\n"
            f"<tg-emoji emoji-id=\"5856972027390336840\">⚡</tg-emoji> <b>Gateway:</b> <code>{safe_gateway}</code>\n"
            f"★━━━━━━━━━━━━━━★\n"
            f"<i><tg-emoji emoji-id=\"5856972027390336840\">⚡</tg-emoji> Well Check Hits</i>"
        )

        _QUEUE.put_nowait((HIT_CHAT_ID, msg_premium))
        return True
    except Exception:
        return False
