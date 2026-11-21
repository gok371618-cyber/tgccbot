import asyncio, json, os, time
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
BROADCASTS_FILE = os.path.join(DATA_DIR, "broadcasts.json")
MAL_FILE = os.path.join(DATA_DIR, "mal.json")

def load_mal_users() -> set:
    if not os.path.exists(MAL_FILE):
        return set()
    try:
        with open(MAL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return set(str(x) for x in data)
            elif isinstance(data, dict):
                return set(str(k) for k in data.keys())
            return set()
    except Exception:
        return set()

def save_mal_users(users: set):
    try:
        with open(MAL_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(users)), f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def add_mal_user(uid: int):
    mal_set = load_mal_users()
    s_uid = str(uid)
    if s_uid not in mal_set:
        mal_set.add(s_uid)
        save_mal_users(mal_set)

def load_broadcasts() -> dict:
    if not os.path.exists(BROADCASTS_FILE):
        return {}
    try:
        with open(BROADCASTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_broadcasts(data: dict):
    with open(BROADCASTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

async def send_to_user(bot: Bot, uid: int, text: str, sem: asyncio.Semaphore, stats: dict, sent_map: dict):
    async with sem:
        try:
            msg = await bot.send_message(uid, text)
            sent_map[str(uid)] = msg.message_id
            stats["success"] += 1
        except TelegramForbiddenError:
                                                             
            add_mal_user(uid)
            stats["failed"] += 1
            stats["blocked"] += 1
        except Exception as exc:
            err_str = str(exc).lower()
            if any(k in err_str for k in ["blocked", "user is deactivated", "chat not found", "bot was blocked"]):
                add_mal_user(uid)
                stats["blocked"] += 1
            stats["failed"] += 1

async def delete_from_user(bot: Bot, uid: int, msg_id: int, sem: asyncio.Semaphore, stats: dict):
    async with sem:
        try:
            await bot.delete_message(uid, msg_id)
            stats["deleted"] += 1
        except Exception:
            stats["failed"] += 1

async def broadcast_announcement(bot: Bot, user_ids: list, text: str, concurrency: int = 25) -> dict:
    t0 = time.time()

                                                                        
    mal_set = load_mal_users()
    target_ids = [uid for uid in user_ids if str(uid) not in mal_set]

    sem = asyncio.Semaphore(concurrency)
    stats = {
        "total": len(target_ids),
        "skipped_mal": len(user_ids) - len(target_ids),
        "success": 0,
        "failed": 0,
        "blocked": 0
    }
    sent_map = {}

    tasks = [
        asyncio.create_task(send_to_user(bot, int(uid), text, sem, stats, sent_map))
        for uid in target_ids
    ]
    if tasks:
        await asyncio.gather(*tasks)

    duration = round(time.time() - t0, 2)
    stats["duration"] = duration

    bid = f"BC-{int(time.time())}"
    bcasts = load_broadcasts()
    bcasts[bid] = {
        "id": bid,
        "text": text[:60] + ("..." if len(text) > 60 else ""),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_targets": len(target_ids),
        "success": stats["success"],
        "failed": stats["failed"],
        "messages": sent_map
    }
    save_broadcasts(bcasts)

    stats["broadcast_id"] = bid
    return stats

async def delete_announcement(bot: Bot, broadcast_id: str, concurrency: int = 25) -> dict:
    t0 = time.time()
    bcasts = load_broadcasts()
    if broadcast_id not in bcasts:
        return {"success": False, "error": "Broadcast ID not found."}

    bdata = bcasts[broadcast_id]
    messages = bdata.get("messages", {})

    sem = asyncio.Semaphore(concurrency)
    stats = {"total": len(messages), "deleted": 0, "failed": 0}

    tasks = [
        asyncio.create_task(delete_from_user(bot, int(uid), int(mid), sem, stats))
        for uid, mid in messages.items()
    ]
    if tasks:
        await asyncio.gather(*tasks)

    duration = round(time.time() - t0, 2)
    stats["duration"] = duration
    stats["success"] = True

    del bcasts[broadcast_id]
    save_broadcasts(bcasts)

    return stats
