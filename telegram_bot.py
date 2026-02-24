import telebot
from telebot import types
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
OPENAI_API_KEY = "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"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = OpenAI(api_key=OPENAI_API_KEY)

RATES = {"inside": 60.0, "outside": 90.0}
TAX_RATE = 0.13
user_sessions = {}

# --- 2. Jobs Data ---
AVAILABLE_JOBS = [
    {"id": "J-8801", "desc": "Emergency Leak Repair", "street": "Riverside Drive"},
    {"id": "J-8802", "desc": "Water Heater Installation", "street": "Ouellette Ave"},
    {"id": "J-8803", "desc": "Bathroom Faucet Replacement", "street": "Tecumseh Road"},
    {"id": "J-8804", "desc": "Main Line Cleaning", "street": "Walker Road"},
    {"id": "J-8805", "desc": "Kitchen Sink Unclogging", "street": "Wyandotte St"}
]

# --- 3. Database & PDF Classes ---
def init_db():
    conn = sqlite3.connect('inventory.db')
    cursor = conn.cursor()
    cursor.execute('DROP TABLE IF EXISTS products')
    cursor.execute('''CREATE TABLE products (id INTEGER PRIMARY KEY, barcode_data TEXT UNIQUE, name TEXT, sku TEXT, price REAL)''')
    
    plumbing_items = [
        ("PRODUCT-001", "Copper Pipe 1/2 inch", "CP-001", 25.00),
        ("PRODUCT-002", "PEX Tee Connector", "PT-002", 5.50),
        ("PRODUCT-003", "PVC Sweep Elbow", "PS-003", 8.25),
        ("PRODUCT-004", "Kitchen Sink Drain Kit", "KS-004", 45.00),
        ("PRODUCT-005", "Shut-off Ball Valve", "SB-005", 15.75),
        ("PRODUCT-006", "Thread Sealant Tape", "TT-006", 2.50),
        ("PRODUCT-007", "Adjustable Pipe Wrench", "AW-007", 35.00),
        ("PRODUCT-008", "Toilet Wax Ring", "TW-008", 12.00),
        ("PRODUCT-009", "Braided Stainless Hose", "BH-009", 18.50),
        ("PRODUCT-010", "Shower Valve Cartridge", "SV-010", 65.00)
    ]
    cursor.executemany("INSERT INTO products (barcode_data, name, sku, price) VALUES (?,?,?,?)", plumbing_items)
    conn.commit()
    conn.close()

class ProfessionalInvoice(FPDF):
    def header(self):
        self.set_fill_color(44, 62, 80) 
        self.rect(0, 0, 210, 40, 'F')
        self.set_font('Arial', 'B', 22)
        self.set_text_color(255, 255, 255)
        self.cell(0, 20, 'PLUMBING SERVICE INVOICE', 0, 1, 'L')
        self.ln(25)
    def section_title(self, label):
        self.set_fill_color(235, 235, 235)
        self.set_font('Arial', 'B', 12)
        self.set_text_color(0, 0, 0)
        self.cell(0, 10, f" {label}", 0, 1, 'L', True)
        self.ln(2)

# --- 4. Core Logic Functions ---
def extract_and_polish(text):
    try:
        prompt = (f"Analyze: '{text}'. Extract hours worked, Location (inside/outside Windsor), and a professional technical summary. "
                  "Return JSON: {'hours': 0.0, 'location': 'inside/outside', 'description': 'string'}")
        response = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except: return None

def get_main_menu():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(types.KeyboardButton('📋 View Jobs'), types.KeyboardButton('🏁 Finish'))
    return markup

def add_pending_to_session(session):
    """Adds the pending part with quantity 1 if the user skipped the buttons."""
    if session.get('pending_part'):
        p = session['pending_part']
        session['parts'].append({"name": p['name'], "price": p['price'], "qty": 1})
        session['pending_part'] = None

# --- 5. Message Handlers ---

@bot.message_handler(commands=['start', 'reset'])
def reset_session(message):
    uid = message.chat.id
    user_sessions[uid] = {
        'hours': 0.0, 'location': 'inside', 'parts': [], 
        'state': 'WAITING_JOB', 'description': '', 
        'current_job': None, 'pending_part': None,
        'completed_job_ids': user_sessions.get(uid, {}).get('completed_job_ids', [])
    }
    bot.send_message(uid, "🛠 **Plumber Portal Active.**", reply_markup=get_main_menu())

