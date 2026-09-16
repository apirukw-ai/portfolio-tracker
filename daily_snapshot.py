import os
from datetime import datetime, timedelta, timezone
from supabase import Client, create_client
import yfinance as yf

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Missing Supabase Credentials")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_usd_thb_rate():
    try:
        ticker = yf.Ticker("THB=X")
        hist = ticker.history(period="1d")
        if not hist.empty:
            rate = float(hist["Close"].iloc[-1])
            print(f"💵 อัตราแลกเปลี่ยน USD/THB ปัจจุบัน: {rate:.4f}")
            return rate
    except Exception as e:
        print(f"⚠️ Exchange Rate Fetch Error: {e}")
    
    # Fallback rate หาก yfinance มีปัญหา
    return 34.50 

def save_daily_snapshot(app_source, total_thb):
    try:
        # ดึงวันที่ปัจจุบันของไทย (UTC+7)
        today_str = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%d")
        app_upper = app_source.upper()

        prev_res = (
            supabase.table("portfolio_snapshots")
            .select("reported_ytd_pct, reported_5y_pct, reported_since_inception_pct")
            .ilike("app_source", app_upper)
            .order("snapshot_date", desc=True)
            .limit(1)
            .execute()
        )

        data = {
            "snapshot_date": today_str,
            "app_source": app_upper,
            "total_value_thb": float(total_thb),
        }

        # ดึงเปอร์เซ็นต์ย้อนหลังเดิมมาใส่เพื่อไม่ให้ค่าหาย
        if prev_res.data and len(prev_res.data) > 0:
            last_record = prev_res.data[0]
            for key in ["reported_ytd_pct", "reported_5y_pct", "reported_since_inception_pct"]:
                if last_record.get(key) is not None:
                    data[key] = last_record[key]

        supabase.table("portfolio_snapshots").upsert(
            data, on_conflict="snapshot_date,app_source"
        ).execute()

        print(f"✅ [Snapshot] {app_upper}: ฿{total_thb:,.2f}")
    except Exception as e:
        print(f"⚠️ Failed to save snapshot for {app_source}: {e}")

def run_snapshot_process():
    usd_rate = get_usd_thb_rate()
    db_res = supabase.table("user_portfolios").select("*").execute()
    latest_items = db_res.data or []

    all_apps = {str(i.get("app_source", "")).strip().upper() for i in latest_items if i.get("app_source")}

    for app in all_apps:
        app_items = [
            i for i in latest_items 
            if str(i.get("app_source", "")).strip().upper() == app
        ]

        # คำนวณยอดรวมโดยเช็คทั้ง current_value หรือคำนวณจาก (units * avg_nav/current_nav)
        total_thb = 0.0
        for item in app_items:
            units = float(item.get("units") or 0)
            nav = float(item.get("avg_nav") or item.get("current_nav") or 0)
            
            # หากมี current_value ให้ใช้ตรงๆ ถ้าไม่มีให้คิดจาก units * nav
            val = float(item.get("current_value")) if item.get("current_value") is not None else (units * nav)
            
            if app == "DIME":
                total_thb += (val * usd_rate)
            else:
                total_thb += val

        # บันทึก snapshot (ยอมให้บันทึกกรณี >= 0 เพื่อเก็บประวัติแม้ยอดเป็น 0)
        if total_thb >= 0:
            save_daily_snapshot(app, total_thb)

if __name__ == "__main__":
    run_snapshot_process()
