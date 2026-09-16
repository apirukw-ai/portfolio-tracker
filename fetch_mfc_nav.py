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
# 2. รายชื่อกองทุนที่ต้องการดึง NAV
# ==========================================
TARGET_FUNDS = ['IGOLD-G', 'MGTECH', 'M-EM', 'MEURO-G', 'MGFPVD', 'M-ASIA']


def fetch_mfc_nav():
    nav_results = {}
    
    # Endpoint สำหรับดึง NAV กองทุนรวมล่าสุดจากระบบกลาง
    url = "https://api.settrade.com/api/fund/nav/latest"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.settrade.com/"
    }

    print(f"📡 กำลังดึงข้อมูล NAV จาก Open API...")

    # ลองดึงทีละกองทุนจาก Public API เพื่อลดโอกาสการล้มเหลวแบบยกชุด
    for fund in TARGET_FUNDS:
        try:
            # แปลงชื่อกองทุนตัดอักขระพิเศษเพื่อค้นหา
            query_fund = fund.replace('-', '')
            req_url = f"https://fund.kasikornasset.com/api/nav?fund_name={query_fund}"
            
            # ใช้วิธีดึงผ่าน API สาธารณะของ Fund Data Thailand
            api_url = f"https://api.thmutualfund.com/v1/nav/{fund}"
            res = requests.get(api_url, headers=headers, timeout=10)
            
            if res.status_code == 200:
                data = res.json()
                nav_val = float(data.get("nav", 0))
                if nav_val > 0:
                    nav_results[fund] = nav_val
                    print(f"✅ เจอ {fund} -> NAV: {nav_val}")
                    continue
        except Exception:
            pass

    # หากดึง API ไม่สำเร็จ ให้ใช้ Scraping หน้าเว็บสำรองที่ไม่มี Cloudflare บล็อก (Thaifundstoday / Wealthmagik)
    if len(nav_results) < len(TARGET_FUNDS):
        print("ℹ️ กำลังดึงข้อมูลกองทุนที่เหลือผ่าน Service สำรอง...")
        for fund in TARGET_FUNDS:
            if fund in nav_results:
                continue
            try:
                # ดึงผ่าน API สาธารณะสำรอง
                alt_url = f"https://findfund.app/api/nav/{fund}"
                r = requests.get(alt_url, headers=headers, timeout=10)
                if r.status_code == 200:
                    val = r.json().get("nav")
                    if val:
                        nav_results[fund] = float(val)
                        print(f"✅ เจอ {fund} (จาก Server สำรอง) -> NAV: {val}")
            except Exception:
                pass

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
    print("🚀 เริ่มต้นกระบวนการ Auto Update NAV (MFC)...")
    nav_data = fetch_mfc_nav()
    print(f"📊 สรุปข้อมูลที่ดึงได้ ({len(nav_data)} กองทุน): {nav_data}")
    update_supabase(nav_data)
    print("✨ ทำงานเสร็จสิ้น!")
