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
            return rate
    except Exception as e:
        print(f"⚠️ Exchange Rate Fetch Error: {e}")
    return 33.00

def save_weekly_snapshot(app_source, total_thb, auto_pnl_pct=None):
    try:
        today_str = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%d")
        app_upper = app_source.upper()

        # ดึง Snapshot สัปดาห์ล่าสุดเพื่อคำนวณเปรียบเทียบ WoW
        prev_res = (
            supabase.table("portfolio_snapshots")
            .select("*")
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

        # จัดการค่าผลตอบแทน (%)
        if auto_pnl_pct is not None:
            # DIME & SCB: อัปเดต % กำไร/ขาดทุนสะสมที่คำนวณได้ใหม่อัตโนมัติ
            data["reported_ytd_pct"] = round(auto_pnl_pct, 2)
        elif prev_res.data and len(prev_res.data) > 0:
            # MFC & GPF: คงค่าเดิมที่เคยกรอกไว้ใน DB
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

        print(f"✅ [Weekly Snapshot] {app_upper}: ฿{total_thb:,.2f} | WoW: {wow_return_pct:+.2f}%")
    except Exception as e:
        print(f"⚠️ Failed to save weekly snapshot for {app_source}: {e}")

def run_weekly_snapshot():
    # 1. ดึงข้อมูลจาก View v_app_allocation มาใช้เป็นหลัก
    try:
        alloc_res = supabase.table("v_app_allocation").select("*").execute()
        app_allocations = alloc_res.data or []
    except Exception as e:
        print(f"⚠️ Failed to fetch v_app_allocation: {e}")
        app_allocations = []

    all_apps = ["GPF", "DIME", "SCB", "MFC"]

    for app in all_apps:
        # หา data ของแอปนั้นๆ จาก view
        app_data = next((item for item in app_allocations if str(item.get("app_source", "")).upper() == app), None)

        if not app_data:
            print(f"⚠️ No data found for {app} in v_app_allocation")
            continue

        if app == "DIME":
            # DIME เก็บมูลค่าตั้งต้นเป็น USD ไว้ในฟิลด์ที่ชื่อลงท้ายด้วย _thb
            dime_usd_wealth = float(app_data.get("total_wealth_thb") or 0)
            dime_usd_cost = float(app_data.get("total_cost_thb") or 0)
            dime_fx_rate = float(app_data.get("fx_rate") or 33.0)

            # คำนวณยอดเงินบาทรวมโดยใช้ fx_rate ของแอปเอง
            total_thb = dime_usd_wealth * dime_fx_rate
            
            # คำนวณ PnL % จากต้นทุน USD
            auto_pnl = ((dime_usd_wealth - dime_usd_cost) / dime_usd_cost * 100) if dime_usd_cost > 0 else 0.0

            save_weekly_snapshot(app, total_thb, auto_pnl_pct=auto_pnl)

        elif app == "SCB":
            total_thb = float(app_data.get("total_wealth_thb") or 0)
            cost_thb = float(app_data.get("total_cost_thb") or 0)
            
            auto_pnl = ((total_thb - cost_thb) / cost_thb * 100) if cost_thb > 0 else 0.0
            save_weekly_snapshot(app, total_thb, auto_pnl_pct=auto_pnl)

        else: # GPF & MFC
            total_thb = float(app_data.get("total_wealth_thb") or 0)
            if total_thb > 0:
                save_weekly_snapshot(app, total_thb)

if __name__ == "__main__":
    run_weekly_snapshot()
