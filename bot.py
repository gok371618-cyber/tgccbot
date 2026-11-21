import asyncio, io, json, os, re, threading, uuid, time, html, traceback
from datetime import datetime, timezone
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery, BufferedInputFile

from curl_cffi import requests

from services.puan import parse_cc
from services.bin import query_bin
from services.broadcast import broadcast_announcement, delete_announcement, load_broadcasts
from services.hit import send_hit_notification
from services.registar import is_user_registered, register_user_in_db, send_registration_screen
from gates import GATES, get_gate_handler

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
CHANNEL_LINK = os.getenv("CHANNEL_LINK")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "log.txt")
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

def write_log(level: str, msg: str):
    now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")
    line = f"[{now_str}] [{level.upper()}] {msg}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    print(line.rstrip())

DB_FILE = os.path.join(DATA_DIR, "db.json")
KEYS_FILE = os.path.join(DATA_DIR, "keys.json")
PROXIES_FILE = os.path.join(DATA_DIR, "proxies.txt")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
EMOJI_CACHE_FILE = os.path.join(DATA_DIR, "emoji_cache.json")

EMOJI_SETS = ["NewsEmoji", "FinanceEmoji", "AnimatedEmoji", "PremiumIcons", "DocsEmoji"]

TIER_FREE = "free"
TIER_VIP = "vip"
TIER_PREMIUM = "premium"
TIER_UNLIMITED = "unlimited"

DAILY_LIMITS = {
    TIER_FREE: 200,
    TIER_VIP: 500,
    TIER_PREMIUM: 1000,
    TIER_UNLIMITED: 999999999
}

router = Router()
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

class MapuState(StatesGroup):
    confirm = State()

class TxtCheckState(StatesGroup):
    confirm = State()

async def handle_single_gate_check(m: Message, gate_info: dict, raw_card_text: str = None):
    gate_name = gate_info.get("name", "Unknown")
    gate_id = gate_info.get("id")
    cmd = gate_info.get("command")

    if m.from_user.id != ADMIN_ID and is_gate_maintenance(gate_name):
        await m.answer(f"{e('🛠️')} <b>{gate_name} Gate is currently under maintenance.</b>\nPlease try again later.")
        return

    db = load_db()
    u = get_user(db, m.from_user)

                                                              
    search_text = raw_card_text if raw_card_text else m.text
    cards = parse_cards(search_text)
    if not cards:
        await m.answer(f"{e('⚠️')} Invalid card format.\nUsage: <code>/{cmd} cardno|month|year|cvv</code>")
        return
    if remaining(u) < 1:
        await m.answer(
            f"{e('🚫')} You have reached your check limit!\n\n"
            f"▫️ Upgrade plan: <code>/buy</code>\n"
            f"▫️ Contact Admin: <b>{ADMIN_USERNAME}</b>"
        )
        return

    wait = await m.answer(f"{e('🔍')} Checking card ({gate_name}), please wait...")
    start_t = time.time()

                               
    blocked, block_reason = await asyncio.get_event_loop().run_in_executor(
        None, is_blocked_card_type, cards[0][0]
    )
    if blocked:
        card_line = f"{cards[0][0]}|{cards[0][1]}|{cards[0][2]}|{cards[0][3]}"
        user_mention = f"@{html.escape(m.from_user.username)}" if m.from_user.username else f"<code>{m.from_user.id}</code>"
        msg_blocked = (
            f"{e('⚡')} {e('👑')} <b>Check Result</b> {e('🔥')}\n"
            f"★━━━━━━━━━━━━━━★\n"
            f"{e('💳')} <b>Card:</b> <code>{card_line}</code>\n"
            f"{e('❌')} <b>Status:</b> <b>Blocked!</b>\n"
            f"{e('⚡')} <b>Gateway:</b> <code>{html.escape(gate_name)}</code>\n"
            f"{e('💬')} <b>Response:</b> <code>{html.escape(block_reason)}</code>\n"
            f"★━━━━━━━━━━━━━━★\n"
            f"{e('⏳')} <b>Available:</b> <code>{remaining_str(u)}</code> • {e('👤')} <b>By:</b> {user_mention}"
        )
        await wait.edit_text(msg_blocked)
        return

    try:
        res = await asyncio.get_event_loop().run_in_executor(
            None, execute_gate_query, gate_id, *cards[0]
        )
    except Exception as exc:
        res = f"{e('⚠️')} Error: {censor_text(str(exc))}"

    taken = round(time.time() - start_t, 2)
    res = censor_text(str(res))
    display_res = clean_gate_result(res)
    u["used"] += 1
    u["total_checks"] = u.get("total_checks", 0) + 1
    if "Approved" in res:
        u["successful_checks"] = u.get("successful_checks", 0) + 1
        card_str = f"{cards[0][0]}|{cards[0][1]}|{cards[0][2]}|{cards[0][3]}"
        global_hit_num = get_next_global_hit_count()
        await send_hit_notification(
            username=m.from_user.username,
            user_id=m.from_user.id,
            message_text=display_res,
            taken_time=taken,
            gateway=gate_name,
            hit_num=global_hit_num,
            cc_data=card_str
        )
    save_db(db)

    user_mention = f"@{html.escape(m.from_user.username)}" if m.from_user.username else f"<code>{m.from_user.id}</code>"
    card_line = f"{cards[0][0]}|{cards[0][1]}|{cards[0][2]}|{cards[0][3]}"

    if "Approved" in res:
        status_line = f"{e('✅')} <b>Status:</b> <b>Approved!</b>"
    elif "Declined" in res:
        status_line = f"{e('❌')} <b>Status:</b> <b>Declined!</b>"
    else:
        status_line = f"{e('⚠️')} <b>Status:</b> <b>Error!</b>"

    msg_card = (
        f"{e('⚡')} {e('👑')} <b>Check Result</b> {e('🔥')}\n"
        f"★━━━━━━━━━━━━━━★\n"
        f"{e('💳')} <b>Card:</b> <code>{card_line}</code>\n"
        f"{status_line}\n"
        f"{e('⚡')} <b>Gateway:</b> <code>{html.escape(gate_name)}</code>\n"
        f"{e('💬')} <b>Response:</b> <code>{html.escape(display_res)}</code>\n"
        f"{e('⏱️')} <b>Time:</b> <code>{taken}s</code>\n"
        f"★━━━━━━━━━━━━━━★\n"
        f"{e('⏳')} <b>Available:</b> <code>{remaining_str(u)}</code> • {e('👤')} <b>By:</b> {user_mention}"
    )

    await wait.edit_text(msg_card)

class GateCheckState(StatesGroup):
    waiting_card = State()

def register_gate_commands(r: Router):
    for g_id, g_info in GATES.items():
        cmd = g_info.get("command")
        if not cmd:
            continue

        def _make_handler(info):
            async def _gate_cmd_handler(m: Message):
                await handle_single_gate_check(m, info)
            return _gate_cmd_handler

        handler = require_channel(_make_handler(g_info))
        r.message.register(handler, Command(cmd))

class AdminActionState(StatesGroup):
    waiting_input = State()

EMOJI_DATA = {}
EMOJI_ALIASES = {
    "⏳": "⌛",
    "📢": "📣",
    "✅": "✔️",
    "📋": "📄",
    "🏁": "🚩",
    "🛠️": "⚙️",
    "🛠": "⚙️",
    "👤": "🧑‍💻",
    "📝": "✍️",
    "➖": "🔽",
}

