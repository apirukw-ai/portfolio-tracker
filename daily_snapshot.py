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
    
    # Fallback rate if yfinance is down
    return 33.00 

def save_daily_snapshot(app_source, total_thb):
    try:
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

        # Persist historical percentages if they exist
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

    # Dynamically extract all unique apps present in the portfolio table
    all_apps = {str(i.get("app_source", "")).strip().upper() for i in latest_items if i.get("app_source")}

    for app in all_apps:
        app_items = [
            i for i in latest_items 
            if str(i.get("app_source", "")).strip().upper() == app
        ]

        # Calculate totals
        if app == "DIME":
            # DIME is stored in USD, so we convert to THB
            total_usd = sum(float(i.get("current_value") or 0) for i in app_items)
            total_thb = total_usd * usd_rate
        else:
            total_thb = sum(float(i.get("current_value") or 0) for i in app_items)

        if total_thb > 0:
            save_daily_snapshot(app, total_thb)

if __name__ == "__main__":
    run_snapshot_process()