import os
import re
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Error: กรุณาตั้งค่า SUPABASE_URL และ SUPABASE_KEY ใน Environment Variables")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

FUND_MAP = {
    'IGOLD-G': ['IGOLD-G', 'IGOLD'],
    'MGTECH':  ['MGTECH', 'MTECH', 'M-TECH'],
    'M-EM':    ['M-EM', 'MEM'],
    'MEURO-G': ['MEURO-G', 'MEURO'],
    'MGFPVD':  ['MGFPVD', 'MGF'],
    'M-ASIA':  ['M-ASIA', 'MASIA']
}

def fetch_mfc_nav():
    # 🔗 อัปเดต URL ไปยังหน้าใหม่
    url = "https://mfcfund.com/funds/filtersets/prices"
    nav_results = {}

    print(f"📡 กำลังเปิด Headless Browser เพื่อดึงข้อมูลจาก: {url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
                
                # 🛠️ รอให้แถวตารางข้อมูลโหลดเสร็จสมบูรณ์
                page.wait_for_selector("table tr, div[class*='table']", timeout=20000)
                page.wait_for_timeout(3000) # รอเพิ่มเติมเพื่อให้ข้อมูลเรนเดอร์ครบถ้วน
                
                html_content = page.content()
            finally:
                browser.close()

        soup = BeautifulSoup(html_content, 'html.parser')
        rows = soup.find_all('tr')
        print(f"ℹ️ พบแถวตารางทั้งหมด: {len(rows)} แถว")
        
        for row in rows:
            raw_text = row.get_text(separator=' ', strip=True)
            if not raw_text:
                continue

            # ทำความสะอาดข้อความสำหรับการจับชื่อกองทุน
            clean_text = re.sub(r'[\s\-]+', '', raw_text).upper()

            for asset_name, aliases in FUND_MAP.items():
                if asset_name in nav_results:
                    continue

                for alias in aliases:
                    clean_alias = re.sub(r'[\s\-]+', '', alias).upper()
                    
                    # ตรวจสอบว่าชื่อ/อักษรย่อกองทุนอยู่ในแถวนี้หรือไม่
                    if clean_alias in clean_text:
                        # ดึงตัวเลขทศนิยม 4 ตำแหน่ง (รูปแบบ NAV ของ MFC)
                        matches = re.findall(r'\b\d{1,4}(?:\,\d{3})*\.\d{4}\b', raw_text)
                        
                        # ลองสกัดวันที่ NAV (ถ้ามีในแถว เช่น DD/MM/YYYY)
                        date_match = re.search(r'\b(\d{1,2}/\d{1,2}/\d{4})\b', raw_text)
                        parsed_date = None
                        if date_match:
                            try:
                                d_str = date_match.group(1)
                                parsed_date = datetime.strptime(d_str, "%d/%m/%Y").strftime("%Y-%m-%d")
                            except ValueError:
                                parsed_date = None

                        if matches:
                            try:
                                # ค่าแรกของทศนิยม 4 ตำแหน่งในคอลัมน์ NAV per Unit
                                nav_val = float(matches[0].replace(',', ''))
                                if 0.1 <= nav_val <= 5000.0:
                                    nav_results[asset_name] = {
                                        "nav": nav_val,
                                        "nav_date": parsed_date
                                    }
                                    print(f"✅ เจอ {asset_name} -> NAV: {nav_val} (วันที่: {parsed_date or 'N/A'})")
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
    now_thai = datetime.now(thai_tz)
    today_str = now_thai.strftime("%Y-%m-%d")

    try:
        db_res = supabase.table("user_portfolios").select("*").ilike("app_source", "MFC").execute()
        mfc_items = db_res.data or []
    except Exception as e:
        print(f"❌ ไม่สามารถดึงข้อมูลจาก Supabase ได้: {e}")
        return

    batch_payload = []
    for item in mfc_items:
        asset_name = item.get("asset_name", "").strip()
        asset_code = item.get("asset_code", "").strip()
        
        # ตรวจสอบทั้ง asset_name และ asset_code
        nav_info = nav_data.get(asset_name) or nav_data.get(asset_code)

        if nav_info:
            nav_val = nav_info["nav"]
            nav_date = nav_info.get("nav_date") or today_str
            units = float(item.get("units") or 0)
            
            updated_item = item.copy()
            updated_item.update({
                "current_nav": round(nav_val, 4),
                "current_value": round(units * nav_val, 4),
                "nav_date": nav_date,
                "updated_at": now_thai.isoformat()
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
    print("🚀 เริ่มต้นกระบวนการ Auto Update NAV (Playwright - MFC Filtersets)...")
    nav_data = fetch_mfc_nav()
    print("-" * 40)
    print(f"📊 สรุปข้อมูลที่ดึงได้ ({len(nav_data)}/{len(FUND_MAP)} กองทุน): {nav_data}")
    print("-" * 40)
    update_supabase_batch(nav_data)
    print("✨ ทำงานเสร็จสิ้น!")