async def load_emoji_pack(bot: Bot):
    global EMOJI_DATA
    if os.path.exists(EMOJI_CACHE_FILE):
        try:
            with open(EMOJI_CACHE_FILE, "r", encoding="utf-8") as f:
                EMOJI_DATA = json.load(f)
        except Exception:
            pass

    for pack_name in EMOJI_SETS:
        try:
            st_set = await bot.get_sticker_set(pack_name)
            for st in st_set.stickers:
                if st.custom_emoji_id:
                    cid = str(st.custom_emoji_id)
                    EMOJI_DATA[st.emoji] = cid
                    EMOJI_DATA[st.emoji.replace("\ufe0f", "")] = cid
        except Exception:
            pass

    for k, v in EMOJI_ALIASES.items():
        cid = EMOJI_DATA.get(v) or EMOJI_DATA.get(v.replace("\ufe0f", ""))
        if cid:
            EMOJI_DATA[k] = cid
            EMOJI_DATA[k.replace("\ufe0f", "")] = cid

    try:
        with open(EMOJI_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(EMOJI_DATA, f, ensure_ascii=False)
    except Exception:
        pass

def emoji_id(char: str):
    clean = char.replace("\ufe0f", "")
    return EMOJI_DATA.get(char) or EMOJI_DATA.get(clean) or EMOJI_DATA.get(EMOJI_ALIASES.get(char, "")) or EMOJI_DATA.get(EMOJI_ALIASES.get(clean, ""))

def e(char: str) -> str:
    cid = emoji_id(char)
    if cid:
        return f'<tg-emoji emoji-id="{cid}">{char}</tg-emoji>'
    return char

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {"maintenance": False, "gate_maintenance": {}}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "gate_maintenance" not in data:
                data["gate_maintenance"] = {}
            return data
    except Exception:
        return {"maintenance": False, "gate_maintenance": {}}

def save_settings(data):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_maintenance_mode():
    return load_settings().get("maintenance", False)

def is_gate_maintenance(gate_name="Point"):
    gm = load_settings().get("gate_maintenance", {})
    return bool(gm.get(gate_name, False))

def set_gate_maintenance(gate_name, is_maint):
    s = load_settings()
    if "gate_maintenance" not in s:
        s["gate_maintenance"] = {}
    s["gate_maintenance"][gate_name] = bool(is_maint)
    save_settings(s)

def get_next_global_hit_count() -> int:
    s = load_settings()
    current = s.get("total_hits_count")
    if current is None:
        db = load_db()
        current = sum(u.get("successful_checks", 0) for u in db.values() if isinstance(u, dict))
    current += 1
    s["total_hits_count"] = current
    save_settings(s)
    return current

def get_current_global_hit_count() -> int:
    s = load_settings()
    current = s.get("total_hits_count")
    if current is None:
        db = load_db()
        current = sum(u.get("successful_checks", 0) for u in db.values() if isinstance(u, dict))
    return current

def clean_gate_result(text):
    text = str(text or "").strip()
    m = re.match(r'^(?:Approved!|Declined!|Approved|Declined)\s*[-–:]*\s*(.*)$', text, re.IGNORECASE)
    if m and m.group(1).strip():
        return m.group(1).strip()
    return text

def load_db():
    if not os.path.exists(DB_FILE):
        return {}
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_keys():
    if not os.path.exists(KEYS_FILE):
        return {}
    try:
        with open(KEYS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_keys(data):
    with open(KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_proxy_list():
    if not os.path.exists(PROXIES_FILE):
        return []
    try:
        with open(PROXIES_FILE, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
    except Exception:
        return []

def save_proxy_list(proxies):
    with open(PROXIES_FILE, "w", encoding="utf-8") as f:
        for p in proxies:
            f.write(f"{p}\n")

def normalize_proxy_string(raw: str) -> str:
    p = raw.strip()
    if p.startswith("http://") or p.startswith("https://") or p.startswith("socks5://"):
        return p
    parts = p.split(":")
    if len(parts) == 4:
        if parts[1].isdigit():
            ip, port, user, pwd = parts[0], parts[1], parts[2], parts[3]
            return f"http://{user}:{pwd}@{ip}:{port}"
        if parts[3].isdigit():
            user, pwd, ip, port = parts[0], parts[1], parts[2], parts[3]
            return f"http://{user}:{pwd}@{ip}:{port}"
    return f"http://{p}"

def check_proxy_health(proxy_str):
    p = normalize_proxy_string(proxy_str)
    t0 = time.time()
    try:
        r = requests.get("https://api.ipify.org?format=json", proxies={"http": p, "https": p}, timeout=8)
        dur = round(time.time() - t0, 2)
        if r.status_code == 200:
            ip = r.json().get("ip", "Unknown")
            return True, dur, ip, p
        return False, dur, f"HTTP {r.status_code}", p
    except Exception as exc:
        dur = round(time.time() - t0, 2)
        return False, dur, str(exc), p

def get_today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def get_user(db, user, auto_create=False):
    uid = str(user.id)
    today = get_today_str()
    current_username = user.username or ""
    current_first_name = user.first_name or ""
    if uid not in db:
        if not auto_create:
            return None
        db[uid] = {
            "username": current_username,
            "first_name": current_first_name,
            "tier": TIER_FREE,
            "banned": False,
            "used": 0,
            "total": DAILY_LIMITS[TIER_FREE],
            "last_reset": today,
            "total_checks": 0,
            "successful_checks": 0
        }
        save_db(db)
    else:
        u = db[uid]
        updated = False
        if u.get("username") != current_username:
            u["username"] = current_username
            updated = True
        if u.get("first_name") != current_first_name:
            u["first_name"] = current_first_name
            updated = True
        if "tier" not in u:
            u["tier"] = TIER_FREE
            updated = True
        if u.get("banned"):
                                 
            ban_until = u.get("banned_until")
            if ban_until and time.time() > ban_until:
                u["banned"] = False
                u["banned_until"] = None
                updated = True
            else:
                pass
        if "last_reset" not in u:
            u["last_reset"] = today
            updated = True
        if "total_checks" not in u:
            u["total_checks"] = u.get("used", 0)
            updated = True
        if "successful_checks" not in u:
            u["successful_checks"] = 0
            updated = True

        if u.get("last_reset") != today:
            u["used"] = 0
            u["last_reset"] = today
                                                      
            if u.get("tier_expiry") and time.time() > u["tier_expiry"]:
                u["tier"] = TIER_FREE
                u["total"] = DAILY_LIMITS[TIER_FREE]
                u["tier_expiry"] = None
            else:
                u["total"] = DAILY_LIMITS.get(u.get("tier", TIER_FREE), 200)
            updated = True

        if updated:
            save_db(db)

    return db[uid]

def find_user_by_query(db: dict, query: str):
    query = (query or "").strip().lstrip("@").lower()
    if not query:
        return None, None
                                 
    if query in db:
        return query, db[query]
                                         
    for uid, u in db.items():
        uname = (u.get("username") or "").lower()
        if uname == query:
            return uid, u
    return None, None

def remaining(user_data):
    if user_data.get("tier") == TIER_UNLIMITED:
        return 999999999
    return max(0, user_data.get("total", 0) - user_data.get("used", 0))

def remaining_str(user_data):
    if user_data.get("tier") == TIER_UNLIMITED:
        return "Unlimited"
    return f"{remaining(user_data)}/{user_data.get('total', 0)}"

def parse_cards(text):
    cards = []
    for token in re.split(r"[\s]+", (text or "").strip()):
        if not token:
            continue
        try:
            c = parse_cc(token)
            if c:
                cards.append(c)
        except Exception:
            pass
    return cards

def censor_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'https?://[^:@\s]+:[^@\s]+@[^\s/:]+(?::\d+)?', '[PROXY]', text)
    text = re.sub(r'https?://[^\s<>"\')]+', '[SENSITIVE_URL]', text)
    text = re.sub(r'(?i)\b(?:[\w\-]+\.)*(?:hepsiburada|hepsipay|voltran-gw|sardes)[\w\.\-]*\b', '[GATEWAY]', text)
    text = re.sub(r'(?i)\b(?:[\w\-]+\.)+(?:com|net|org|com\.tr|tr)\b', '[GATEWAY]', text)
    text = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?\b', '[IP]', text)
    return text

def is_blocked_card_type(card_no: str) -> tuple[bool, str]:
    clean_no = re.sub(r"[^\d]", "", str(card_no))
    if len(clean_no) < 6:
        return False, ""
    try:
        bin_info = query_bin(clean_no[:8])
        if bin_info.get("success"):
            c_type = str(bin_info.get("type", "")).upper()
            brand = str(bin_info.get("brand", "")).upper()
            is_prepaid = bin_info.get("prepaid", False) or "PREPAID" in c_type or "PREPAID" in brand
            is_debit = "DEBIT" in c_type or "DEBIT" in brand

            if is_prepaid:
                return True, "Prepaid Cards are not allowed."
            if is_debit:
                return True, "Debit Cards are not allowed."
    except Exception:
        pass
    return False, ""

GATE_HANDLERS = {
    gate_id: get_gate_handler(info) for gate_id, info in GATES.items()
}

def execute_gate_query(gate_id: str, cn: str, em: str, ey: str, cv: str) -> str:
    func = GATE_HANDLERS.get(gate_id)
    if not func:
        return f"{e('⚠️')} Error: Gate handler not found for {gate_id}"
    lock = threading.Lock()
    with lock:
        try:
            res = func(cn, em, ey, cv)
            res = str(res)
            if res.startswith("⚠️"):
                res = f"{e('⚠️')}{res[1:]}"
            return censor_text(res)
        except Exception as exc:
            return f"{e('⚠️')} Error: {censor_text(str(exc))}"

def join_message():
    return (
        f"{e('🔒')} <b>Access Locked!</b>\n\n"
        f"{e('📢')} To use this bot, you must join our official channel first.\n\n"
        f"{e('➡️')} Join the channel, then tap <b>I Joined</b>.\n"
    )

def maintenance_message():
    return (
        f"{e('🛠️')} <b>Bot Under Maintenance</b>\n\n"
        f"We are currently undergoing scheduled system updates and maintenance.\n"
        f"All services will be back online shortly.\n\n"
        f"For urgent questions, contact admin: <b>{ADMIN_USERNAME}</b>"
    )

def welcome_text(user):
    name = html.escape(user.first_name or "User")
    mention = f'<a href="tg://user?id={user.id}">{name}</a>'
    return (
        f"{e('👋')} <b>Welcome to Well Check, {mention}!</b>\n\n"
        f"{e('💳')} Check your credit card rewards and points instantly."
    )

def get_join_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Join Channel", url=CHANNEL_LINK, icon_custom_emoji_id=emoji_id("📢"))],
        [InlineKeyboardButton(text="I Joined", callback_data="check_join", icon_custom_emoji_id=emoji_id("✅"), style="success")],
    ])

def get_start_kb(is_admin: bool):
    rows = [
        [
            InlineKeyboardButton(text="Gates", callback_data="open_gates_menu", icon_custom_emoji_id=emoji_id("💳"), style="primary"),
            InlineKeyboardButton(text="BIN Lookup", callback_data="howto_bin", icon_custom_emoji_id=emoji_id("🔍"), style="primary")
        ],
        [
            InlineKeyboardButton(text="My Profile", callback_data="open_profile", icon_custom_emoji_id=emoji_id("📋"), style="success"),
            InlineKeyboardButton(text="Upgrade Plan", callback_data="open_upgrade", icon_custom_emoji_id=emoji_id("🎁"), style="success")
        ]
    ]
    if is_admin:
        rows.append([
            InlineKeyboardButton(text="Admin Panel", callback_data="admin_home", icon_custom_emoji_id=emoji_id("👑"), style="danger")
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def profile_text(user, u):
    t = u.get("tier", TIER_FREE).upper()
    expiry_str = "Lifetime"
    if u.get("tier_expiry"):
        expiry_dt = datetime.fromtimestamp(u["tier_expiry"], timezone.utc)
        expiry_str = expiry_dt.strftime("%d.%m.%Y %H:%M") + " UTC"
    elif u.get("tier") == TIER_FREE:
        expiry_str = "Free Tier"

    return (
        f"{e('👤')} <b>User Profile</b>\n\n"
        f"<b>ID:</b> <code>{user.id}</code>\n"
        f"<b>Name:</b> {html.escape(user.first_name or 'N/A')}\n"
        f"<b>Username:</b> @{user.username or 'none'}\n"
        f"<b>Plan:</b> <b>{t}</b>\n"
        f"<b>Expires:</b> <code>{expiry_str}</code>\n"
        f"<b>Available Checks:</b> <b>{remaining_str(u)}</b>\n"
        f"<b>Total Checked:</b> <b>{u.get('total_checks', 0)}</b>\n"
        f"<b>Successful Hits:</b> <b>{u.get('successful_checks', 0)}</b>\n"
        f"<b>Status:</b> {'🚫 Banned' if u.get('banned') else '✅ Active'}"
    )

STAR_PLANS = {
    "vip_1d": {
        "title": "VIP Plan (1 Day)",
        "stars": 75,
        "description": "500 checks/day, fast proxy pool, 1 day active",
        "tier": TIER_VIP,
        "days": 1,
        "limit": 500
    },
    "vip_3d": {
        "title": "VIP Plan (3 Days)",
        "stars": 175,
        "description": "500 checks/day, fast proxy pool, 3 days active",
        "tier": TIER_VIP,
        "days": 3,
        "limit": 500
    },
    "vip_7d": {
        "title": "VIP Plan (1 Week)",
        "stars": 350,
        "description": "500 checks/day, fast proxy pool, 7 days active",
        "tier": TIER_VIP,
        "days": 7,
        "limit": 500
    },
    "vip_30d": {
        "title": "VIP Plan (1 Month)",
        "stars": 750,
        "description": "500 checks/day, fast proxy pool, 30 days active",
        "tier": TIER_VIP,
        "days": 30,
        "limit": 500
    },
    "prem_1d": {
        "title": "PREMIUM Plan (1 Day)",
        "stars": 125,
        "description": "1000 checks/day, priority dedicated proxies, 1 day active",
        "tier": TIER_PREMIUM,
        "days": 1,
        "limit": 1000
    },
    "prem_3d": {
        "title": "PREMIUM Plan (3 Days)",
        "stars": 290,
        "description": "1000 checks/day, priority dedicated proxies, 3 days active",
        "tier": TIER_PREMIUM,
        "days": 3,
        "limit": 1000
    },
    "prem_7d": {
        "title": "PREMIUM Plan (1 Week)",
        "stars": 590,
        "description": "1000 checks/day, priority dedicated proxies, 7 days active",
        "tier": TIER_PREMIUM,
        "days": 7,
        "limit": 1000
    },
    "prem_30d": {
        "title": "PREMIUM Plan (1 Month)",
        "stars": 1250,
        "description": "1000 checks/day, priority dedicated proxies, 30 days active",
        "tier": TIER_PREMIUM,
        "days": 30,
        "limit": 1000
    },
    "unl_lifetime": {
        "title": "UNLIMITED Plan (Lifetime)",
        "stars": 2500,
        "description": "Lifetime unrestricted checks, maximum speed & concurrency",
        "tier": TIER_UNLIMITED,
        "days": 3650,
        "limit": 999999999
    }
}

def upgrade_text():
    return (
        f"{e('⭐')} <b>Subscription Plans & Telegram Stars Pricing</b>\n\n"
        f"{e('👑')} <b>VIP PLAN (500 Checks/Day):</b>\n"
        f"   • 1 Day: <b>75 Stars</b>\n"
        f"   • 3 Days: <b>175 Stars</b>\n"
        f"   • 1 Week: <b>350 Stars</b>\n"
        f"   • 1 Month: <b>750 Stars</b>\n\n"
        f"{e('🔥')} <b>PREMIUM PLAN (1000 Checks/Day + Dedicated Proxies):</b>\n"
        f"   • 1 Day: <b>125 Stars</b>\n"
        f"   • 3 Days: <b>290 Stars</b>\n"
        f"   • 1 Week: <b>590 Stars</b>\n"
        f"   • 1 Month: <b>1250 Stars</b>\n\n"
        f"{e('⚡')} <b>UNLIMITED PLAN (Lifetime / Unlimited):</b>\n"
        f"   • Unlimited / Lifetime: <b>2500 Stars</b>\n\n"
        f"<i>Select your preferred plan from the menu below. Automatically activated upon payment!</i>"
    )

def get_upgrade_kb():
    clean_admin = ADMIN_USERNAME.replace("@", "")
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="VIP Plans", callback_data="buy_menu_vip", icon_custom_emoji_id=emoji_id("⭐"), style="primary"),
            InlineKeyboardButton(text="PREMIUM Plans", callback_data="buy_menu_premium", icon_custom_emoji_id=emoji_id("🔥"), style="primary"),
        ],
        [
            InlineKeyboardButton(text="UNLIMITED Lifetime (2500 Stars)", callback_data="buy_stars_unl_lifetime", icon_custom_emoji_id=emoji_id("⚡"), style="success"),
        ],
        [
            InlineKeyboardButton(text="Contact Admin", url=f"https://t.me/{clean_admin}", icon_custom_emoji_id=emoji_id("💬")),
            InlineKeyboardButton(text="Redeem Key", callback_data="redeem_prompt", icon_custom_emoji_id=emoji_id("🔑")),
        ],
        [InlineKeyboardButton(text="Back", callback_data="adm_back_start", icon_custom_emoji_id=emoji_id("▶️"), style="danger")]
    ])

