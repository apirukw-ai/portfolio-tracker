import os
from supabase import create_client, Client
import yfinance as yf

# 1. เชื่อมต่อ Supabase
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

def update_dime_stocks():
    # 2. ดึงเฉพาะรายการที่เป็นของแอป DIME
    response = supabase.table("user_portfolios").select("id, asset_name").ilike("app_source", "DIME").execute()
    portfolios = response.data

    for item in portfolios:
        ticker_symbol = item['asset_name']
        
        try:
            # 3. ดึงราคาประวัติย้อนหลัง 5 วันทำการจาก yfinance
            ticker = yf.Ticker(ticker_symbol)
            hist = ticker.history(period="5d")

            # ตรวจสอบว่ามีข้อมูลอย่างน้อย 2 วันทำการหรือไม่
            if len(hist) >= 2:
                current_price = float(hist['Close'].iloc[-1]) # ราคาปิดวันล่าสุด
                prev_price = float(hist['Close'].iloc[-2])    # ราคาปิดวันก่อนหน้า
                
                # 4. อัปเดตทั้ง current_nav และ prev_nav จาก Yahoo Finance โดยตรง
                supabase.table("user_portfolios").update({
                    "current_nav": round(current_price, 4),
                    "prev_nav": round(prev_price, 4)
                }).eq("id", item['id']).execute()

                print(f"✅ {ticker_symbol}: Current={current_price:.4f}, Prev={prev_price:.4f}")

        except Exception as e:
            print(f"❌ Error updating {ticker_symbol}: {e}")

if __name__ == "__main__":
    update_dime_stocks()
