import os
import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup
import requests
from supabase import Client, create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Missing Supabase Credentials")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

def get_gpf_nav_direct():
    nav_map = {}
    try:
        gpf_url = "https://www.gpf.or.th/thai2019/About/main.php?page=memberfund&lang=th&size=n&pattern=n&menu=statistic"
        res = requests.get(gpf_url, headers=HEADERS, timeout=15)
        res.encoding = "utf-8" if "utf-8" in res.text.lower() else "tis-620"

        soup = BeautifulSoup(res.text, "html.parser")
        for row in soup.find_all("tr"):
            text = row.get_text()
            cols = [re.sub(r"\s+", "", col.get_text()) for col in row.find_all(["td", "th"])]
            if not cols:
                continue

            nav_candidates = []
            for col_text in cols:
                match = re.search(r"^\d{1,3}(?:,\d{3})*\.\d{4}$", col_text)
                if match:
                    nav_candidates.append(float(match.group(0).replace(",", "")))

            if not nav_candidates:
                continue

            nav_val = nav_candidates[0]
            if "หุ้นต่างประเทศ" in text or "1788632129596" in text:
                nav_map["1788632129596"] = nav_val
                nav_map["แผนหุ้นต่างประเทศ"] = nav_val
            elif "หุ้นไทย" in text and "ต่างประเทศ" not in text:
                nav_map["1788631314182"] = nav_val
                nav_map["แผนหุ้นไทย"] = nav_val
            elif "อสังหาริมทรัพย์" in text or "1788632247228" in text:
                nav_map["1788632247228"] = nav_val
                nav_map["แผนอสังหาริมทรัพย์ไทย"] = nav_val

    except Exception as e:
        print(f"⚠️ GPF Fetch Error: {e}")

    return nav_map

def run_gpf_update():
    thai_tz = timezone(timedelta(hours=7))
    now_thai_dt = datetime.now(thai_tz)
    now_thai = now_thai_dt.strftime("%Y-%m-%dT%H:%M:%S+07:00")
    today_date_str = now_thai_dt.strftime("%d/%m/%Y")

    gpf_nav_data = get_gpf_nav_direct()
    if not gpf_nav_data:
        print("⚠️ ไม่สามารถดึงข้อมูล NAV จาก GPF ได้")
        return

    db_res = supabase.table("user_portfolios").select("*").ilike("app_source", "GPF").execute()
    gpf_items = db_res.data or []

    print(f"📦 พบรายการ GPF ในระบบ {len(gpf_items)} รายการ")

    for item in gpf_items:
        item_id = item["id"]
        code = item.get("asset_code", "").strip()
        units = float(item.get("units") or 0)
        latest_nav = gpf_nav_data.get(code)

        if latest_nav and latest_nav > 0:
            update_payload = {
                "current_nav": round(latest_nav, 4),
                "current_value": round(units * latest_nav, 4),
                "nav_date": today_date_str,
                "updated_at": now_thai
            }
            supabase.table("user_portfolios").update(update_payload).eq("id", item_id).execute()
            print(f" ✅ [GPF] {code}: NAV={latest_nav} | Value=฿{units * latest_nav:,.2f}")

if __name__ == "__main__":
    run_gpf_update()