def get_vip_plans_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 Day (75 Stars)", callback_data="buy_stars_vip_1d"),
            InlineKeyboardButton(text="3 Days (175 Stars)", callback_data="buy_stars_vip_3d"),
        ],
        [
            InlineKeyboardButton(text="1 Week (350 Stars)", callback_data="buy_stars_vip_7d"),
            InlineKeyboardButton(text="1 Month (750 Stars)", callback_data="buy_stars_vip_30d"),
        ],
        [InlineKeyboardButton(text="« Back", callback_data="open_upgrade", icon_custom_emoji_id=emoji_id("▶️"), style="danger")]
    ])

def get_premium_plans_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 Day (125 Stars)", callback_data="buy_stars_prem_1d"),
            InlineKeyboardButton(text="3 Days (290 Stars)", callback_data="buy_stars_prem_3d"),
        ],
        [
            InlineKeyboardButton(text="1 Week (590 Stars)", callback_data="buy_stars_prem_7d"),
            InlineKeyboardButton(text="1 Month (1250 Stars)", callback_data="buy_stars_prem_30d"),
        ],
        [InlineKeyboardButton(text="« Back", callback_data="open_upgrade", icon_custom_emoji_id=emoji_id("▶️"), style="danger")]
    ])

def admin_home_kb():
    m_on = is_maintenance_mode()
    m_btn_text = "Disable Maintenance" if m_on else "Enable Maintenance"
    m_icon = emoji_id("🟢") if m_on else emoji_id("🛠️")
    m_cb = "adm_toggle_maint_off" if m_on else "adm_toggle_maint_on"
    m_style = "success" if m_on else "danger"

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Users & Limits", callback_data="adm_cat_users", icon_custom_emoji_id=emoji_id("👤"), style="primary"),
            InlineKeyboardButton(text="Keys & Plans", callback_data="adm_cat_keys", icon_custom_emoji_id=emoji_id("🔑"), style="primary")
        ],
        [
            InlineKeyboardButton(text="Proxy Pool", callback_data="adm_proxies_menu", icon_custom_emoji_id=emoji_id("🌐"), style="primary"),
            InlineKeyboardButton(text="System & Tools", callback_data="adm_cat_system", icon_custom_emoji_id=emoji_id("🛠️"), style="primary")
        ],
        [
            InlineKeyboardButton(text=m_btn_text, callback_data=m_cb, icon_custom_emoji_id=m_icon, style=m_style)
        ],
        [
            InlineKeyboardButton(text="Back to Start", callback_data="adm_back_start", icon_custom_emoji_id=emoji_id("▶️"), style="danger")
        ]
    ])

def admin_users_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Add Credits", callback_data="adm_add_credits", icon_custom_emoji_id=emoji_id("➕"), style="success"),
            InlineKeyboardButton(text="Deduct Credits", callback_data="adm_ded_credits", icon_custom_emoji_id=emoji_id("➖"), style="danger")
        ],
        [
            InlineKeyboardButton(text="Set Tier", callback_data="adm_set_tier", icon_custom_emoji_id=emoji_id("👑"), style="primary"),
            InlineKeyboardButton(text="Revoke Tier", callback_data="adm_revoke_tier", icon_custom_emoji_id=emoji_id("❌"), style="danger")
        ],
        [
            InlineKeyboardButton(text="Ban User", callback_data="adm_ban_user", icon_custom_emoji_id=emoji_id("🚫"), style="danger"),
            InlineKeyboardButton(text="Unban User", callback_data="adm_unban_user", icon_custom_emoji_id=emoji_id("✅"), style="success")
        ],
        [
            InlineKeyboardButton(text="Back", callback_data="admin_home", icon_custom_emoji_id=emoji_id("▶️"), style="danger")
        ]
    ])

def admin_system_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="System Statistics", callback_data="adm_stats", icon_custom_emoji_id=emoji_id("📊"), style="primary"),
            InlineKeyboardButton(text="Gate Maintenance", callback_data="adm_gates_menu", icon_custom_emoji_id=emoji_id("🛠️"), style="primary")
        ],
        [
            InlineKeyboardButton(text="Broadcast Message", callback_data="adm_broadcast", icon_custom_emoji_id=emoji_id("📢"), style="success"),
            InlineKeyboardButton(text="Delete Broadcast", callback_data="adm_del_broadcast_menu", icon_custom_emoji_id=emoji_id("🗑️"), style="danger")
        ],
        [
            InlineKeyboardButton(text="Back", callback_data="admin_home", icon_custom_emoji_id=emoji_id("▶️"), style="danger")
        ]
    ])

