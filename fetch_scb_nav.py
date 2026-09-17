import os
import re
from datetime import datetime, timedelta, timezone
import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client

# ==========================================
# 1. ตั้งค่าการเชื่อมต่อ Supabase
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Error: กรุณาตั้งค่า SUPABASE_URL และ SUPABASE_KEY ใน Environment Variables")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 2. จับคู่ asset_name -> คำค้นหาสัญลักษณ์กองทุน
# ==========================================
FUND_MAP = {
    'SCBAXJ(E)':    ['SCBAXJ(E)', 'SCBAXJ-E', ' SCBAXJ(E) '],
    'SCBNDQ(E)':    ['SCBNDQ(E)', 'SCBNDQ-E', ' SCBNDQ(E) '],
    'SCBS&P500E':   ['SCBS&P500E', 'SCBS&P500(E)', 'SCBS&P500-E', ' SCBS&P500E '],
    'SCBSEMI(E)':   ['SCBSEMI(E)', 'SCBSEMI-E', ' SCBSEMI(E) '],
    'SCBWORLD(E)':  ['SCBWORLD(E)', 'SCBWORLD-E', ' SCBWORLD(E) ']
}

def clean_symbol(text):
    """ฟังก์ชันทำความสะอาดข้อความ ลบช่องว่าง และจัดการ HTML entities เช่น &amp;"""
    if not text:
        return ""
    text = text.replace('&amp;', '&')
    return re.sub(r'[\s\-_()]+', '', text).upper()

def fetch_scb_nav():
    url = "https://www.scbam.com/medias/inc/navmail.html"
    nav_results = {}

    print(f"📡 กำลังดึงข้อมูล NAV จากหน้าเว็บ SCBAM Direct: {url}")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    }

    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.encoding = 'utf-8'

        if response.status_code != 200:
            print(f"❌ ดึงข้อมูลไม่สำเร็จ HTTP Status: {response.status_code}")
            return nav_results

        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.find_all('tr')

        for row in rows:
            raw_text = row.get_text()
            clean_text = clean_symbol(raw_text)

            for asset_name, aliases in FUND_MAP.items():
                if asset_name in nav_results:
                    continue

                for alias in aliases:
                    clean_alias = clean_symbol(alias)

                    if clean_alias in clean_text:
                        matches = re.findall(r'\d[\d\,]*\.\d{4}', raw_text)
                        if matches:
                            try:
                                nav_val = float(matches[0].replace(',', ''))
                                if 1.0 <= nav_val <= 500.0:
                                    nav_results[asset_name] = nav_val
                                    print(f"✅ เจอ {asset_name} (สัญลักษณ์ '{alias}') -> NAV: {nav_val}")
                                    break
                            except ValueError:
                                continue

        return nav_results

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดขณะดึง NAV: {e}")
        return nav_results

def update_supabase_batch(nav_data):
    if not nav_data:
        print("⚠️ ไม่มีข้อมูล NAV ที่จะอัปเดต")
        return

    thai_tz = timezone(timedelta(hours=7))
    now_thai_dt = datetime.now(thai_tz)
    now_thai_iso = now_thai_dt.isoformat()
    today_date_str = now_thai_dt.strftime("%Y-%m-%d")

    try:
        db_res = supabase.table("user_portfolios").select("*").ilike("app_source", "SCB").execute()
        scb_items = db_res.data or []
    except Exception as e:
        print(f"❌ ไม่สามารถดึงข้อมูลจาก Supabase ได้: {e}")
        return

    batch_payload = []

    for item in scb_items:
        asset_name = item.get("asset_name", "").strip()
        asset_code = item.get("asset_code", "").strip()
        units = float(item.get("units") or 0)
        
        # เช็คแมตช์ทั้งจาก asset_name และ asset_code
        latest_nav = nav_data.get(asset_name) or nav_data.get(asset_code)

        if latest_nav:
            updated_item = item.copy()
            updated_item.update({
                "current_nav": round(latest_nav, 4),
                "current_value": round(units * latest_nav, 4),
                "nav_date": today_date_str,
                "updated_at": now_thai_iso
            })
            batch_payload.append(updated_item)

    if batch_payload:
        try:
            supabase.table("user_portfolios").upsert(batch_payload).execute()
            print(f"💾 อัปเดต Supabase แบบ Batch สำเร็จทั้งหมด {len(batch_payload)} รายการ")
        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาดในการอัปเดตแบบ Batch: {e}")
    else:
        print("⚠️ ไม่พบข้อมูล asset_name / asset_code ใน Supabase ที่จับคู่ตรงกัน")

if __name__ == "__main__":
    print("🚀 เริ่มต้นกระบวนการ Auto Update NAV (SCB HTML + Batch Upsert)...")
    nav_data = fetch_scb_nav()
    print("-" * 40)
    print(f"📊 สรุปข้อมูลที่ดึงได้ ({len(nav_data)}/{len(FUND_MAP)} กองทุน): {nav_data}")
    print("-" * 40)
    update_supabase_batch(nav_data)
    print("✨ ทำงานเสร็จสิ้น!")
