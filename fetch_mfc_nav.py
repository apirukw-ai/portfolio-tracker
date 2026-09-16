import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

import requests
from supabase import Client, create_client

# ==========================================
# 1. ตั้งค่าการเชื่อมต่อ และ Environment Variables
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SEC_API_KEY = os.environ.get("SEC_API_KEY", "260c6d98184a4ec491ff27a5ad8f226b") # แนะนำให้เซ็ตผ่าน Env

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Error: กรุณาตั้งค่า SUPABASE_URL และ SUPABASE_KEY ใน Environment Variables")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 2. จับคู่ asset_name ใน Supabase -> ชื่อสัญลักษณ์บนเว็บ/ก.ล.ต.
# ==========================================
FUND_MAP = {
    'IGOLD-G': ['IGOLD-G', 'IGOLD'],         # MPF07
    'MGTECH':  ['MGTECH', 'MTECH', 'M-TECH'],  # MPF15
    'M-EM':    ['M-EM', 'MEM'],              # MPF18
    'MEURO-G': ['MEURO-G', 'MEURO'],         # MPF19
    'MGFPVD':  ['MGFPVD', 'MGF'],            # MPF23
    'M-ASIA':  ['M-ASIA', 'MASIA']           # MPF27
}

def clean_string(text: str) -> str:
    """ลบช่องว่างและขีดออก พร้อมทำเป็นตัวพิมพ์ใหญ่สำหรับการเปรียบเทียบ"""
    return re.sub(r'[\s\-]+', '', str(text)).strip().upper()

def fetch_mfc_nav() -> Dict[str, float]:
    """ดึงข้อมูล NAV จาก SEC Open API และใช้ Finnomena เป็น Fallback"""
    sec_url = "https://api.sec.or.th/FundDailyInfo/C0000000062/dailynav"
    fallback_url = "https://backend.finnomena.com/api/v1/fund/nav/latest"
    nav_results: Dict[str, float] = {}

    headers = {
        "Ocp-Apim-Subscription-Key": SEC_API_KEY,
        "User-Agent": "Mozilla/5.0"
    }

    print("📡 กำลังดึงข้อมูล NAV ผ่าน SEC Open API...")

    # ใช้ Session เพื่อการเชื่อมต่อที่มีประสิทธิภาพ
    with requests.Session() as session:
        try:
            response = session.get(sec_url, headers=headers, timeout=15)
            
            # กรณี SEC API ใช้งานไม่ได้ หรือติด Rate Limit -> ใช้ Fallback API
            if response.status_code != 200:
                print(f"⚠️ SEC Main API status: {response.status_code} กำลังลอง Endpoint สำรอง...")
                res_fn = session.get(fallback_url, timeout=15)
                res_fn.raise_for_status()
                
                fn_data = res_fn.json().get("data", [])
                for item in fn_data:
                    fund_code = item.get("fund_code", "")
                    nav_val = item.get("nav")
                    
                    if not fund_code or nav_val is None:
                        continue
                        
                    clean_fund_code = clean_string(fund_code)
                    
                    for asset_name, aliases in FUND_MAP.items():
                        if asset_name in nav_results:
                            continue
                        # ตรวจสอบว่า fund_code ตรงกับ alias ใดๆ หรือไม่
                        if clean_fund_code in [clean_string(a) for a in aliases]:
                            nav_results[asset_name] = float(nav_val)
                            print(f"✅ เจอ {asset_name} ({fund_code}) -> NAV: {nav_val}")
                            break
                return nav_results

            # กรณี SEC API ใช้งานได้ปกติ
            sec_data = response.json()
            items = sec_data if isinstance(sec_data, list) else sec_data.get("last_val", [])

            print(f"ℹ️ ดึงข้อมูลสำเร็จ พบข้อมูลกองทุนทั้งหมด: {len(items)} รายการ")

            for item in items:
                raw_name = item.get("proj_abbr_name", "") or item.get("proj_name_en", "")
                nav_val_raw = item.get("nav_price") or item.get("net_val")

                if not raw_name or nav_val_raw is None:
                    continue

                try:
                    nav_val = float(nav_val_raw)
                except ValueError:
                    continue

                clean_fund_name = clean_string(raw_name)

                for asset_name, aliases in FUND_MAP.items():
                    if asset_name in nav_results:
                        continue

                    if clean_fund_name in [clean_string(a) for a in aliases]:
                        if 1.0 <= nav_val <= 1000.0:
                            nav_results[asset_name] = nav_val
                            print(f"✅ เจอ {asset_name} ({raw_name}) -> NAV: {nav_val}")
                            break

            return nav_results

        except requests.RequestException as req_err:
            print(f"❌ เกิดข้อผิดพลาดด้านเครือข่าย/API: {req_err}")
        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาดขณะจัดการข้อมูล NAV: {e}")
            
    return nav_results

def update_supabase(nav_data: Dict[str, float]) -> None:
    """อัปเดตข้อมูล NAV ล่าสุดลงในฐานข้อมูล Supabase"""
    if not nav_data:
        print("⚠️ ไม่มีข้อมูล NAV ที่จะอัปเดต")
        return

    # จัดการเวลาประเทศไทย (UTC+7)
    thai_tz = timezone(timedelta(hours=7))
    now_thai_dt = datetime.now(thai_tz)
    now_thai_iso = now_thai_dt.isoformat() # เช่น 2026-09-16T11:42:13+07:00
    today_date_str = now_thai_dt.strftime("%d/%m/%Y")

    try:
        db_res = supabase.table("user_portfolios").select("*").ilike("app_source", "MFC").execute()
        mfc_items = db_res.data or []
    except Exception as e:
        print(f"❌ ไม่สามารถดึงข้อมูลจาก Supabase ได้: {e}")
        return

    for item in mfc_items:
        item_id = item["id"]
        asset_name = item.get("asset_name", "").strip()
        units = float(item.get("units") or 0)

        latest_nav = nav_data.get(asset_name)

        if latest_nav:
            current_value = round(units * latest_nav, 4)
            update_payload = {
                "current_nav": round(latest_nav, 4),
                "current_value": current_value,
                "nav_date": today_date_str,
                "updated_at": now_thai_iso
            }
            
            try:
                supabase.table("user_portfolios").update(update_payload).eq("id", item_id).execute()
                print(f"💾 อัปเดต Supabase สำเร็จ: {asset_name} | NAV: {latest_nav} | Value: ฿{current_value:,.2f}")
            except Exception as e:
                print(f"❌ อัปเดต Supabase ไม่สำเร็จ ({asset_name}): {e}")

if __name__ == "__main__":
    print("🚀 เริ่มต้นกระบวนการ Auto Update NAV (SEC Open API)...")
    nav_data = fetch_mfc_nav()
    
    print("-" * 40)
    print(f"📊 สรุปข้อมูลที่พร้อมอัปเดต ({len(nav_data)} กองทุน):")
    for fund, nav in nav_data.items():
        print(f"   - {fund}: {nav}")
    print("-" * 40)
        
    update_supabase(nav_data)
    print("✨ ทำงานเสร็จสิ้น!")
