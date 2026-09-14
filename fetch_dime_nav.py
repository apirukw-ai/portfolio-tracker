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
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        print(f"⚠️ Exchange Rate Fetch Error: {e}")
    return 33.00

def get_us_stock_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        # ล็อกเป้าดึงเฉพาะราคาในเวลาทำการปกติ (Regular Market) 
        # เพื่อหลีกเลี่ยงราคาช่วง After-hours ที่ทำให้ทศนิยมเพี้ยน
        current_price = info.get('regularMarketPrice')
        prev_close = info.get('regularMarketPreviousClose')
        
        # Fallback สำรองเผื่อหา key ด้านบนไม่เจอ
        if current_price is None:
            current_price = info.get('currentPrice')
        if prev_close is None:
            prev_close = info.get('previousClose')
            
        if current_price is not None and prev_close is not None:
            return round(float(current_price), 4), round(float(prev_close), 4)
            
    except Exception as e:
        print(f"⚠️ yfinance Error [{symbol}]: {e}")
        
    return None, None

def run_dime_update():
    thai_tz = timezone(timedelta(hours=7))
    now_thai_dt = datetime.now(thai_tz)
    now_thai = now_thai_dt.strftime("%Y-%m-%dT%H:%M:%S+07:00")
    today_date_str = now_thai_dt.strftime("%d/%m/%Y")

    usd_rate = get_usd_thb_rate()
    print(f"💵 อัตราแลกเปลี่ยน USD/THB ปัจจุบัน: {usd_rate:.4f}")

    db_res = supabase.table("user_portfolios").select("*").ilike("app_source", "DIME").execute()
    dime_items = db_res.data or []

    print(f"📦 พบรายการ DIME ในระบบ {len(dime_items)} รายการ")

    for item in dime_items:
        item_id = item["id"]
        code = item.get("asset_code", "").strip()
        units = float(item.get("units") or 0)

        latest_nav, latest_prev_nav = get_us_stock_price(code)

        if latest_nav and latest_nav > 0:
            current_value_usd = round(units * latest_nav, 4)
            
            update_payload = {
                "current_nav": round(latest_nav, 4),
                "current_value": current_value_usd,
                "nav_date": today_date_str,
                "updated_at": now_thai
            }
            
            if latest_prev_nav and latest_prev_nav > 0:
                update_payload["prev_nav"] = round(latest_prev_nav, 4)

            supabase.table("user_portfolios").update(update_payload).eq("id", item_id).execute()
            print(f" ✅ [DIME] {code}: Price=${latest_nav:.2f} | Value=${current_value_usd:.2f} (฿{current_value_usd * usd_rate:,.2f})")

if __name__ == "__main__":
    run_dime_update()
