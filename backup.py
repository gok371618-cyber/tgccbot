import asyncio
import io
import json
import os
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
import pyzipper
from aiogram import Bot
from aiogram.types import BufferedInputFile
from aiogram.client.default import DefaultBotProperties

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BACKUP_CHAT_ID = -1004436457671
ZIP_PASSWORD = b"xrisune2442!E"
BACKUP_INTERVAL = 15 * 60
STATE_FILE = os.path.join("data", "backup_state.json")
EMOJI_CACHE_FILE = os.path.join("data", "emoji_cache.json")

def load_emoji_map():
    if os.path.exists(EMOJI_CACHE_FILE):
        try:
            with open(EMOJI_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

EMOJI_DATA = load_emoji_map()

def emoji_id(char: str):
    clean = char.replace("\ufe0f", "")
    return EMOJI_DATA.get(char) or EMOJI_DATA.get(clean)

def e(char: str) -> str:
    cid = emoji_id(char)
    if cid:
        return f'<tg-emoji emoji-id="{cid}">{char}</tg-emoji>'
    return char

def load_last_message_id():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("last_message_id")
        except Exception:
            pass
    return None

def save_last_message_id(msg_id):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_message_id": msg_id, "updated_at": time.time()}, f)
    except Exception:
        pass

def create_backup_zip():
    buf = io.BytesIO()
    file_count = 0
    total_uncompressed = 0

    with pyzipper.AESZipFile(
        buf,
        "w",
        compression=pyzipper.ZIP_DEFLATED,
        encryption=pyzipper.WZ_AES
    ) as zf:
        zf.setpassword(ZIP_PASSWORD)
        for root, dirs, files in os.walk("."):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", ".pytest_cache", "venv", ".venv")]
            for file in files:
                if file.endswith(".zip") or file == "backup_state.json":
                    continue
                fp = os.path.join(root, file)
                rel = os.path.relpath(fp, ".")
                try:
                    zf.write(fp, arcname=rel)
                    file_count += 1
                    total_uncompressed += os.path.getsize(fp)
                except Exception:
                    pass

    zip_bytes = buf.getvalue()
    return zip_bytes, file_count, total_uncompressed

async def perform_backup(bot: Bot, trigger: str = "SCHEDULED"):
    global EMOJI_DATA
    EMOJI_DATA = load_emoji_map()

    old_msg_id = load_last_message_id()
    if old_msg_id:
        try:
            await bot.delete_message(chat_id=BACKUP_CHAT_ID, message_id=old_msg_id)
        except Exception:
            pass

    loop = asyncio.get_running_loop()
    zip_data, count, uncomp_size = await loop.run_in_executor(None, create_backup_zip)
    now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y | %H:%M:%S UTC")
    zip_size_mb = round(len(zip_data) / (1024 * 1024), 2)
    uncomp_mb = round(uncomp_size / (1024 * 1024), 2)
    filename = f"backup_{int(time.time())}.zip"

    caption = (
        f"{e('🔒')} <b>Automated Project Backup</b> ({trigger})\n\n"
        f"▫️ {e('📅')} <b>Timestamp:</b> <code>{now_str}</code>\n"
        f"▫️ {e('📁')} <b>Files Count:</b> <code>{count}</code> files\n"
        f"▫️ {e('📦')} <b>Compressed Size:</b> <code>{zip_size_mb} MB</code> (Original: <code>{uncomp_mb} MB</code>)\n"
        f"▫️ {e('🔑')} <b>Encryption:</b> <code>AES-256 (Password Protected)</code>\n"
        f"▫️ {e('⏱️')} <b>Interval:</b> Every 15 minutes / On Restart\n\n"
        f"<i>Previous backup message was automatically deleted before sending.</i>"
    )

    doc = BufferedInputFile(zip_data, filename=filename)
    sent_msg = await bot.send_document(
        chat_id=BACKUP_CHAT_ID,
        document=doc,
        caption=caption
    )
    save_last_message_id(sent_msg.message_id)
    return sent_msg.message_id

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "log.txt")

def write_log(level: str, msg: str):
    now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")
    line = f"[{now_str}] [{level.upper()}] [BACKUP] {msg}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    print(line.rstrip())

async def backup_worker(bot: Bot):
    write_log("INFO", "Backup worker started.")
    while True:
        try:
            write_log("INFO", "Executing startup/restart backup...")
            await perform_backup(bot, trigger="RESTART / STARTUP")
            write_log("INFO", "Startup backup completed successfully.")
            break
        except Exception as ex:
            write_log("ERROR", f"Startup backup failed, retrying in 5s: {ex}")
            await asyncio.sleep(5)

    while True:
        try:
            await asyncio.sleep(BACKUP_INTERVAL)
            write_log("INFO", "Executing scheduled backup...")
            await perform_backup(bot, trigger="SCHEDULED")
            write_log("INFO", "Scheduled backup completed successfully.")
        except asyncio.CancelledError:
            write_log("INFO", "Backup worker cancelled.")
            break
        except Exception as ex:
            write_log("ERROR", f"Scheduled backup failed: {ex}")
            await asyncio.sleep(10)

async def main():
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    try:
        await backup_worker(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())