@bot.message_handler(func=lambda m: m.text == '📋 View Jobs')
def show_jobs(message):
    uid = message.chat.id
    if uid not in user_sessions: reset_session(message)
    active_jobs = [j for j in AVAILABLE_JOBS if j['id'] not in user_sessions[uid]['completed_job_ids']]
    
    if not active_jobs:
        bot.reply_to(message, "✅ All jobs completed! Use /reset to clear history.")
        return

    markup = types.InlineKeyboardMarkup()
    for job in active_jobs:
        markup.add(types.InlineKeyboardButton(text=f"{job['id']} | {job['street']}", callback_data=f"job_{job['id']}"))
    bot.send_message(uid, "📂 **Available Jobs:**", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('job_'))
def handle_job_selection(call):
    uid = call.message.chat.id
    job_id = call.data.replace('job_', '')
    job_details = next((j for j in AVAILABLE_JOBS if j['id'] == job_id), None)
    
    if job_details:
        user_sessions[uid].update({'current_job': job_details, 'state': 'WAITING_WORK'})
        user_sessions[uid]['completed_job_ids'].append(job_id)
        bot.edit_message_text(f"🏗 **Job Selected:** {job_id}\n📍 **Street:** {job_details['street']}\n\n**Next:** Send voice/text with your hours.", uid, call.message.message_id)

@bot.message_handler(content_types=['text', 'voice'])
def handle_input(message):
    uid = message.chat.id
    if uid not in user_sessions: reset_session(message)
    session = user_sessions[uid]

    if message.text == '🏁 Finish' or (message.text and message.text.lower() == 'finish'):
        finalize_invoice(message)
        return

    if session['state'] == 'WAITING_JOB':
        bot.reply_to(message, "⚠️ Select a job first using 'View Jobs'.")
        return

    if session['state'] == 'CONFIRMING' and message.text:
        if "yes" in message.text.lower() or "correct" in message.text.lower():
            session['state'] = 'SCANNING'
            bot.reply_to(message, "✅ **Confirmed.** Now, scan barcodes (Send Photos).")
        else:
            session['state'] = 'WAITING_WORK'
            bot.reply_to(message, "❌ **Entry Denied.** Please record hours again.")
        return

    if session['state'] == 'WAITING_WORK':
        incoming_text = message.text
        if message.content_type == 'voice':
            bot.send_chat_action(uid, 'typing')
            file_info = bot.get_file(message.voice.file_id)
            downloaded = bot.download_file(file_info.file_path)
            with open("temp.oga", "wb") as f: f.write(downloaded)
            AudioSegment.from_file("temp.oga").export("temp.mp3", format="mp3")
            with open("temp.mp3", "rb") as audio_file:
                incoming_text = client.audio.transcriptions.create(model="whisper-1", file=audio_file).text
            os.remove("temp.oga"); os.remove("temp.mp3")

        data = extract_and_polish(incoming_text)
        if data:
            session.update(data)
            session['state'] = 'CONFIRMING'
            bot.reply_to(message, f"🔍 **Verification:**\n🕒 Hours: {data['hours']}\n📍 Loc: {data['location']}\n📝 Note: {data['description']}\n\nIs this correct? (Yes/No)")

