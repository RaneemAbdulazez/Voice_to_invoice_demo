import telebot
import cv2
import numpy as np
from pyzbar.pyzbar import decode
import io, os, sqlite3, time, re
from pydub import AudioSegment
from openai import OpenAI
from fpdf import FPDF
import json
from datetime import datetime

# --- 1. Configuration ---
TELEGRAM_TOKEN = "8297726717:AAGaP7JO32k5ei_z3zLmG5WZlAD6-Z7J2v4"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = OpenAI(api_key=OPENAI_API_KEY)

# Pricing: $60/hr inside, $90/hr outside. Tax is 13% HST.
RATES = {"inside": 60.0, "outside": 90.0}
TAX_RATE = 0.13
user_sessions = {}

# --- 2. Enhanced Extraction (The Brain) ---

def extract_data(text):
    """Triple-Check logic to ensure hours are NEVER ignored."""
    print(f"[DEBUG] Processing text: {text}")
    
    # Check 1: OpenAI (Natural Language)
    try:
        prompt = f"Extract hours (number) and location (inside/outside Windsor) from: '{text}'. Return ONLY JSON: {{\"hours\": 0.0, \"location\": \"string\"}}"
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            response_format={ "type": "json_object" },
            timeout=10
        )
        data = json.loads(response.choices[0].message.content)
        if data.get('hours') and data['hours'] > 0:
            print(f"[DEBUG] AI Success: {data}")
            return data
    except Exception as e:
        print(f"[DEBUG] AI Failed: {e}")

    # Check 2: Regex Backup (Looks for numbers and 'outside')
    hours_found = re.findall(r"(\d+\.?\d*)", text)
    if hours_found:
        hours = float(hours_found[0])
        location = "outside" if "outside" in text.lower() else "inside"
        print(f"[DEBUG] Regex Fallback: {hours} hrs, {location}")
        return {"hours": hours, "location": location}

    return None

# --- 3. Professional Invoice Generator ---

class ClientInvoice(FPDF):
    def header(self):
        self.set_fill_color(44, 62, 80) # Professional Navy
        self.rect(0, 0, 210, 35, 'F')
        self.set_font('Arial', 'B', 22)
        self.set_text_color(255, 255, 255)
        self.cell(0, 15, 'SERVICE INVOICE', 0, 1, 'L')
        self.set_font('Arial', '', 10)
        self.cell(0, -5, f"Invoice Date: {datetime.now().strftime('%Y-%m-%d')}", 0, 1, 'R')
        self.ln(20)

def generate_pdf(uid):
    s = user_sessions[uid]
    pdf = ClientInvoice()
    pdf.add_page()
    
    rate = RATES[s['location']]
    labor_sub = s['hours'] * rate
    parts_sub = sum(p['price'] for p in s['parts'])
    
    # Labor Table
    pdf.set_font('Arial', 'B', 12)
    pdf.set_fill_color(236, 240, 241)
    pdf.cell(0, 10, ' LABOR AND SERVICES', 0, 1, 'L', True)
    pdf.set_font('Arial', '', 11)
    pdf.cell(100, 10, f"Technical Service ({s['location'].title()} Windsor)", 1)
    pdf.cell(30, 10, f"{s['hours']} hrs", 1, 0, 'C')
    pdf.cell(30, 10, f"${rate}/hr", 1, 0, 'C')
    pdf.cell(30, 10, f"${labor_sub:.2f}", 1, 1, 'R')
    
    # Parts Table
    pdf.ln(5)
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 10, ' PARTS AND MATERIALS', 0, 1, 'L', True)
    pdf.set_font('Arial', '', 11)
    for p in s['parts']:
        pdf.cell(160, 10, f" {p['name']} ({p['sku']})", 1)
        pdf.cell(30, 10, f"${p['price']:.2f}", 1, 1, 'R')
    
    # Calculations
    # Total = (Hours * Rate + Sum(Parts)) * (1 + Tax)
    subtotal = labor_sub + parts_sub
    tax = subtotal * TAX_RATE
    total = subtotal + tax
    
    pdf.ln(10)
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(160, 8, 'Subtotal:', 0, 0, 'R')
    pdf.cell(30, 8, f"${subtotal:.2f}", 0, 1, 'R')
    pdf.cell(160, 8, f'HST ({int(TAX_RATE*100)}%):', 0, 0, 'R')
    pdf.cell(30, 8, f"${tax:.2f}", 0, 1, 'R')
    
    pdf.set_font('Arial', 'B', 14)
    pdf.set_text_color(41, 128, 185) # Corporate Blue
    pdf.cell(160, 15, 'TOTAL DUE (CAD):', 0, 0, 'R')
    pdf.cell(30, 15, f"${total:.2f}", 0, 1, 'R')

    path = f"Invoice_{uid}.pdf"
    pdf.output(path)
    return path

