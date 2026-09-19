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
    return 33.00

def save_weekly_snapshot(app_source, total_thb):
    try:
        today_str = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%d")
        app_upper = app_source.upper()

        # ดึงข้อมูล Snapshot สัปดาห์ล่าสุดเพื่อคำนวณเปรียบเทียบ WoW
        prev_res = (
            supabase.table("portfolio_snapshots")
            .select("total_value_thb, reported_ytd_pct, reported_5y_pct, reported_since_inception_pct")
            .ilike("app_source", app_upper)
            .order("snapshot_date", desc=True)
            .limit(1)
            .execute()
        )

        wow_change_thb = 0.0
        wow_return_pct = 0.0

        if prev_res.data and len(prev_res.data) > 0:
            last_record = prev_res.data[0]
            prev_total_thb = float(last_record.get("total_value_thb") or 0)
            
            if prev_total_thb > 0:
                wow_change_thb = round(total_thb - prev_total_thb, 2)
                wow_return_pct = round((wow_change_thb / prev_total_thb) * 100, 2)

        data = {
            "snapshot_date": today_str,
            "app_source": app_upper,
            "total_value_thb": round(float(total_thb), 2),
            "wow_change_thb": wow_change_thb,
            "wow_return_pct": wow_return_pct
        }

        # เก็บประวัติ YTD และค่าเดิมถ้ามี
        if prev_res.data and len(prev_res.data) > 0:
            last_record = prev_res.data[0]
            if last_record.get("reported_ytd_pct") is not None:
                data["reported_ytd_pct"] = last_record["reported_ytd_pct"]
            if last_record.get("reported_5y_pct") is not None:
                data["reported_5y_pct"] = last_record["reported_5y_pct"]
            if last_record.get("reported_since_inception_pct") is not None:
                data["reported_since_inception_pct"] = last_record["reported_since_inception_pct"]

        supabase.table("portfolio_snapshots").upsert(
            data, on_conflict="snapshot_date,app_source"
        ).execute()

        print(f"✅ [Weekly Snapshot] {app_upper}: ฿{total_thb:,.2f} | WoW: ฿{wow_change_thb:,.2f} ({wow_return_pct:+.2f}%)")
    except Exception as e:
        print(f"⚠️ Failed to save weekly snapshot for {app_source}: {e}")

def run_weekly_snapshot():
    usd_rate = get_usd_thb_rate()
    db_res = supabase.table("user_portfolios").select("*").execute()
    latest_items = db_res.data or []

    all_apps = ["GPF", "DIME", "SCB", "MFC"]

    for app in all_apps:
        app_items = [
            i for i in latest_items
            if str(i.get("app_source", "")).strip().upper() == app
        ]

        if app == "DIME":
            total_usd = sum(float(i.get("current_value") or 0) for i in app_items)
            total_thb = total_usd * usd_rate
        else:
            total_thb = sum(float(i.get("current_value") or 0) for i in app_items)

        if total_thb > 0:
            save_weekly_snapshot(app, total_thb)

if __name__ == "__main__":
    run_weekly_snapshot()