def admin_gates_kb():
    gm = load_settings().get("gate_maintenance", {})
    buttons = []
    for g_id, g_info in GATES.items():
        g_name = g_info.get("name", g_id)
        d_name = g_info.get("display_name", f"{g_name} Gate")
        is_off = gm.get(g_name, False)
        status_text = "Disabled" if is_off else "Active"
        btn_text = f"{d_name}: {status_text}"
        cb_data = f"adm_toggle_gate_{g_id}_off" if is_off else f"adm_toggle_gate_{g_id}_on"
        btn_style = "success" if is_off else "danger"
        btn_icon = emoji_id("🟢") if is_off else emoji_id("🛠️")
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data, icon_custom_emoji_id=btn_icon, style=btn_style)])

    buttons.append([InlineKeyboardButton(text="Back", callback_data="adm_cat_system", icon_custom_emoji_id=emoji_id("▶️"), style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

MEMBER_CACHE = {}
MEMBER_CACHE_TTL = 300  # 5 dakika önbellek

async def is_member(bot: Bot, user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    now = time.time()
    cached = MEMBER_CACHE.get(user_id)
    if cached and (now - cached["ts"]) < MEMBER_CACHE_TTL:
        return cached["is_member"]
    try:
        m = await bot.get_chat_member(CHANNEL_ID, user_id)
        is_m = m.status in ("member", "administrator", "creator")
        if is_m:
            MEMBER_CACHE[user_id] = {"is_member": True, "ts": now}
        else:
            MEMBER_CACHE[user_id] = {"is_member": False, "ts": now - (MEMBER_CACHE_TTL - 10)}
        return is_m
    except Exception:
        return False

def require_channel(handler):
    import inspect
    accepted = set(inspect.signature(handler).parameters) - {"event"}

    async def wrapper(event, *args, **kwargs):
        user = getattr(event, "from_user", None)
        bot = event.bot
        if user:
            db = load_db()
            if not is_user_registered(db, user.id) and user.id != ADMIN_ID:
                register_user_in_db(db, user, daily_limit=DAILY_LIMITS[TIER_FREE], tier=TIER_FREE, save_func=save_db)

            if not await is_member(bot, user.id):
                if isinstance(event, Message):
                    await event.answer(join_message(), reply_markup=get_join_kb())
                elif isinstance(event, CallbackQuery):
                    await event.message.answer(join_message(), reply_markup=get_join_kb())
                    await event.answer()
                return

            if user.id != ADMIN_ID and is_maintenance_mode():
                if isinstance(event, Message):
                    await event.answer(maintenance_message())
                elif isinstance(event, CallbackQuery):
                    await event.answer("Bot is under maintenance.", show_alert=True)
                return

            u = get_user(db, user, auto_create=False)
            if u and u.get("banned"):
                if isinstance(event, Message):
                    await event.answer(f"{e('🚫')} <b>Your account has been suspended by administration.</b>")
                elif isinstance(event, CallbackQuery):
                    await event.answer("Your account is banned.", show_alert=True)
                return
        call_kwargs = {k: v for k, v in kwargs.items() if k in accepted}
        return await handler(event, *args, **call_kwargs)
    return wrapper

@router.message(CommandStart())
async def cmd_start(m: Message):
    db = load_db()
    if not is_user_registered(db, m.from_user.id) and m.from_user.id != ADMIN_ID:
        register_user_in_db(db, m.from_user, daily_limit=DAILY_LIMITS[TIER_FREE], tier=TIER_FREE, save_func=save_db)

    if not await is_member(m.bot, m.from_user.id):
        await m.answer(join_message(), reply_markup=get_join_kb())
        return

    if m.from_user.id != ADMIN_ID and is_maintenance_mode():
        await m.answer(maintenance_message())
        return

    u = get_user(db, m.from_user, auto_create=False)
    if u and u.get("banned"):
        await m.answer(f"{e('🚫')} <b>Your account has been suspended by administration.</b>")
        return

    is_adm = (m.from_user.id == ADMIN_ID)
    await m.answer(welcome_text(m.from_user), reply_markup=get_start_kb(is_adm))

@router.message(Command("registar"))
async def cmd_registar(m: Message):
                                         
    if not await is_member(m.bot, m.from_user.id):
        await m.answer(join_message(), reply_markup=get_join_kb())
        return

                                     
    if m.from_user.id != ADMIN_ID and is_maintenance_mode():
        await m.answer(maintenance_message())
        return

    db = load_db()
    if is_user_registered(db, m.from_user.id):
        await m.answer(f"{e('ℹ️')} You are already registered!")
        return

    register_user_in_db(db, m.from_user, daily_limit=DAILY_LIMITS[TIER_FREE], tier=TIER_FREE, save_func=save_db)
    is_adm = (m.from_user.id == ADMIN_ID)
    await m.answer(f"{e('✅')} <b>Registration Successful!</b>\nWelcome to Well Check.", reply_markup=get_start_kb(is_adm))

@router.callback_query(F.data == "btn_do_register")
async def cb_btn_do_register(c: CallbackQuery):
    if not await is_member(c.bot, c.from_user.id):
        await c.answer("Please join the channel first!", show_alert=True)
        return

    if c.from_user.id != ADMIN_ID and is_maintenance_mode():
        await c.answer("Bot is currently under maintenance.", show_alert=True)
        return

    db = load_db()
    if is_user_registered(db, c.from_user.id):
        await c.answer("You are already registered!", show_alert=True)
        return

    register_user_in_db(db, c.from_user, daily_limit=DAILY_LIMITS[TIER_FREE], tier=TIER_FREE, save_func=save_db)
    is_adm = (c.from_user.id == ADMIN_ID)
    await c.message.delete()
    await c.message.answer(f"{e('✅')} <b>Registration Successful!</b>\nWelcome to Well Check.", reply_markup=get_start_kb(is_adm))
    await c.answer()

@router.callback_query(F.data == "check_join")
async def cb_check_join(c: CallbackQuery):
    if not await is_member(c.bot, c.from_user.id):
        await c.answer("You have not joined the channel yet!", show_alert=True)
        return

    if c.from_user.id != ADMIN_ID and is_maintenance_mode():
        await c.answer("Bot is currently under maintenance.", show_alert=True)
        return

    db = load_db()
    if not is_user_registered(db, c.from_user.id):
        await c.message.delete()
        await send_registration_screen(c, c.from_user, e_func=e, emoji_id_func=emoji_id)
        return

    u = get_user(db, c.from_user, auto_create=False)
    if u and u.get("banned"):
        await c.answer("Your account is suspended.", show_alert=True)
        return

    is_adm = (c.from_user.id == ADMIN_ID)
    await c.message.edit_text(welcome_text(c.from_user), reply_markup=get_start_kb(is_adm))

@router.callback_query(F.data == "adm_back_start")
async def cb_adm_back_start(c: CallbackQuery):
    is_adm = (c.from_user.id == ADMIN_ID)
    await c.message.edit_text(welcome_text(c.from_user), reply_markup=get_start_kb(is_adm))
    await c.answer()

def get_user_gates_kb():
    buttons = []
    gm = load_settings().get("gate_maintenance", {})
    for g_id, g_info in GATES.items():
        g_name = g_info.get("name", g_id)
        d_name = g_info.get("display_name", f"{g_name} Gate")
        cmd = g_info.get("command", "")
        is_off = gm.get(g_name, False)
        status_text = " [Maint]" if is_off else ""
        btn_text = f"{d_name}{status_text}"
        btn_icon = emoji_id("🛠️") if is_off else emoji_id("💳")
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"sel_gate_{g_id}", icon_custom_emoji_id=btn_icon, style="primary")])
    buttons.append([InlineKeyboardButton(text="Back", callback_data="adm_back_start", icon_custom_emoji_id=emoji_id("▶️"), style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.callback_query(F.data == "open_gates_menu")
async def cb_open_gates_menu(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID and is_maintenance_mode():
        await c.answer("Bot is under maintenance.", show_alert=True)
        return
    text = (
        f"{e('💳')} <b>Available Gates:</b>\n\n"
        f"Select a gate below to check your card:"
    )
    await c.message.edit_text(text, reply_markup=get_user_gates_kb())
    await c.answer()

@router.callback_query(F.data.startswith("sel_gate_"))
async def cb_sel_gate(c: CallbackQuery, state: FSMContext):
    if c.from_user.id != ADMIN_ID and is_maintenance_mode():
        await c.answer("Bot is under maintenance.", show_alert=True)
        return
    g_id = c.data.replace("sel_gate_", "")
    gate_info = GATES.get(g_id)
    if not gate_info:
        await c.answer("Gate not found!", show_alert=True)
        return

    g_name = gate_info.get("name", g_id)
    cmd = gate_info.get("command", "")
    if c.from_user.id != ADMIN_ID and is_gate_maintenance(g_name):
        await c.answer(f"{g_name} is currently under maintenance!", show_alert=True)
        return

    await state.set_state(GateCheckState.waiting_card)
    await state.update_data(selected_gate_id=g_id)

    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Cancel", callback_data="cancel_gate_input", icon_custom_emoji_id=emoji_id("❌"), style="danger")]
    ])

    await c.message.edit_text(
        f"{e('💳')} <b>{gate_info.get('display_name')}</b> selected!\n\n"
        f"Please send your card details in the following format:\n"
        f"<code>cardno|month|year|cvv</code>",
        reply_markup=cancel_kb
    )
    await c.answer()

@router.callback_query(F.data == "cancel_gate_input")
async def cb_cancel_gate_input(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text(welcome_text(c.from_user), reply_markup=get_start_kb(c.from_user.id == ADMIN_ID))
    await c.answer("Cancelled.")

@router.message(GateCheckState.waiting_card)
async def process_gate_card_input(m: Message, state: FSMContext):
                                                                          
    if m.text and m.text.startswith("/"):
        await state.clear()
        return

    data = await state.get_data()
    g_id = data.get("selected_gate_id")
    gate_info = GATES.get(g_id)

    if not gate_info:
        await state.clear()
        await m.answer(f"{e('⚠️')} Unknown gate selected.")
        return

                                                                                         
    await handle_single_gate_check(m, gate_info, raw_card_text=m.text)

def get_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Back", callback_data="adm_back_start", icon_custom_emoji_id=emoji_id("▶️"), style="danger")]
    ])

@router.callback_query(F.data == "howto_bin")
async def cb_howto_bin(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID and is_maintenance_mode():
        await c.answer("Bot is under maintenance.", show_alert=True)
        return
    text = (
        f"{e('💡')} <b>BIN Lookup:</b>\n\n"
        f"Send: <code>/bin &lt;6 to 12 digits&gt;</code>\n\n"
        f"Example:\n<code>/bin 454315</code>"
    )
    await c.message.edit_text(text, reply_markup=get_back_kb())
    await c.answer()

@router.message(Command("bin"))
@require_channel
async def cmd_bin(m: Message):
    parts = m.text.split(maxsplit=1)
    if len(parts) < 2:
        await m.answer(f"{e('⚠️')} Usage: <code>/bin &lt;6-12 digits&gt;</code>\nExample: <code>/bin 454315</code>")
        return

    bin_raw = parts[1].strip()
    status = await m.answer(f"{e('🔍')} Looking up BIN <code>{bin_raw}</code>...")

    info = await asyncio.get_event_loop().run_in_executor(None, query_bin, bin_raw)

    if not info.get("success"):
        await status.edit_text(f"{e('❌')} <b>Lookup Failed:</b> {info.get('error', 'Unknown error')}")
        return

    msg = (
        f"{e('💳')} <b>BIN Lookup Result</b>\n\n"
        f"▫️ <b>BIN:</b> <code>{info['bin']}</code>\n"
        f"▫️ <b>Brand / Scheme:</b> <b>{info['scheme']}</b>\n"
        f"▫️ <b>Type:</b> <b>{info['type']}</b>\n"
        f"▫️ <b>Tier / Level:</b> <b>{info['brand']}</b>\n"
        f"▫️ <b>Issuer / Bank:</b> <b>{info['bank']}</b>\n"
        f"▫️ <b>Country:</b> {info['flag']} <b>{info['country']}</b> ({info['country_code']})\n"
        f"▫️ <b>Source:</b> <code>{info['source']}</code>"
    )
    await status.edit_text(msg)

@router.message(Command("profile"))
@require_channel
async def cmd_profile(m: Message):
    db = load_db()
    u = get_user(db, m.from_user)
    await m.answer(profile_text(m.from_user, u))

@router.callback_query(F.data == "open_profile")
async def cb_open_profile(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID and is_maintenance_mode():
        await c.answer("Bot is under maintenance.", show_alert=True)
        return
    db = load_db()
    u = get_user(db, c.from_user)
    await c.message.edit_text(profile_text(c.from_user, u), reply_markup=get_back_kb())
    await c.answer()

@router.message(Command("buy"))
@require_channel
async def cmd_buy(m: Message):
    await m.answer(upgrade_text(), reply_markup=get_upgrade_kb())

@router.callback_query(F.data == "open_upgrade")
async def cb_open_upgrade(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID and is_maintenance_mode():
        await c.answer("Bot is under maintenance.", show_alert=True)
        return
    await c.message.edit_text(upgrade_text(), reply_markup=get_upgrade_kb())
    await c.answer()

@router.callback_query(F.data == "buy_menu_vip")
async def cb_buy_menu_vip(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID and is_maintenance_mode():
        await c.answer("Bot is under maintenance.", show_alert=True)
        return
    text = (
        f"{e('👑')} <b>VIP Plan Purchase</b>\n\n"
        f"• Daily <b>500</b> checks limit (resets every 24h)\n"
        f"• High-speed stable proxy pool\n\n"
        f"Please select duration:"
    )
    await c.message.edit_text(text, reply_markup=get_vip_plans_kb())
    await c.answer()

@router.callback_query(F.data == "buy_menu_premium")
async def cb_buy_menu_premium(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID and is_maintenance_mode():
        await c.answer("Bot is under maintenance.", show_alert=True)
        return
    text = (
        f"{e('🔥')} <b>PREMIUM Plan Purchase</b>\n\n"
        f"• Daily <b>1000</b> checks limit (resets every 24h)\n"
        f"• Priority fast servers & dedicated proxy pool\n\n"
        f"Please select duration:"
    )
    await c.message.edit_text(text, reply_markup=get_premium_plans_kb())
    await c.answer()

@router.callback_query(F.data.startswith("buy_stars_"))
async def cb_buy_stars(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID and is_maintenance_mode():
        await c.answer("Bot is under maintenance.", show_alert=True)
        return

    plan_key = c.data.replace("buy_stars_", "")
    plan = STAR_PLANS.get(plan_key)
    if not plan:
        await c.answer("Invalid package selected.", show_alert=True)
        return

    prices = [LabeledPrice(label=plan["title"], amount=plan["stars"])]
    
    await c.message.answer_invoice(
        title=plan["title"],
        description=plan["description"],
        payload=f"plan_{plan_key}_{c.from_user.id}_{int(time.time())}",
        currency="XTR",
        prices=prices,
        provider_token=""
    )
    await c.answer()

@router.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@router.message(F.successful_payment)
async def process_successful_payment(m: Message):
    sp = m.successful_payment
    payload = sp.invoice_payload
                                                    
    plan_key = None
    if payload.startswith("plan_"):
        parts = payload.split("_")
        if len(parts) >= 2:
            plan_key = parts[1]

    plan = STAR_PLANS.get(plan_key)
    if not plan:
                             
        plan = STAR_PLANS.get("vip")

    tier_name = plan["tier"]
    daily_lim = plan["limit"]
    expire_days = plan["days"]

    db = load_db()
    u = get_user(db, m.from_user)
    u["tier"] = tier_name
    u["total"] = daily_lim
    u["used"] = 0
    u["tier_expiry"] = time.time() + (expire_days * 86400)
    save_db(db)

                            
    try:
        await m.bot.send_message(
            ADMIN_ID,
            f"{e('⭐️')} <b>New Stars Purchase!</b>\n"
            f"👤 <b>User:</b> @{m.from_user.username or 'none'} (<code>{m.from_user.id}</code>)\n"
            f"📦 <b>Package:</b> {plan['title']}\n"
            f"⭐️ <b>Paid Stars:</b> {sp.total_amount} XTR\n"
            f"🆔 <b>Telegram Payment Charge ID:</b> <code>{sp.telegram_payment_charge_id}</code>"
        )
    except Exception:
        pass

    success_msg = (
        f"{e('🎉')} <b>Payment Successful!</b> {e('✨')}\n\n"
        f"{e('👑')} <b>Package:</b> <b>{tier_name.upper()}</b> successfully activated on your account!\n"
        f"{e('⚡')} <b>Daily Limit:</b> <b>{DAILY_LIMITS.get(tier_name, 'Unlimited')}</b> checks\n"
        f"{e('⭐️')} <b>Amount Paid:</b> <b>{sp.total_amount} Stars</b>\n\n"
        f"Enjoy your upgraded access!"
    )
    await m.answer(success_msg, reply_markup=get_start_kb(m.from_user.id == ADMIN_ID))

@router.message(F.refunded_payment)
async def process_refunded_payment(m: Message):
    rf = m.refunded_payment
    db = load_db()
    u = get_user(db, m.from_user)
    
                                                
    u["tier"] = TIER_FREE
    u["total"] = DAILY_LIMITS[TIER_FREE]
    u["tier_expiry"] = None
    u["used"] = u.get("total", 200)                 
    
                                        
    ban_duration = 86400
    u["banned"] = True
    u["banned_until"] = time.time() + ban_duration
    save_db(db)

                               
    ban_end_str = datetime.fromtimestamp(u["banned_until"], timezone.utc).strftime("%d.%m.%Y %H:%M") + " UTC"
    await m.answer(
        f"{e('⚠️')} <b>Stars Refund Detected!</b>\n\n"
        f"Since the payment was refunded, your membership has been revoked and your account has been <b>temporarily banned for 1 day</b>.\n"
        f"▫️ <b>Ban Expires:</b> <code>{ban_end_str}</code>\n"
        f"▫️ <b>Refunded Amount:</b> <code>{rf.total_amount} XTR</code>\n\n"
        f"If you believe this is a mistake, contact the administrator: <b>{ADMIN_USERNAME}</b>"
    )

                             
    try:
        await m.bot.send_message(
            ADMIN_ID,
            f"{e('🚨')} <b>PAYMENT REFUND / FRAUD ALERT!</b>\n"
            f"👤 <b>User:</b> @{m.from_user.username or 'none'} (<code>{m.from_user.id}</code>)\n"
            f"⭐️ <b>Refunded Stars:</b> {rf.total_amount} XTR\n"
            f"🆔 <b>Charge ID:</b> <code>{rf.telegram_payment_charge_id}</code>\n"
            f"🚫 <b>Action:</b> Membership revoked and user banned for 1 day!"
        )
    except Exception:
        pass

@router.message(Command("redeem"))
@require_channel
async def cmd_redeem(m: Message):
    parts = m.text.split(maxsplit=1)
    if len(parts) < 2:
        await m.answer(f"{e('⚠️')} Usage: <code>/redeem KEY</code>")
        return

    key_input = parts[1].strip()
    keys = load_keys()
    if key_input not in keys:
        await m.answer(f"{e('❌')} Invalid or expired key.")
        return

    kdata = keys.pop(key_input)
    save_keys(keys)

    db = load_db()
    u = get_user(db, m.from_user)
    k_type = kdata.get("type")
    k_val = kdata.get("value")

    if k_type == "tier":
        u["tier"] = k_val
        u["total"] = DAILY_LIMITS[k_val]
        u["used"] = 0
        save_db(db)
        await m.answer(
            f"{e('🎉')} <b>Success!</b> Your subscription has been upgraded to <b>{k_val.upper()}</b>!"
        )
    elif k_type == "credits":
        u["total"] += int(k_val)
        save_db(db)
        await m.answer(
            f"{e('🎉')} <b>Success!</b> Added <b>{k_val}</b> check credits to your account!"
        )

@router.callback_query(F.data == "redeem_prompt")
async def cb_redeem_prompt(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID and is_maintenance_mode():
        await c.answer("Bot is under maintenance.", show_alert=True)
        return
    await c.message.answer(f"{e('💡')} To redeem a key, send: <code>/redeem YOUR_KEY</code>")
    await c.answer()

@router.message(Command("admin"))
async def cmd_admin(m: Message):
    if m.from_user.id != ADMIN_ID:
        return
    await m.answer(f"{e('👑')} <b>Admin Control Panel</b>", reply_markup=admin_home_kb())

@router.callback_query(F.data == "admin_home")
async def cb_admin_home(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        await c.answer("Access denied", show_alert=True)
        return
    await c.message.edit_text(f"{e('👑')} <b>Admin Control Panel</b>\n\nSelect a management category below:", reply_markup=admin_home_kb())
    await c.answer()

@router.callback_query(F.data == "adm_cat_users")
async def cb_adm_cat_users(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    msg = f"{e('👤')} <b>User & Balance Management</b>\n\nGrant credits, change tiers, or manage bans:"
    await c.message.edit_text(msg, reply_markup=admin_users_kb())
    await c.answer()

@router.callback_query(F.data == "adm_cat_keys")
async def cb_adm_cat_keys(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    keys = load_keys()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Gen VIP Key", callback_data="adm_gen_vip", icon_custom_emoji_id=emoji_id("➕"), style="primary"),
         InlineKeyboardButton(text="Gen Premium Key", callback_data="adm_gen_prem", icon_custom_emoji_id=emoji_id("➕"), style="primary")],
        [InlineKeyboardButton(text="Gen Unlimited Key", callback_data="adm_gen_unlim", icon_custom_emoji_id=emoji_id("➕"), style="primary"),
         InlineKeyboardButton(text="Gen 100 Credits Key", callback_data="adm_gen_cred", icon_custom_emoji_id=emoji_id("➕"), style="primary")],
        [InlineKeyboardButton(text="Back", callback_data="admin_home", icon_custom_emoji_id=emoji_id("▶️"), style="danger")]
    ])
    msg = f"{e('🔑')} <b>Keys & Subscriptions</b>\n\n<b>Active Keys:</b> <code>{len(keys)}</code>\n\nGenerate a new redeemable key:"
    await c.message.edit_text(msg, reply_markup=kb)
    await c.answer()

@router.callback_query(F.data == "adm_cat_system")
async def cb_adm_cat_system(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    msg = f"{e('🛠️')} <b>System & Broadcast Tools</b>\n\nView platform metrics, send broadcasts, or revoke messages:"
    await c.message.edit_text(msg, reply_markup=admin_system_kb())
    await c.answer()

@router.callback_query(F.data == "adm_del_broadcast_menu")
async def cb_adm_del_broadcast_menu(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    bcasts = load_broadcasts()
    if not bcasts:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data="adm_cat_system", icon_custom_emoji_id=emoji_id("▶️"), style="danger")]])
        await c.message.edit_text(f"{e('🗑️')} <b>Delete Broadcast</b>\n\nNo broadcast history found in records.", reply_markup=kb)
        await c.answer()
        return

    buttons = []
    for bid, bdata in list(bcasts.items())[-6:]:
        label = f"{bid} ({bdata.get('success', 0)} users)"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"delbc_{bid}", style="danger")])
    buttons.append([InlineKeyboardButton(text="Back", callback_data="adm_cat_system", icon_custom_emoji_id=emoji_id("▶️"), style="danger")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await c.message.edit_text(f"{e('🗑️')} <b>Delete Broadcast</b>\n\nSelect a broadcast to revoke and delete from all users:", reply_markup=kb)
    await c.answer()

@router.callback_query(F.data.startswith("delbc_"))
async def cb_delete_broadcast_action(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    bid = c.data.replace("delbc_", "")
    status_msg = await c.message.edit_text(f"{e('⏳')} <b>Revoking broadcast {bid}...</b>\nRunning 25 parallel worker tasks...")

    stats = await delete_announcement(c.bot, bid, concurrency=25)

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data="adm_cat_system", icon_custom_emoji_id=emoji_id("▶️"), style="danger")]])

    if not stats.get("success"):
        await status_msg.edit_text(f"{e('❌')} <b>Delete Failed:</b> {stats.get('error', 'Unknown error')}", reply_markup=kb)
        return

    result_text = (
        f"{e('✅')} <b>Broadcast Revoked & Deleted!</b>\n\n"
        f"▫️ <b>Broadcast ID:</b> <code>{bid}</code>\n"
        f"▫️ <b>Target Messages:</b> <code>{stats.get('total', 0)}</code>\n"
        f"▫️ <b>Successfully Deleted:</b> <code>{stats.get('deleted', 0)}</code>\n"
        f"▫️ <b>Failed / Already Deleted:</b> <code>{stats.get('failed', 0)}</code>\n"
        f"▫️ <b>Execution Time:</b> <code>{stats.get('duration', 0)}s</code> (25 parallel workers)"
    )
    await status_msg.edit_text(result_text, reply_markup=kb)
    await c.answer()

@router.callback_query(F.data == "adm_gates_menu")
async def cb_adm_gates_menu(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    msg = f"{e('🛠️')} <b>Gate Maintenance Control</b>\n\nToggle individual gate maintenance status on or off:"
    await c.message.edit_text(msg, reply_markup=admin_gates_kb())
    await c.answer()

@router.callback_query(F.data.startswith("adm_toggle_gate_"))
async def cb_adm_toggle_gate_dynamic(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
                                                
    parts = c.data.split("_")
    action = parts[-1]                   
    g_id = "_".join(parts[3:-1])           

    gate_info = GATES.get(g_id)
    if not gate_info:
        await c.answer("Unknown gate!", show_alert=True)
        return

    gate_name = gate_info.get("name", g_id)
    turn_on = (action == "on")
    set_gate_maintenance(gate_name, turn_on)
    state_str = "Maintenance Enabled (Gate Closed)" if turn_on else "Maintenance Disabled (Gate Active)"
    await c.answer(f"{gate_name} Gate {state_str}!", show_alert=True)
    msg = f"{e('🛠️')} <b>Gate Maintenance Control</b>\n\nToggle individual gate maintenance status on or off:"
    await c.message.edit_text(msg, reply_markup=admin_gates_kb())

@router.callback_query(F.data.in_({"adm_toggle_maint_on", "adm_toggle_maint_off"}))
async def cb_adm_toggle_maint(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    s = load_settings()
    turn_on = (c.data == "adm_toggle_maint_on")
    s["maintenance"] = turn_on
    save_settings(s)
    state_str = "ENABLED (Users cannot use the bot)" if turn_on else "DISABLED (Bot is open to all users)"
    await c.answer(f"Maintenance mode {state_str}!", show_alert=True)
    await c.message.edit_text(f"{e('👑')} <b>Admin Control Panel</b>\n\nSelect a management category below:", reply_markup=admin_home_kb())

@router.callback_query(F.data == "adm_stats")
async def cb_adm_stats(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    db = load_db()
    total_users = len(db)
    banned_count = sum(1 for u in db.values() if u.get("banned"))
    vips = sum(1 for u in db.values() if u.get("tier") == TIER_VIP)
    prems = sum(1 for u in db.values() if u.get("tier") == TIER_PREMIUM)
    unlims = sum(1 for u in db.values() if u.get("tier") == TIER_UNLIMITED)
    tot_checks = sum(u.get("total_checks", 0) for u in db.values())
    tot_hits = get_current_global_hit_count()
    m_status = f"{e('🛠️')} Active" if is_maintenance_mode() else f"{e('🟢')} Normal"

    msg = (
        f"{e('📊')} <b>System Statistics</b>\n\n"
        f"<b>Maintenance Mode:</b> <b>{m_status}</b>\n"
        f"<b>Total Users:</b> <code>{total_users}</code>\n"
        f"<b>VIP Members:</b> <code>{vips}</code>\n"
        f"<b>Premium Members:</b> <code>{prems}</code>\n"
        f"<b>Unlimited Members:</b> <code>{unlims}</code>\n"
        f"<b>Banned Users:</b> <code>{banned_count}</code>\n"
        f"<b>Total Checks:</b> <code>{tot_checks}</code>\n"
        f"<b>Total Hits:</b> <code>{tot_hits}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data="adm_cat_system", icon_custom_emoji_id=emoji_id("▶️"), style="danger")]])
    await c.message.edit_text(msg, reply_markup=kb)
    await c.answer()

@router.callback_query(F.data == "adm_proxies_menu")
async def cb_adm_proxies_menu(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    proxies = load_proxy_list()
    msg = (
        f"{e('🌐')} <b>Proxy Pool Management</b>\n\n"
        f"<b>Active Proxies:</b> <code>{len(proxies)}</code>\n"
        f"<b>Storage:</b> <code>data/proxies.txt</code>\n\n"
        f"Choose an action below:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="List Proxies", callback_data="adm_list_proxies", icon_custom_emoji_id=emoji_id("📋"), style="primary")],
        [InlineKeyboardButton(text="Add & Test Proxy", callback_data="adm_add_proxy", icon_custom_emoji_id=emoji_id("➕"), style="success")],
        [InlineKeyboardButton(text="Delete Proxy", callback_data="adm_del_proxy", icon_custom_emoji_id=emoji_id("🗑️"), style="danger")],
        [InlineKeyboardButton(text="Back", callback_data="admin_home", icon_custom_emoji_id=emoji_id("▶️"), style="danger")]
    ])
    await c.message.edit_text(msg, reply_markup=kb)
    await c.answer()

@router.callback_query(F.data == "adm_list_proxies")
async def cb_adm_list_proxies(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    proxies = load_proxy_list()
    if not proxies:
        msg = f"{e('🌐')} <b>Proxy Pool</b>\n\nNo proxies found in <code>data/proxies.txt</code>."
    else:
        censored = []
        for i, p in enumerate(proxies, 1):
            censored.append(f"<b>{i}.</b> <code>{censor_text(p)}</code>")
        msg = f"{e('🌐')} <b>Active Proxies ({len(proxies)}):</b>\n\n" + "\n".join(censored)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data="adm_proxies_menu", icon_custom_emoji_id=emoji_id("▶️"), style="danger")]])
    await c.message.edit_text(msg, reply_markup=kb)
    await c.answer()

@router.callback_query(F.data.startswith("adm_gen_"))
async def cb_adm_gen_key(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return
    action = c.data.replace("adm_gen_", "")
    keys = load_keys()
    new_key = f"KEY-{uuid.uuid4().hex[:12].upper()}"

    if action == "vip":
        keys[new_key] = {"type": "tier", "value": TIER_VIP, "created": time.time()}
    elif action == "prem":
        keys[new_key] = {"type": "tier", "value": TIER_PREMIUM, "created": time.time()}
    elif action == "unlim":
        keys[new_key] = {"type": "tier", "value": TIER_UNLIMITED, "created": time.time()}
    elif action == "cred":
        keys[new_key] = {"type": "credits", "value": 100, "created": time.time()}

    save_keys(keys)
    msg = (
        f"{e('✅')} <b>Key Generated Successfully!</b>\n\n"
        f"<b>Key:</b> <code>{new_key}</code>\n"
        f"<b>Type:</b> <code>{action.upper()}</code>\n\n"
        f"User can claim it via: <code>/redeem {new_key}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data="adm_cat_keys", icon_custom_emoji_id=emoji_id("▶️"), style="danger")]])
    await c.message.edit_text(msg, reply_markup=kb)
    await c.answer()

@router.callback_query(F.data.in_({
    "adm_add_credits", "adm_ded_credits", "adm_set_tier", "adm_revoke_tier",
    "adm_ban_user", "adm_unban_user", "adm_broadcast", "adm_add_proxy", "adm_del_proxy"
}))
async def cb_admin_actions(c: CallbackQuery, state: FSMContext):
    if c.from_user.id != ADMIN_ID:
        return
    act = c.data
    await state.update_data(admin_action=act)
    await state.set_state(AdminActionState.waiting_input)

    prompts = {
        "adm_add_credits": "Send target <b>User ID</b> and <b>Amount</b>:\nExample: <code>123456789 100</code>",
        "adm_ded_credits": "Send target <b>User ID</b> and <b>Amount</b> to deduct:\nExample: <code>123456789 50</code>",
        "adm_set_tier": "Send target <b>User ID</b> and <b>Tier</b> (vip / premium / unlimited):\nExample: <code>123456789 vip</code>",
        "adm_revoke_tier": "Send target <b>User ID</b> to reset to Free tier:\nExample: <code>123456789</code>",
        "adm_ban_user": "Send target <b>User ID</b> to ban:\nExample: <code>123456789</code>",
        "adm_unban_user": "Send target <b>User ID</b> to unban:\nExample: <code>123456789</code>",
        "adm_broadcast": "Send the broadcast message text to send to all users (Processed with 25 parallel workers):",
        "adm_add_proxy": "Send the proxy string to test and add:\nSupported: <code>ip:port:user:pass</code>, <code>user:pass:ip:port</code>, or <code>http://...</code>",
        "adm_del_proxy": "Send the exact proxy or index number to delete:\nExample: <code>1</code> or <code>http://user:pass@ip:port</code>"
    }

    if act in ("adm_add_credits", "adm_ded_credits", "adm_set_tier", "adm_revoke_tier", "adm_ban_user", "adm_unban_user"):
        cancel_target = "adm_cat_users"
    elif act == "adm_broadcast":
        cancel_target = "adm_cat_system"
    else:
        cancel_target = "adm_proxies_menu"

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Cancel", callback_data=cancel_target, icon_custom_emoji_id=emoji_id("❌"), style="danger")]])
    await c.message.edit_text(f"{e('📝')} {prompts[act]}", reply_markup=kb)
    await c.answer()

@router.callback_query(AdminActionState.waiting_input, F.data == "adm_cancel_action")
async def cb_adm_cancel_action(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text(f"{e('👑')} <b>Admin Control Panel</b>\n\nSelect a management category below:", reply_markup=admin_home_kb())
    await c.answer()

@router.message(AdminActionState.waiting_input)
async def process_admin_input(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    act = data.get("admin_action")
    await state.clear()
    text = m.text.strip()
    db = load_db()

    kb_users = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data="adm_cat_users", icon_custom_emoji_id=emoji_id("▶️"), style="danger")]])
    kb_system = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data="adm_cat_system", icon_custom_emoji_id=emoji_id("▶️"), style="danger")]])
    kb_proxies = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data="adm_proxies_menu", icon_custom_emoji_id=emoji_id("▶️"), style="danger")]])

    if act == "adm_add_proxy":
        status_msg = await m.answer(f"{e('🔍')} Testing proxy connection and latency...")
        is_ok, dur, ip_val, full_proxy = await asyncio.get_event_loop().run_in_executor(None, check_proxy_health, text)
        if is_ok:
            plist = load_proxy_list()
            if full_proxy not in plist:
                plist.append(full_proxy)
                save_proxy_list(plist)
            await status_msg.edit_text(
                f"{e('✅')} <b>Proxy Working & Added!</b>\n\n"
                f"▫️ <b>Public IP:</b> <code>{ip_val}</code>\n"
                f"▫️ <b>Latency:</b> <code>{dur}s</code>\n"
                f"▫️ <b>Status:</b> <b>Active</b>\n"
                f"▫️ <b>Total Proxies:</b> <code>{len(plist)}</code>",
                reply_markup=kb_proxies
            )
        else:
            await status_msg.edit_text(
                f"{e('❌')} <b>Proxy Test Failed!</b>\n\n"
                f"▫️ <b>Reason:</b> <code>{censor_text(str(ip_val))}</code>\n"
                f"▫️ <b>Latency:</b> <code>{dur}s</code>\n\n"
                f"<i>Proxy was not added because it is inactive or unreachable.</i>",
                reply_markup=kb_proxies
            )
        return

    if act == "adm_del_proxy":
        plist = load_proxy_list()
        removed = None
        if text.isdigit():
            idx = int(text) - 1
            if 0 <= idx < len(plist):
                removed = plist.pop(idx)
        else:
            normalized_query = normalize_proxy_string(text)
            for p in plist:
                if text in p or normalized_query in p:
                    removed = p
                    plist.remove(p)
                    break

        if removed:
            save_proxy_list(plist)
            await m.answer(
                f"{e('✅')} <b>Proxy Deleted Successfully!</b>\n\n"
                f"<b>Removed:</b> <code>{censor_text(removed)}</code>\n"
                f"<b>Remaining:</b> <code>{len(plist)}</code>",
                reply_markup=kb_proxies
            )
        else:
            await m.answer(f"{e('⚠️')} Proxy not found in list.", reply_markup=kb_proxies)
        return

    if act == "adm_broadcast":
        uids = list(db.keys())
        status_msg = await m.answer(f"{e('⏳')} <b>Broadcasting to {len(uids)} users...</b>\nRunning 25 parallel worker tasks...")
        formatted_text = f"{e('📢')} <b>Announcement:</b>\n\n{text}"
        stats = await broadcast_announcement(m.bot, uids, formatted_text, concurrency=25)

        res_msg = (
            f"{e('✅')} <b>Broadcast Completed!</b>\n\n"
            f"▫️ <b>Broadcast ID:</b> <code>{stats.get('broadcast_id')}</code>\n"
            f"▫️ <b>Total Targets:</b> <code>{stats.get('total', 0)}</code>\n"
            f"▫️ <b>Delivered:</b> <code>{stats.get('success', 0)}</code>\n"
            f"▫️ <b>Failed:</b> <code>{stats.get('failed', 0)}</code>\n"
            f"▫️ <b>Newly Blocked (mal.json):</b> <code>{stats.get('blocked', 0)}</code>\n"
            f"▫️ <b>Skipped (Already Blocked):</b> <code>{stats.get('skipped_mal', 0)}</code>\n"
            f"▫️ <b>Execution Time:</b> <code>{stats.get('duration', 0)}s</code> (25 parallel workers)\n\n"
            f"<i>You can revoke/delete this broadcast anytime from System & Tools.</i>"
        )
        await status_msg.edit_text(res_msg, reply_markup=kb_system)
        return

    parts = text.split()
    if not parts:
        await m.answer(f"{e('⚠️')} Invalid input.", reply_markup=kb_users)
        return

    raw_query = parts[0]
    target_uid, u = find_user_by_query(db, raw_query)

    if not u:
                                                       
        if raw_query.isdigit():
            target_uid = raw_query
            db[target_uid] = {
                "username": "", "first_name": "User", "tier": TIER_FREE,
                "banned": False, "used": 0, "total": DAILY_LIMITS[TIER_FREE],
                "last_reset": get_today_str(), "total_checks": 0, "successful_checks": 0
            }
            u = db[target_uid]
        else:
            await m.answer(f"{e('⚠️')} User <b>{html.escape(raw_query)}</b> not found in database.", reply_markup=kb_users)
            return

    target_display = f"@{u['username']}" if u.get("username") else f"<code>{target_uid}</code>"

    if act == "adm_add_credits":
        val = int(parts[1]) if len(parts) > 1 else 0
        u["total"] += val
        save_db(db)
        await m.answer(f"{e('✅')} Added <b>{val}</b> credits to user {target_display}.", reply_markup=kb_users)
    elif act == "adm_ded_credits":
        val = int(parts[1]) if len(parts) > 1 else 0
        u["total"] = max(0, u["total"] - val)
        save_db(db)
        await m.answer(f"{e('✅')} Deducted <b>{val}</b> credits from user {target_display}.", reply_markup=kb_users)
    elif act == "adm_set_tier":
        tier = parts[1].lower() if len(parts) > 1 else TIER_VIP
        if tier in DAILY_LIMITS:
            u["tier"] = tier
            u["total"] = DAILY_LIMITS[tier]
            u["used"] = 0
            save_db(db)
            await m.answer(f"{e('✅')} User {target_display} tier set to <b>{tier.upper()}</b>.", reply_markup=kb_users)
        else:
            await m.answer(f"{e('⚠️')} Unknown tier. Choose: free, vip, premium, unlimited.", reply_markup=kb_users)
    elif act == "adm_revoke_tier":
        u["tier"] = TIER_FREE
        u["total"] = DAILY_LIMITS[TIER_FREE]
        u["used"] = 0
        save_db(db)
        await m.answer(f"{e('✅')} User {target_display} tier reset to <b>FREE</b>.", reply_markup=kb_users)
    elif act == "adm_ban_user":
        u["banned"] = True
        save_db(db)
        await m.answer(f"{e('🚫')} User {target_display} has been banned.", reply_markup=kb_users)
    elif act == "adm_unban_user":
        u["banned"] = False
        save_db(db)
        await m.answer(f"{e('✅')} User {target_display} has been unbanned.", reply_markup=kb_users)