@bot.message_handler(content_types=['photo'])
def handle_barcode(message):
    uid = message.chat.id
    session = user_sessions.get(uid)
    if not session or session['state'] != 'SCANNING':
        bot.reply_to(message, "⚠️ Confirm hours before scanning parts!")
        return

    # If there was a previous part without qty, default it to 1
    add_pending_to_session(session)

    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    nparr = np.frombuffer(downloaded, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
    detected_codes = decode(img)
    
    if detected_codes:
        barcode_val = detected_codes[0].data.decode('utf-8')
        conn = sqlite3.connect('inventory.db')
        row = conn.execute("SELECT name, price FROM products WHERE barcode_data=?", (barcode_val,)).fetchone()
        conn.close()
        
        if row:
            session['pending_part'] = {"name": row[0], "price": row[1]}
            # Quantity Buttons 1-10
            markup = types.InlineKeyboardMarkup(row_width=5)
            row1 = [types.InlineKeyboardButton(text=str(i), callback_data=f"qty_{i}") for i in range(1, 6)]
            row2 = [types.InlineKeyboardButton(text=str(i), callback_data=f"qty_{i}") for i in range(6, 11)]
            markup.add(*row1)
            markup.add(*row2)
            bot.send_message(uid, f"📦 **Found:** {row[0]}\nSelect Quantity:", reply_markup=markup)
        else:
            bot.reply_to(message, f"❌ **Not Found:** `{barcode_val}`")
    else:
        bot.reply_to(message, "🔍 No barcode detected.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('qty_'))
def handle_quantity(call):
    uid = call.message.chat.id
    session = user_sessions.get(uid)
    qty = int(call.data.replace('qty_', ''))
    
    if session and session['pending_part']:
        p = session['pending_part']
        session['parts'].append({"name": p['name'], "price": p['price'], "qty": qty})
        session['pending_part'] = None
        bot.edit_message_text(f"✅ Added {qty}x {p['name']}\nScan next or click 'Finish'.", uid, call.message.message_id)

def finalize_invoice(message):
    uid = message.chat.id
    session = user_sessions.get(uid)
    
    # Check for any last part that didn't get a qty click
    add_pending_to_session(session)

    if not session or session['hours'] <= 0:
        bot.reply_to(message, "⚠️ No data to bill.")
        return

    rate = RATES.get(session['location'], 60.0)
    l_total = session['hours'] * rate
    p_total = sum(p['price'] * p['qty'] for p in session['parts'])
    sub = l_total + p_total
    tax, grand = (sub * TAX_RATE), (sub * (1 + TAX_RATE))

    pdf = ProfessionalInvoice()
    pdf.add_page()
    pdf.section_title(f"JOB: {session['current_job']['id'] if session['current_job'] else 'N/A'}")
    pdf.set_font('Arial', '', 11)
    pdf.multi_cell(0, 7, f"Description: {session['description']}\nStreet: {session['current_job']['street'] if session['current_job'] else 'N/A'}")
    
    pdf.ln(5); pdf.set_font('Arial', 'B', 10)
    pdf.cell(100, 10, "Service", 1); pdf.cell(30, 10, "Hours", 1, 0, 'C'); pdf.cell(60, 10, "Total", 1, 1, 'R')
    pdf.set_font('Arial', '', 10)
    pdf.cell(100, 10, f"Labor ({session['location']})", 1); pdf.cell(30, 10, f"{session['hours']}", 1, 0, 'C'); pdf.cell(60, 10, f"${l_total:.2f}", 1, 1, 'R')
    
    if session['parts']:
        pdf.ln(5); pdf.section_title("MATERIALS")
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(90, 10, "Item", 1); pdf.cell(20, 10, "Qty", 1, 0, 'C'); pdf.cell(40, 10, "Price", 1, 0, 'R'); pdf.cell(40, 10, "Total", 1, 1, 'R')
        pdf.set_font('Arial', '', 10)
        for p in session['parts']:
            pdf.cell(90, 10, p['name'], 1); pdf.cell(20, 10, str(p['qty']), 1, 0, 'C'); pdf.cell(40, 10, f"${p['price']:.2f}", 1, 0, 'R'); pdf.cell(40, 10, f"${p['price']*p['qty']:.2f}", 1, 1, 'R')

    pdf.ln(10); pdf.set_font('Arial', 'B', 12)
    pdf.cell(130, 10, "TOTAL DUE (CAD):", 0, 0, 'R'); pdf.cell(60, 10, f"${grand:.2f}", 0, 1, 'R')

    fname = f"Invoice_{uid}.pdf"
    pdf.output(fname)
    with open(fname, 'rb') as f: bot.send_document(uid, f, caption="Invoice generated successfully. ✅")
    os.remove(fname)
    reset_session(message)

if __name__ == "__main__":
    init_db()
    print("🚀 Plumber Bot v2.0 (Quantity Edition) Online...")
    bot.remove_webhook()
    bot.infinity_polling()