import os
import re
from io import BytesIO
from pypdf import PdfReader
from supabase import Client, create_client

# ----------------------------------------------------
# 1. เชื่อมต่อ Supabase
# ----------------------------------------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Missing Supabase Credentials")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ----------------------------------------------------
# 2. ฟังก์ชัน แกะข้อมูลจาก PDF ใบยืนยันการซื้อขาย Dime
# ----------------------------------------------------
def parse_dime_pdf(pdf_bytes: bytes) -> dict:
    """
    อ่านไฟล์ PDF Confirmation Note ของ Dime และส่งคืนข้อมูลการซื้อขาย
    """
    reader = PdfReader(BytesIO(pdf_bytes))
    full_text = ""
    for page in reader.pages:
        full_text += page.extract_text() + "\n"

    # ทำการทำความสะอาด Text เพื่อป้องกันปัญหาเว้นวรรค/ขึ้นบรรทัดใหม่
    clean_text = re.sub(r'\s+', ' ', full_text)

    # 1. ดึงชื่อหลักทรัพย์ (Securities)
    sec_match = re.search(r'ชื่อหลักทรัพย์[^\n]*?Securities[^\n]*?([A-Z0-9\.\-]+)', full_text)
    asset_code = sec_match.group(1).strip() if sec_match else None

    # 2. ดึงประเภทรายการ (BUY / SELL)
    tx_match = re.search(r'ประเภท\s*รายการ[^\n]*?Transaction Type\s*(BUY|SELL)', full_text, re.IGNORECASE)
    tx_type = tx_match.group(1).upper() if tx_match else "BUY"

    # 3. ดึงจำนวนหน่วย (Unit)
    unit_match = re.search(r'จำนวนหน่วย\s*Unit\s*([\d\.\,]+)', full_text)
    units = float(unit_match.group(1).replace(',', '')) if unit_match else 0.0

    # 4. ดึงราคาต่อหน่วย (Unit Price)
    price_match = re.search(r'ราคาต่อหน่วย\s*Unit Price[^\n]*?([\d\.\,]+)', full_text)
    unit_price = float(price_match.group(1).replace(',', '')) if price_match else 0.0

    # 5. ดึงสกุลเงิน (Currency)
    curr_match = re.search(r'สกุลเงิน\s*Currency[^\n]*?(USD|THB)', full_text)
    currency = curr_match.group(1).strip() if curr_match else "USD"

    if not asset_code or units == 0 or unit_price == 0:
        raise ValueError("❌ ไม่สามารถอ่านข้อมูลหลักทรัพย์, จำนวนหน่วย หรือราคาจาก PDF ได้")

    return {
        "asset_code": asset_code,
        "transaction_type": tx_type,
        "units": units,
        "unit_price": unit_price,
        "currency": currency
    }

# ----------------------------------------------------
# 3. ฟังก์ชันคำนวณถัวเฉลี่ย และ อัปเดตลง user_portfolios
# ----------------------------------------------------
def process_dime_pdf_and_update(user_id: str, pdf_bytes: bytes):
    """
    อ่าน PDF Dime -> คำนวณ Unit และ Avg Cost ใหม่ -> บันทึกลง Supabase
    """
    try:
        parsed_data = parse_dime_pdf(pdf_bytes)
        asset_code = parsed_data["asset_code"]
        tx_type = parsed_data["transaction_type"]
        new_units = parsed_data["units"]
        new_price = parsed_data["unit_price"]

        print(f"📄 สแกนสำเร็จ: [{tx_type}] {asset_code} | จำนวน: {new_units} | ราคา: {new_price} {parsed_data['currency']}")

        # ดึงข้อมูลสินทรัพย์เดิมจาก Supabase
        res = supabase.table("user_portfolios") \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("app_source", "dime") \
            .eq("asset_code", asset_code) \
            .execute()

        portfolio_items = res.data or []

        if not portfolio_items:
            # กรณีเพิ่งเคยซื้อหุ้นตัวนี้เป็นครั้งแรกในพอร์ต
            if tx_type == "BUY":
                insert_data = {
                    "user_id": user_id,
                    "app_source": "dime",
                    "asset_code": asset_code,
                    "asset_name": asset_code,
                    "units": new_units,
                    "avg_cost": new_price,  # ราคาเริ่มต้น
                    "current_nav": new_price,
                    "current_value": new_units * new_price
                }
                supabase.table("user_portfolios").insert(insert_data).execute()
                print(f"✅ บันทึกหุ้นใหม่ {asset_code} เข้าพอร์ต DIME เรียบร้อย")
            return

        # สินทรัพย์มีอยู่แล้วในพอร์ต -> คำนวณถัวเฉลี่ย
        item = portfolio_items[0]
        item_id = item["id"]
        old_units = float(item.get("units") or 0)
        old_avg_cost = float(item.get("avg_cost") or item.get("current_nav") or 0)
        current_nav = float(item.get("current_nav") or new_price)

        if tx_type == "BUY":
            # คำนวณหน่วยรวมใหม่
            updated_units = old_units + new_units
            
            # คำนวณราคาต้นทุนเฉลี่ยถัวเฉลี่ย (Weighted Average Cost)
            total_cost = (old_units * old_avg_cost) + (new_units * new_price)
            updated_avg_cost = total_cost / updated_units if updated_units > 0 else 0

        elif tx_type == "SELL":
            # กรณีขาย หักหน่วยออก แต่ราคาต้นทุนเฉลี่ยต่อหน่วยคงเดิม
            updated_units = max(0.0, old_units - new_units)
            updated_avg_cost = old_avg_cost

        # อัปเดตข้อมูลกลับไปยัง Supabase
        update_payload = {
            "units": updated_units,
            "avg_cost": updated_avg_cost,
            "current_value": updated_units * current_nav
        }

        supabase.table("user_portfolios").update(update_payload).eq("id", item_id).execute()

        print(f"💾 อัปเดตพอร์ต {asset_code} สำเร็จ:")
        print(f"   • จำนวนหน่วย: {old_units:.6f} ➔ {updated_units:.6f}")
        print(f"   • ต้นทุนเฉลี่ย: {old_avg_cost:.4f} ➔ {updated_avg_cost:.4f}")

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการประมวลผล PDF: {e}")

# ----------------------------------------------------
# ตัวอย่างการใช้งาน
# ----------------------------------------------------
if __name__ == "__main__":
    # ทดสอบอ่านไฟล์ PDF
    pdf_file_path = "Dime_offshore_confirmationNote_DIMEOS20260909072261_unlocked.pdf"
    
    if os.path.exists(pdf_file_path):
        with open(pdf_file_path, "rb") as f:
            pdf_bytes = f.read()
            # ระบุ user_id ของผู้ใช้งานในระบบ
            process_dime_pdf_and_update(user_id="YOUR_USER_UUID", pdf_bytes=pdf_bytes)