@router.message(Command("mapu"))
@require_channel
async def cmd_mapu(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID and is_gate_maintenance("Point"):
        await m.answer(f"{e('🛠️')} <b>Point Gate is currently under maintenance.</b>\nPlease try again later.")
        return
    db = load_db()
    u = get_user(db, m.from_user)
    text = m.text.split(maxsplit=1)[1] if len(m.text.split(maxsplit=1)) > 1 else ""
    if not text:
        await m.answer(f"{e('⚠️')} Send cards with the command.\nExample: <code>/mapu 4111111111111111|12|25|123 5500005555555559|01|26|456</code>")
        return

    parsed = parse_cards(text)
    valid = [c for c in parsed if c is not None]
    if not valid:
        await m.answer(f"{e('⚠️')} No valid cards found.")
        return
    if remaining(u) < len(valid):
        await m.answer(
            f"{e('🚫')} Not enough checks left!\n"
            f"{e('💳')} Cards sent: <b>{len(valid)}</b>\n"
            f"{e('⏳')} Remaining: <b>{remaining_str(u)}</b>\n\n"
            f"To get more checks send <code>/buy</code>"
        )
        return

    await state.update_data(cards=valid)
    await state.set_state(MapuState.confirm)
    listing = "\n".join(f"▫️ <code>{c[0]}|{c[1]}|{c[2]}|{c[3]}</code>" for c in valid[:10])
    more_txt = f"\n<i>...and {len(valid) - 10} more</i>" if len(valid) > 10 else ""
    await m.answer(
        f"{e('📋')} <b>{len(valid)} cards ready to check</b>\n\n{listing}{more_txt}\n\n"
        f"{e('⏳')} Required checks: <b>{len(valid)}</b>\n\n"
        f"{e('▶️')} Press <b>Start</b> to begin processing.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Start", callback_data="mapu_go", icon_custom_emoji_id=emoji_id("✅"), style="success"),
                InlineKeyboardButton(text="Cancel", callback_data="mapu_cancel", icon_custom_emoji_id=emoji_id("❌"), style="danger"),
            ]
        ]),
    )

