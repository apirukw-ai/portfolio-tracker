import os
import re
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from supabase import create_client, Client

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
    'IGOLD-G': ['IGOLD-G', 'IGOLD'],       # MPF07
    'MGTECH':  ['MGTECH', 'MTECH', 'M-TECH'], # MPF15
    'M-EM':    ['M-EM', 'MEM'],            # MPF18
    'MEURO-G': ['MEURO-G', 'MEURO'],       # MPF19
    'MGFPVD':  ['MGFPVD', 'MGF'],          # MPF23
    'M-ASIA':  ['M-ASIA', 'MASIA']         # MPF27
}

def fetch_mfc_nav():
    url = "https://mfcfund.com/unit-value/"
    nav_results = {}

    print(f"📡 กำลังเปิด Headless Browser เพื่อดึงข้อมูลจาก: {url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000)

            html_content = page.content()
            browser.close()

        soup = BeautifulSoup(html_content, 'html.parser')
        rows = soup.find_all('tr')
        print(f"ℹ️ พบแถวตาราง (tr) ทั้งหมด: {len(rows)} แถว")

        for row in rows:
            raw_text = row.get_text()
            clean_text = re.sub(r'[\s\-]+', '', raw_text).upper()

            for asset_name, aliases in FUND_MAP.items():
                if asset_name in nav_results:
                    continue

                for alias in aliases:
                    clean_alias = re.sub(r'[\s\-]+', '', alias).upper()
                    
                    if clean_alias in clean_text:
                        matches = re.findall(r'\d[\d\,]*\.\d{4}', raw_text)
                        if matches:
                            try:
                                nav_val = float(matches[0].replace(',', ''))
                                if 1.0 <= nav_val <= 500.0:
                                    nav_results[asset_name] = nav_val
                                    print(f"✅ เจอ {asset_name} (จากชื่อบนเว็บ '{alias}') -> NAV: {nav_val}")
                                    break
                            except ValueError:
                                continue

        return nav_results

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดขณะดึง NAV: {e}")
        return nav_results

def update_supabase(nav_data):
    if not nav_data:
        print("⚠️ ไม่มีข้อมูล NAV ที่จะอัปเดต")
        return

    thai_tz = timezone(timedelta(hours=7))
    now_thai_dt = datetime.now(thai_tz)
    now_thai = now_thai_dt.strftime("%Y-%m-%dT%H:%M:%S+07:00")
    today_date_str = now_thai_dt.strftime("%d/%m/%Y")

    # ดึงข้อมูล MFC ทั้งหมดเพื่อเอา units มาคำนวณมูลค่ารวม
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
    print("🚀 เริ่มต้นกระบวนการ Auto Update NAV...")
    nav_data = fetch_mfc_nav()
    print(f"📊 สรุปข้อมูลที่ดึงได้ ({len(nav_data)} กองทุน): {nav_data}")
    update_supabase(nav_data)
    print("✨ ทำงานเสร็จสิ้น!")