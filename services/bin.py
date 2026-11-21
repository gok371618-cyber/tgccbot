import re
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "bins.db")

def flag_emoji(alpha2: str) -> str:
    if not alpha2 or len(alpha2) != 2:
        return "🌐"
    return "".join(chr(127397 + ord(c.upper())) for c in alpha2)

def query_bin(bin_code: str) -> dict:
    clean = re.sub(r"[^\d]", "", str(bin_code))
    if len(clean) < 6:
        return {"success": False, "error": "BIN must be at least 6 digits."}

                                            
    search_keys = []
    if len(clean) >= 8:
        search_keys.append(clean[:8])
    search_keys.append(clean[:6])

    if not os.path.exists(DB_PATH):
        return {"success": False, "error": "Local BIN database not found."}

    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        row = None
        matched_bin = None

        for k in search_keys:
            cur.execute("SELECT bin, brand, type, category, issuer, alpha2, country, is_prepaid FROM bins WHERE bin = ?", (k,))
            row = cur.fetchone()
            if row:
                matched_bin = k
                break

        conn.close()

        if row:
            b_num, brand, c_type, category, issuer, alpha2, country, is_prepaid = row
            return {
                "success": True,
                "bin": matched_bin,
                "scheme": brand or "N/A",
                "type": c_type or "N/A",
                "brand": category or "N/A",
                "bank": issuer or "N/A",
                "country": country or "N/A",
                "country_code": alpha2 or "N/A",
                "flag": flag_emoji(alpha2),
                "prepaid": bool(is_prepaid),
                "source": "LocalDB"
            }
        else:
            return {"success": False, "error": "BIN details not found in local database."}
    except Exception as exc:
        return {"success": False, "error": f"Database error: {str(exc)}"}