@router.callback_query(MapuState.confirm, F.data == "mapu_cancel")
async def cb_mapu_cancel(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text(f"{e('❌')} <b>Cancelled.</b> No checks were consumed.")
    await c.answer()

@router.callback_query(MapuState.confirm, F.data == "mapu_go")
async def cb_mapu_go(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cards = data.get("cards") or []
    await state.clear()
    await c.answer()

    if c.from_user.id != ADMIN_ID and is_gate_maintenance("Point"):
        await c.message.edit_text(f"{e('🛠️')} <b>Point Gate is currently under maintenance.</b>\nPlease try again later.")
        return

    db = load_db()
    u = get_user(db, c.from_user)
    status = await c.message.edit_text(f"{e('🚀')} <b>Starting bulk check...</b>")

    lines = []
    done = 0
    for cn, em, ey, cv in cards:
        card_start = time.time()
                                
        blocked, block_reason = await asyncio.get_event_loop().run_in_executor(
            None, is_blocked_card_type, cn
        )
        if blocked:
            lines.append(f"<code>{cn}|{em}|{ey}|{cv}</code> → ❌ Blocked ({block_reason})")
            done += 1
            try:
                await status.edit_text(
                    f"{e('🚀')} <b>Bulk check in progress...</b> ({done}/{len(cards)})\n\n" + "\n".join(lines)
                )
            except Exception:
                pass
            continue

        try:
            res = await asyncio.get_event_loop().run_in_executor(
                None, execute_gate_query, "point", cn, em, ey, cv
            )
        except Exception as exc:
            res = f"{e('⚠️')} Error: {censor_text(str(exc))}"

        taken = round(time.time() - card_start, 2)
        res = censor_text(str(res))
        display_res = clean_gate_result(res)
        done += 1
        u["used"] += 1
        u["total_checks"] = u.get("total_checks", 0) + 1
        if "Approved" in res:
            u["successful_checks"] = u.get("successful_checks", 0) + 1
            card_str = f"{cn}|{em}|{ey}|{cv}"
            global_hit_num = get_next_global_hit_count()
            await send_hit_notification(
                username=c.from_user.username,
                user_id=c.from_user.id,
                message_text=display_res,
                taken_time=taken,
                gateway="Point",
                hit_num=global_hit_num,
                cc_data=card_str
            )
        save_db(db)
        lines.append(f"<code>{cn}|{em}|{ey}|{cv}</code> → {display_res}")
        try:
            await status.edit_text(
                f"{e('🚀')} <b>Bulk check in progress...</b> ({done}/{len(cards)})\n\n" + "\n".join(lines)
            )
        except Exception:
            pass

    await status.edit_text(
        f"{e('🏁')} <b>Bulk check completed!</b> ({done}/{len(cards)})\n\n"
        + "\n".join(lines)
        + f"\n\n{e('⏳')} Available: <b>{remaining_str(u)}</b>"
    )

def find_gate_from_text(caption: str):
    cap = (caption or "").strip()
    cmd = cap.split()[0].lower().lstrip("/") if cap else ""
    for gid, ginfo in GATES.items():
        if ginfo.get("command") == cmd or ginfo.get("multi_command") == cmd or gid == cmd or ginfo.get("name", "").lower() == cmd:
            return ginfo
    return None

@router.message(F.document)
@require_channel
async def handle_document_upload(m: Message, state: FSMContext):
    doc = m.document
    if not doc.file_name or not doc.file_name.lower().endswith(".txt"):
        await m.answer(f"{e('⚠️')} Please send a valid <b>.txt</b> file only.")
        return

    if doc.file_size and doc.file_size > 5 * 1024 * 1024:
        await m.answer(f"{e('⚠️')} File size is too large (Maximum 5 MB).")
        return

    gate_info = find_gate_from_text(m.caption) if m.caption else None

    if not gate_info:
        gate_btns = []
        for gid, ginfo in GATES.items():
            gate_btns.append(InlineKeyboardButton(text=f"{ginfo['name']} (/{ginfo['command']})", callback_data=f"txtgate_{gid}_{doc.file_id[:20]}", icon_custom_emoji_id=emoji_id("⚡"), style="primary"))

        rows = [gate_btns[i:i+2] for i in range(0, len(gate_btns), 2)]
        rows.append([InlineKeyboardButton(text="Cancel", callback_data="cancel_txt_file", icon_custom_emoji_id=emoji_id("❌"), style="danger")])
        gate_kb = InlineKeyboardMarkup(inline_keyboard=rows)

        await state.update_data(cached_doc_file_id=doc.file_id, cached_doc_name=doc.file_name)

        guide_msg = (
            f"{e('📁')} <b>TXT File Detected:</b> <code>{html.escape(doc.file_name)}</code>\n\n"
            f"▫️ <b>How to Use:</b>\n"
            f"1. <b>Reply</b> to this message or your uploaded file with a gate command:\n"
            f"   • <code>/pu</code> (Point Gate)\n\n"
            f"2. Or choose your target gateway directly using the buttons below 👇\n\n"
            f"{e('⚠️')} <i>Maximum 300 cards supported per file.</i>"
        )
        await m.reply(guide_msg, reply_markup=gate_kb)
        return

    await prepare_and_confirm_txt_check(m, doc, gate_info, state)

@router.callback_query(F.data == "cancel_txt_file")
async def cb_cancel_txt_file(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text(f"{e('❌')} <b>File check cancelled.</b>")
    await c.answer()

@router.callback_query(F.data.startswith("txtgate_"))
async def cb_txt_select_gate_button(c: CallbackQuery, state: FSMContext):
    parts = c.data.split("_")
    gid = parts[1]
    gate_info = GATES.get(gid)
    if not gate_info:
        await c.answer("Invalid gateway.", show_alert=True)
        return

    data = await state.get_data()
    file_id = data.get("cached_doc_file_id")
    file_name = data.get("cached_doc_name", "cards.txt")

    if not file_id:
        await c.answer("Session expired, please re-upload your .txt file.", show_alert=True)
        return

    class FakeDoc:
        def __init__(self, fid, fname):
            self.file_id = fid
            self.file_name = fname
            self.file_size = 0

    await prepare_and_confirm_txt_check(c.message, FakeDoc(file_id, file_name), gate_info, state, edit_msg=c.message)
    await c.answer()

@router.message(F.reply_to_message & F.reply_to_message.document)
@require_channel
async def handle_reply_to_txt_file(m: Message, state: FSMContext):
    orig_msg = m.reply_to_message
    doc = orig_msg.document
    if not doc or not doc.file_name or not doc.file_name.lower().endswith(".txt"):
        return

    gate_info = find_gate_from_text(m.text)
    if not gate_info:
        gate_list = ", ".join([f"<code>/{g['command']}</code> ({g['name']})" for g in GATES.values()])
        await m.reply(
            f"{e('⚠️')} <b>Invalid gate command!</b>\n"
            f"Please reply with a valid gateway command:\n{gate_list}"
        )
        return

    await prepare_and_confirm_txt_check(m, doc, gate_info, state)

async def prepare_and_confirm_txt_check(event_msg: Message, doc, gate_info: dict, state: FSMContext, edit_msg=None):
    gate_name = gate_info.get("name", "Unknown")
    gate_id = gate_info.get("id")

    from_user = event_msg.from_user
    if from_user.id != ADMIN_ID and is_gate_maintenance(gate_name):
        text_maint = f"{e('🛠️')} <b>{gate_name} Gate is currently under maintenance.</b>\nPlease try again later."
        if edit_msg:
            await edit_msg.edit_text(text_maint)
        else:
            await event_msg.answer(text_maint)
        return

    db = load_db()
    u = get_user(db, from_user)

    status_txt = f"{e('📥')} Downloading file and scanning cards..."
    if edit_msg:
        wait_dl = edit_msg
        await edit_msg.edit_text(status_txt)
    else:
        wait_dl = await event_msg.answer(status_txt)

    try:
        file_bytes = io.BytesIO()
        await event_msg.bot.download(doc.file_id, destination=file_bytes)
        file_bytes.seek(0)
        text_content = file_bytes.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        await wait_dl.edit_text(f"{e('❌')} File could not be downloaded: {str(exc)}")
        return

    parsed = parse_cards(text_content)
    valid = [c for c in parsed if c is not None]

    if not valid:
        await wait_dl.edit_text(f"{e('⚠️')} No valid credit cards found in file.")
        return

    if len(valid) > 300:
        await wait_dl.edit_text(
            f"{e('🚫')} <b>Card Limit Exceeded!</b>\n\n"
            f"▫️ Cards detected in file: <b>{len(valid)}</b>\n"
            f"▫️ Maximum allowed cards: <b>300</b>\n\n"
            f"Please reduce your file to at most 300 cards and try again."
        )
        return

    user_rem = remaining(u)
    cards_count = len(valid)

    if user_rem < cards_count:
        await wait_dl.edit_text(
            f"{e('🚫')} <b>Insufficient Checks!</b>\n\n"
            f"{e('💳')} Cards in File: <b>{cards_count}</b>\n"
            f"{e('⏳')} Your Available Balance: <b>{remaining_str(u)}</b>\n\n"
            f"Upgrade your plan to get more checks: <code>/buy</code>"
        )
        return

    if u.get("tier") == TIER_UNLIMITED:
        balance_after_str = "Unlimited"
    else:
        rem_after = max(0, user_rem - cards_count)
        balance_after_str = f"{rem_after}/{u.get('total', 0)}"

    await state.update_data(txt_cards=valid, txt_gate=gate_info)
    await state.set_state(TxtCheckState.confirm)

    listing = "\n".join(f"▫️ <code>{c[0]}|{c[1]}|{c[2]}|{c[3]}</code>" for c in valid[:6])
    more_txt = f"\n<i>...and {cards_count - 6} more</i>" if cards_count > 6 else ""

    confirm_text = (
        f"{e('📋')} <b>TXT Bulk Check Ready</b> {e('✨')}\n"
        f"★━━━━━━━━━━━━━━★\n"
        f"▫️ <b>File:</b> <code>{html.escape(doc.file_name)}</code>\n"
        f"▫️ <b>Gateway:</b> <code>{html.escape(gate_name)}</code>\n"
        f"▫️ <b>Total Cards:</b> <b>{cards_count}</b> / 300\n"
        f"▫️ <b>Current Balance:</b> <code>{remaining_str(u)}</code>\n"
        f"▫️ <b>Balance After Check:</b> <code>{balance_after_str}</code>\n"
        f"★━━━━━━━━━━━━━━★\n"
        f"<b>Card Preview:</b>\n{listing}{more_txt}\n\n"
        f"{e('⚡')} <i>Press <b>Confirm</b> to begin processing or <b>Decline</b> to cancel.</i>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Confirm", callback_data="txt_go", icon_custom_emoji_id=emoji_id("✅"), style="success"),
            InlineKeyboardButton(text="Decline", callback_data="txt_cancel", icon_custom_emoji_id=emoji_id("❌"), style="danger"),
        ]
    ])
    await wait_dl.edit_text(confirm_text, reply_markup=kb)

