import os
from datetime import datetime, timedelta, timezone
from supabase import Client, create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Missing Supabase Credentials")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def save_daily_snapshot(app_source, total_thb):
    try:
        today_str = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%d")
        app_upper = app_source.upper()

        # ดึงค่า % ผลตอบแทนเดิมมาสืบทอดป้องกัน NULL
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

        print(f"✅ [Snapshot] {app_upper}: ฿{total_thb:,.2f}")
    except Exception as e:
        print(f"⚠️ Failed to save snapshot for {app_source}: {e}")

def run_snapshot_process():
    db_res = supabase.table("user_portfolios").select("*").execute()
    latest_items = db_res.data or []

    all_apps = ["GPF", "DIME", "SCB", "MFC"]

    for app in all_apps:
        app_items = [
            i for i in latest_items
            if str(i.get("app_source", "")).strip().upper() == app
        ]

        total_thb = sum(float(i.get("current_value") or 0) for i in app_items)

        if total_thb > 0:
            save_daily_snapshot(app, total_thb)

if __name__ == "__main__":
    run_snapshot_process()