import os
import re
from datetime import datetime, timedelta, timezone
import requests
from supabase import Client, create_client

# ==========================================
# 1. ตั้งค่าการเชื่อมต่อ Supabase
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Error: กรุณาตั้งค่า SUPABASE_URL และ SUPABASE_KEY ใน GitHub Secrets")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 2. จับคู่ asset_name ใน Supabase -> ชื่อสัญลักษณ์บนเว็บ MFC
# ==========================================
FUND_MAP = {
    'IGOLD-G': ['IGOLD-G', 'IGOLD'],         # MPF07
    'MGTECH':  ['MGTECH', 'MTECH', 'M-TECH'],  # MPF15
    'M-EM':    ['M-EM', 'MEM'],              # MPF18
    'MEURO-G': ['MEURO-G', 'MEURO'],         # MPF19
    'MGFPVD':  ['MGFPVD', 'MGF'],            # MPF23
    'M-ASIA':  ['M-ASIA', 'MASIA']           # MPF27
}


def fetch_mfc_nav():
    # ใช้ API หน้าตารางราคาของ MFC โดยตรง
    url = "https://www.mfcfund.com/api/fund/getfundnavlist"
    nav_results = {}

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://mfcfund.com/unit-value/"
    }

    print(f"📡 กำลังดึงข้อมูลผ่าน MFC API: {url}")

    try:
        response = requests.get(url, headers=headers, timeout=30)
        
        # หาก API หลักไม่คืน JSON ให้ Fallback ไปลองดึงผ่าน SEC Open API หรือ HTML
        if response.status_code != 200:
            print(f"⚠️ API ตอบกลับด้วย Status Code: {response.status_code}")
            return nav_results

        data = response.json()
        items = data.get("data", []) or data if isinstance(data, list) else []

        print(f"ℹ️ ดึงข้อมูลสำเร็จ พบกองทุนทั้งหมด: {len(items)} รายการ")

        for item in items:
            # ดึงชื่อกองทุนและค่า NAV จาก JSON Structure ของ MFC
            fund_name = str(item.get("fund_name", "") or item.get("name", "") or item.get("symbol", "")).strip().upper()
            nav_val_raw = item.get("nav") or item.get("net_asset_value") or item.get("nav_price")

            if not fund_name or nav_val_raw is None:
                continue

            try:
                nav_val = float(nav_val_raw)
            except ValueError:
                continue

            clean_fund_name = re.sub(r'[\s\-]+', '', fund_name)

            for asset_name, aliases in FUND_MAP.items():
                if asset_name in nav_results:
                    continue

                for alias in aliases:
                    clean_alias = re.sub(r'[\s\-]+', '', alias).upper()
                    if clean_alias == clean_fund_name or clean_alias in clean_fund_name:
                        if 1.0 <= nav_val <= 1000.0:
                            nav_results[asset_name] = nav_val
                            print(f"✅ เจอ {asset_name} ({fund_name}) -> NAV: {nav_val}")
                            break

        return nav_results

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดขณะดึง NAV ผ่าน API: {e}")
        return nav_results


def update_supabase(nav_data):
    if not nav_data:
        print("⚠️ ไม่มีข้อมูล NAV ที่จะอัปเดต")
        return

    thai_tz = timezone(timedelta(hours=7))
    now_thai_dt = datetime.now(thai_tz)
    now_thai = now_thai_dt.strftime("%Y-%m-%dT%H:%M:%S+07:00")
    today_date_str = now_thai_dt.strftime("%d/%m/%Y")

    db_res = supabase.table("user_portfolios").select("*").ilike("app_source", "MFC").execute()
    mfc_items = db_res.data or []

    for item in mfc_items:
        item_id = item["id"]
        asset_name = item.get("asset_name", "").strip()
        units = float(item.get("units") or 0)

        latest_nav = nav_data.get(asset_name)

        if latest_nav:
            try:
                update_payload = {
                    "current_nav": round(latest_nav, 4),
                    "current_value": round(units * latest_nav, 4),
                    "nav_date": today_date_str,
                    "updated_at": now_thai
                }
                supabase.table("user_portfolios").update(update_payload).eq("id", item_id).execute()
                print(f"💾 อัปเดต Supabase สำเร็จ: {asset_name} = NAV: {latest_nav}, Value: ฿{units * latest_nav:,.2f}")
            except Exception as e:
                print(f"❌ อัปเดต Supabase ไม่สำเร็จ ({asset_name}): {e}")


if __name__ == "__main__":
    print("🚀 เริ่มต้นกระบวนการ Auto Update NAV (MFC API)...")
    nav_data = fetch_mfc_nav()
    print(f"📊 สรุปข้อมูลที่ดึงได้ ({len(nav_data)} กองทุน): {nav_data}")
    update_supabase(nav_data)
    print("✨ ทำงานเสร็จสิ้น!")