@router.callback_query(TxtCheckState.confirm, F.data == "txt_cancel")
async def cb_txt_cancel(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text(f"{e('❌')} <b>Process declined.</b> No checks were consumed.")
    await c.answer()

@router.callback_query(TxtCheckState.confirm, F.data == "txt_go")
async def cb_txt_go(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cards = data.get("txt_cards") or []
    gate_info = data.get("txt_gate") or {}
    await state.clear()
    await c.answer()

    gate_name = gate_info.get("name", "Unknown")
    gate_id = gate_info.get("id")

    if c.from_user.id != ADMIN_ID and is_gate_maintenance(gate_name):
        await c.message.edit_text(f"{e('🛠️')} <b>{gate_name} Gate is under maintenance.</b>\nPlease try again later.")
        return

    db = load_db()
    u = get_user(db, c.from_user)
    status_msg = await c.message.edit_text(f"{e('🚀')} <b>Starting TXT check...</b>\nGateway: <code>{gate_name}</code> (0/{len(cards)})")

    approved_list = []
    declined_list = []
    blocked_list = []
    done = 0
    total = len(cards)
    start_time = time.time()
    last_update_time = time.time()
    last_card_line = "None"

    def render_progress_text(is_done=False):
        elapsed = max(0.1, round(time.time() - start_time, 1))
        speed = round(done / elapsed, 1) if elapsed > 0 else 0
        pct = int((done / total) * 100) if total > 0 else 0
        filled = int((pct / 100) * 10)
        bar = "▰" * filled + "▱" * (10 - filled)

        header = f"{e('🏁')} <b>TXT Bulk Check Completed!</b>" if is_done else f"{e('🚀')} <b>TXT Bulk Check in Progress...</b>"

        return (
            f"{header}\n"
            f"★━━━━━━━━━━━━━━★\n"
            f"▫️ <b>Gateway:</b> <code>{html.escape(gate_name)}</code>\n"
            f"▫️ <b>Progress:</b> <code>[{bar}] {pct}%</code> (<b>{done}/{total}</b>)\n"
            f"▫️ <b>Last Checked:</b> <code>{html.escape(last_card_line)}</code>\n"
            f"★━━━━━━━━━━━━━━★\n"
            f"▫️ {e('✅')} <b>Approved:</b> <code>{len(approved_list)}</code>\n"
            f"▫️ {e('❌')} <b>Declined:</b> <code>{len(declined_list)}</code>\n"
            f"▫️ {e('🚫')} <b>Blocked:</b> <code>{len(blocked_list)}</code>\n"
            f"★━━━━━━━━━━━━━━★\n"
            f"▫️ {e('⚡')} <b>Speed:</b> <code>{speed} cards/sec</code>\n"
            f"▫️ {e('⏱️')} <b>Time Elapsed:</b> <code>{round(elapsed, 1)}s</code>\n"
            f"▫️ {e('⏳')} <b>Remaining Balance:</b> <code>{remaining_str(u)}</code>"
        )

    for cn, em, ey, cv in cards:
        card_str = f"{cn}|{em}|{ey}|{cv}"
        card_start = time.time()

        blocked, block_reason = await asyncio.get_event_loop().run_in_executor(
            None, is_blocked_card_type, cn
        )
        if blocked:
            blocked_list.append(f"{card_str} | Status: Blocked | Response: {block_reason}")
            last_card_line = f"{card_str} (Blocked)"
            done += 1
            if time.time() - last_update_time >= 1.5 or done == total:
                last_update_time = time.time()
                try:
                    await status_msg.edit_text(render_progress_text(is_done=(done == total)))
                except Exception:
                    pass
            continue

        try:
            res = await asyncio.get_event_loop().run_in_executor(
                None, execute_gate_query, gate_id, cn, em, ey, cv
            )
        except Exception as exc:
            res = f"Error: {str(exc)}"

        taken = round(time.time() - card_start, 2)
        res = censor_text(str(res))
        display_res = clean_gate_result(res)

        done += 1
        u["used"] += 1
        u["total_checks"] = u.get("total_checks", 0) + 1

        if "Approved" in res:
            u["successful_checks"] = u.get("successful_checks", 0) + 1
            approved_list.append(f"{card_str} | Status: Approved | Gateway: {gate_name} | Response: {display_res} | Time: {taken}s")
            last_card_line = f"{card_str} (Approved)"
            global_hit_num = get_next_global_hit_count()
            await send_hit_notification(
                username=c.from_user.username,
                user_id=c.from_user.id,
                message_text=display_res,
                taken_time=taken,
                gateway=gate_name,
                hit_num=global_hit_num,
                cc_data=card_str
            )
        else:
            declined_list.append(f"{card_str} | Status: Declined | Gateway: {gate_name} | Response: {display_res} | Time: {taken}s")
            last_card_line = f"{card_str} (Declined)"

        save_db(db)

        if time.time() - last_update_time >= 1.5 or done == total:
            last_update_time = time.time()
            try:
                await status_msg.edit_text(render_progress_text(is_done=(done == total)))
            except Exception:
                pass

    try:
        await status_msg.edit_text(render_progress_text(is_done=True))
    except Exception:
        pass

    ts = int(time.time())
    stats_header = (
        f"# ==========================================\n"
        f"# GATEWAY: {gate_name.upper()}\n"
        f"# TOTAL CARDS: {total}\n"
        f"# APPROVED: {len(approved_list)}\n"
        f"# DECLINED: {len(declined_list)}\n"
        f"# BLOCKED: {len(blocked_list)}\n"
        f"# TOTAL TIME: {round(time.time() - start_time, 2)}s\n"
        f"# DATE: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"# ==========================================\n\n"
    )

    if approved_list:
        approved_body = stats_header + "\n".join(approved_list) + "\n"
        app_doc = BufferedInputFile(approved_body.encode("utf-8"), filename=f"approved_{gate_name.lower()}_{ts}.txt")
        await c.message.answer_document(
            document=app_doc,
            caption=f"{e('✅')} <b>Approved Cards</b> (<code>{len(approved_list)}</code> cards)"
        )

    if declined_list:
        declined_body = stats_header + "\n".join(declined_list) + "\n"
        dec_doc = BufferedInputFile(declined_body.encode("utf-8"), filename=f"declined_{gate_name.lower()}_{ts}.txt")
        await c.message.answer_document(
            document=dec_doc,
            caption=f"{e('❌')} <b>Declined Cards</b> (<code>{len(declined_list)}</code> cards)"
        )

    if blocked_list:
        blocked_body = stats_header + "\n".join(blocked_list) + "\n"
        blk_doc = BufferedInputFile(blocked_body.encode("utf-8"), filename=f"blocked_{gate_name.lower()}_{ts}.txt")
        await c.message.answer_document(
            document=blk_doc,
            caption=f"{e('🚫')} <b>Blocked Cards (Prepaid/Debit)</b> (<code>{len(blocked_list)}</code> cards)"
        )


from backup import backup_worker

async def main():
    write_log("INFO", "Bot startup sequence initiated.")
    try:
        register_gate_commands(router)
        bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
        await load_emoji_pack(bot)
        dp = Dispatcher(storage=MemoryStorage())
        dp.include_router(router)
        asyncio.create_task(backup_worker(bot))
        write_log("INFO", "Bot is ready and polling started.")
    except Exception as exc:
        err_details = traceback.format_exc()
        write_log("FATAL", f"Initialization failed: {exc}\n{err_details}")
        raise

    while True:
        try:
            await dp.start_polling(bot, drop_pending_updates=True)
        except Exception as e:
            err_details = traceback.format_exc()
            write_log("ERROR", f"Polling crashed: {e}\n{err_details}")
            await asyncio.sleep(3)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        err_details = traceback.format_exc()
        write_log("CRASH", f"Unhandled critical crash in main loop: {exc}\n{err_details}")