# --- 4. Handlers ---

@bot.message_handler(commands=['start', 'reset', 'status'])
def status_check(message):
    uid = message.chat.id
    if uid not in user_sessions or message.text == '/reset':
        user_sessions[uid] = {'hours': 0.0, 'location': 'inside', 'parts': []}
        bot.reply_to(message, "🔄 Session Reset. Send work hours/location to begin.")
    else:
        s = user_sessions[uid]
        bot.reply_to(message, f"📊 **Current Session Status:**\n- Hours: {s['hours']}\n- Location: {s['location']}\n- Parts Scanned: {len(s['parts'])}\n\nType 'Finish' to generate PDF.")

@bot.message_handler(func=lambda m: m.text and m.text.lower() == 'finish')
def handle_finish(message):
    uid = message.chat.id
    session = user_sessions.get(uid, {'hours': 0})
    if session['hours'] <= 0:
        bot.reply_to(message, "⚠️ Wait! I still don't have your work hours. Please say something like 'I worked 5 hours outside' before finishing.")
        return
    
    bot.send_message(uid, "📄 **Creating your official invoice...**")
    path = generate_pdf(uid)
    with open(path, 'rb') as f:
        bot.send_document(uid, f, caption="Invoice ready! ✅")
    os.remove(path)
    user_sessions[uid] = {'hours': 0.0, 'location': 'inside', 'parts': []}

@bot.message_handler(content_types=['text', 'voice'])
def handle_info(message):
    uid = message.chat.id
    if uid not in user_sessions: status_check(message)
    if message.text and message.text.lower() == 'finish': return

    bot.send_chat_action(uid, 'typing')
    text = message.text
    
    if message.content_type == 'voice':
        file_info = bot.get_file(message.voice.file_id)
        downloaded = bot.download_file(file_info.file_path)
        with open("v.oga", "wb") as f: f.write(downloaded)
        AudioSegment.from_file("v.oga").export("v.mp3", format="mp3")
        with open("v.mp3", "rb") as af:
            text = client.audio.transcriptions.create(model="whisper-1", file=af).text
        os.remove("v.oga"); os.remove("v.mp3")

    data = extract_data(text)
    if data:
        user_sessions[uid].update(data)
        bot.reply_to(message, f"✅ **Acknowledged!**\nI've recorded **{data['hours']} hours** at **{data['location']} Windsor** rates. Anything else?")
    else:
        bot.reply_to(message, "❓ I heard you, but I couldn't find a specific number of hours. Please try saying: 'I worked 5 hours'.")

@bot.message_handler(content_types=['photo'])
def handle_scan(message):
    uid = message.chat.id
    if uid not in user_sessions: status_check(message)
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    nparr = np.frombuffer(downloaded, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
    codes = decode(img)
    
    if codes:
        barcode_val = codes[0].data.decode('utf-8')
        conn = sqlite3.connect('inventory.db')
        cursor = conn.cursor()
        cursor.execute("SELECT name, sku, price FROM products WHERE barcode_data = ?", (barcode_val,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            part = {"name": row[0], "sku": row[1], "price": row[2]}
            user_sessions[uid]['parts'].append(part)
            bot.reply_to(message, f"📦 **Part Added:** {part['name']} (${part['price']})")
        else: bot.reply_to(message, f"❌ Barcode {barcode_val} not in DB.")
    else: bot.reply_to(message, "🔍 No barcode detected.")

if __name__ == "__main__":
    while True:
        try:
            bot.infinity_polling(timeout=20)
        except:
            time.sleep(5)