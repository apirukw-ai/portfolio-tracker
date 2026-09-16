import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any
import pythainav as nav
from supabase import Client, create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Error: กรุณาตั้งค่า SUPABASE_URL และ SUPABASE_KEY ใน Environment Variables")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_mfc_nav(symbols: List[str]) -> Dict[str, float]:
    """ดึงข้อมูล NAV ผ่าน pythainav จากรายการ Symbol ที่ระบุ"""
    nav_results: Dict[str, float] = {}
    print("📡 กำลังดึงข้อมูล NAV ผ่าน pythainav...")

    for symbol in set(symbols):
        try:
            result = nav.get(symbol)
            nav_val = None
            
            if hasattr(result, 'value') and result.value is not None:
                nav_val = float(result.value)
            elif isinstance(result, (int, float)):
                nav_val = float(result)

            if nav_val and nav_val > 0:
                nav_results[symbol] = nav_val
                print(f"✅ {symbol:<10} -> NAV: {nav_val}")
            else:
                print(f"⚠️ {symbol:<10} -> ไม่พบค่า NAV ที่ถูกต้อง")
        except Exception as e:
            print(f"❌ {symbol:<10} -> Error: {e}")

    return nav_results

def sync_mfc_portfolios() -> None:
    """ดึงรายการ MFC จาก Supabase แล้วอัปเดต NAV กลับแบบ Batch"""
    thai_tz = timezone(timedelta(hours=7))
    now_thai = datetime.now(thai_tz)
    
    today_date_str = now_thai.strftime("%Y-%m-%d") # ใช้ฟอร์แมต YYYY-MM-DD
    now_iso_str = now_thai.isoformat()

    try:
        db_res = supabase.table("user_portfolios").select("*").ilike("app_source", "MFC").execute()
        mfc_items = db_res.data or []
    except Exception as e:
        print(f"❌ ไม่สามารถดึงข้อมูลจาก Supabase ได้: {e}")
        return

    if not mfc_items:
        print("⚠️ ไม่พบรายการกองทุน MFC ในระบบ")
        return

    # ดึง Unique Asset Names เพื่อนำไปดึง NAV
    target_symbols = [item.get("asset_name", "").strip() for item in mfc_items if item.get("asset_name")]
    nav_data = fetch_mfc_nav(target_symbols)

    batch_payload: List[Dict[str, Any]] = []
    for item in mfc_items:
        asset_name = item.get("asset_name", "").strip()
        units = float(item.get("units") or 0)
        latest_nav = nav_data.get(asset_name)

        if latest_nav:
            batch_payload.append({
                "id": item["id"],
                "current_nav": round(latest_nav, 4),
                "current_value": round(units * latest_nav, 4),
                "nav_date": today_date_str,
                "updated_at": now_iso_str
            })

    if batch_payload:
        try:
            supabase.table("user_portfolios").upsert(batch_payload).execute()
            print(f"💾 อัปเดต Supabase สำเร็จทั้งหมด {len(batch_payload)} รายการ")
        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาดในการอัปเดตแบบ Batch: {e}")

if __name__ == "__main__":
    print("🚀 เริ่มต้นกระบวนการ Auto Update NAV...")
    sync_mfc_portfolios()
    print("✨ ทำงานเสร็จสิ้น!")
