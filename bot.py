import os
import re
import asyncio
import urllib3
import requests
from bs4 import BeautifulSoup
from flask import Flask
from threading import Thread

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==============================
# FLASK WEB SERVER (FOR KEEP-ALIVE)
# ==============================
app = Flask('')

@app.route('/')
def home():
    return "Rescrutiny Scanner Bot is Online!"

def run():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()


# ==============================
# BOT & CONFIGURATION
# ==============================
BOT_TOKEN = "9036729577:AAEVuw-tlO8fDNloA47HDPIigZZGJqM0uPg"

BASE_URL = "https://billpay.sonalibank.com.bd"
SEARCH_URL = BASE_URL + "/BoardRescrutiny/Home/Search"
VOUCHER_URL = BASE_URL + "/BoardRescrutiny/Home/Voucher/"

session = requests.Session()
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; K) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0.0.0 Mobile Safari/537.36"
    ),
    "Referer": BASE_URL + "/BoardRescrutiny/Home/Search"
}

# কনভারসেশন স্টেটস
SELECTING_BOARD, GETTING_INSTITUTION, GETTING_ROLL = range(3)

# শিক্ষা বোর্ডের তালিকা
BOARDS = [
    "Dhaka Board", "Barisal Board", "Chattogram Board", 
    "Comilla Board", "Dinajpur Board", "Jessore Board", 
    "Mymensingh Board", "Rajshahi Board", "Sylhet Board", 
    "Madrasah Board", "BTEB"
]

# স্টপ সিস্টেম ট্র্যাকিং আইডি
current_search_id = 0


# ==============================
# DATA EXTRACTION
# ==============================
def get_data(tid):
    url = f"{VOUCHER_URL}{tid}"
    try:
        r = session.get(url, headers=headers, timeout=15, verify=False)
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(" ", strip=True)

        d = {
            "id": tid,
            "date": "N/A",
            "name": "N/A",
            "contact": "N/A",
            "roll": "N/A",
            "board": "N/A",
            "year": "N/A",
            "amount": "0.00"
        }

        txn_match = re.search(r"Transaction\s*Id\s*[:\-]?\s*([A-Za-z0-9]+)", text, re.I)
        if txn_match: d["id"] = txn_match.group(1)

        date_match = re.search(r"Date\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})", text, re.I)
        if date_match: d["date"] = date_match.group(1)

        name_match = re.search(r"Name\s*[:\-]?\s*([A-Za-z.\s]+?)(?=\s+Roll|\s+Board|\s+Year)", text, re.I)
        if name_match: d["name"] = name_match.group(1).strip()

        roll_match = re.search(r"Roll\s*[:\-]?\s*(\d+)", text, re.I)
        if roll_match: d["roll"] = roll_match.group(1)

        board_match = re.search(r"Board\s*[:\-]?\s*([A-Za-z]+)", text, re.I)
        if board_match: d["board"] = board_match.group(1)

        year_match = re.search(r"Year\s*[:\-]?\s*(\d{4})", text, re.I)
        if year_match: d["year"] = year_match.group(1)

        mobile_match = re.search(r"(?:Mobile|Mobile\s*No|Phone)\s*[:\-]?\s*(01\d{9})", text, re.I)
        if mobile_match: d["contact"] = mobile_match.group(1)

        amount_match = re.search(r"Fee\s*Amount\s*(?:\(BDT\))?\s*[:\-]?\s*([\d,]+(?:\.\d{1,2})?)", text, re.I)
        if amount_match: d["amount"] = amount_match.group(1)

        return d
    except Exception:
        return None


# ==============================
# RESULT MESSAGE & BUTTONS
# ==============================
async def process_student_results(update_or_query, data_list, institution_name):
    msg_source = update_or_query.message if hasattr(update_or_query, 'message') else update_or_query
    final_output = "🏦 <b>Sonali Bank - Rescrutiny Result</b>\n\n"
    phones = []

    for i, data in enumerate(data_list, 1):
        final_output += (
            f"🎯 Result {i}\n"
            f"<pre>"
            f"🆔 Transaction Id: {data['id']}\n"
            f"👤 Student Name : {data['name']}\n"
            f"🔢 Roll         : {data['roll']}\n"
            f"🏫 Board        : {data['board']}\n"
            f"🏫 Institute    : {institution_name}\n"
            f"📆 Year         : {data['year']}\n"
            f"📳 Mobile No    : {data['contact']}\n"
            f"💰 Fee Amount   : {data['amount']} BDT\n"
            f"📅 Date         : {data['date']}"
            f"</pre>\n\n"
        )
        p = data["contact"].strip()[-11:]
        if len(p) >= 11 and p.isdigit() and p not in phones:
            phones.append(p)

    keyboard = []
    for ph in phones:
        keyboard.append([
            InlineKeyboardButton("🟢 WhatsApp", url=f"https://wa.me/88{ph}"),
            InlineKeyboardButton("🔵 Telegram", url=f"https://t.me/+88{ph}")
        ])

    await msg_source.reply_text(
        final_output,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )


# ==============================
# SCANNER LOGIC (WITH PROPER BOARD FILTER)
# ==============================
async def run_search(update_or_query, context, s_r, e_r):
    global current_search_id
    this_id = current_search_id 
    
    msg_source = update_or_query.message if hasattr(update_or_query, 'message') else update_or_query
    status_msg = await msg_source.reply_text("⏳ <b>Scanning...</b>", parse_mode="HTML")
    context.user_data["current_end"] = e_r
    
    selected_board_full = context.user_data.get("selected_board", "").upper()
    selected_board_keyword = selected_board_full.split()[0] if selected_board_full else ""
    institution_name = context.user_data.get("institution_name", "N/A")
    
    found_students = 0
    total_range = e_r - s_r + 1
    
    for i, roll in enumerate(range(s_r, e_r + 1), 1):
        if this_id != current_search_id:
            return 

        try:
            if i == 1:
                session.get(BASE_URL + "/BoardRescrutiny/Home/Search", headers=headers, verify=False)
            
            search_url = f"{SEARCH_URL}?searchStr={roll}"
            r = session.get(search_url, headers=headers, timeout=12, verify=False)
            ids = re.findall(r'/BoardRescrutiny/Home/Voucher/([A-Za-z0-9_-]+)', r.text, re.I)
            
            if ids:
                v_list = []
                for tid in set(ids):
                    d = get_data(tid)
                    if d and d["name"] != "N/A":
                        server_board = d["board"].upper()
                        if not server_board or server_board == "N/A" or selected_board_keyword in server_board or server_board in selected_board_keyword:
                            v_list.append(d)
                if v_list:
                    found_students += 1
                    await process_student_results(update_or_query, v_list, institution_name)

            if i % 5 == 0 or i == total_range:
                await status_msg.edit_text(
                    f"⏳ <b>Processing</b>\n🔢 Roll: <code>{roll}</code>\n📊 Found: <b>{found_students}</b>\n✅ Progress: {i}/{total_range}",
                    parse_mode="HTML"
                )
            await asyncio.sleep(0.1)
        except Exception:
            continue

    try:
        await status_msg.delete()
    except Exception:
        pass

    await msg_source.reply_text(
        f"✅ Done!\n📊 Found Students: {found_students}", 
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👉 Next 500?", callback_data="next_500")]]))


# ==============================
# BOT CONVERSATION & HANDLERS
# ==============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_search_id
    current_search_id += 1 
    
    keyboard = []
    for board in BOARDS:
        keyboard.append([InlineKeyboardButton(board, callback_data=f"board_{board}")])
    
    await update.message.reply_text(
        "🏦 <b>Rescrutiny Fee Scanner Bot</b>\n\nদয়া করে নিচের তালিকা থেকে আপনার শিক্ষা বোর্ডটি সিলেক্ট করুন:", 
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SELECTING_BOARD

async def board_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    board_name = query.data.split("_", 1)[1]
    context.user_data["selected_board"] = board_name
    
    reply_kb = ReplyKeyboardMarkup([[KeyboardButton("🏫 Institute Name")]], resize_keyboard=True)
    await query.message.reply_text(
        f"আপনি সিলেক্ট করেছেন: <b>{board_name}</b>\n\nএখন নতুন ইনস্টিটিউটের নাম দিতে চাইলে নিচের <b>'🏫 Institute Name'</b> বাটনে ক্লিক করুন অথবা সরাসরি নাম টাইপ করুন:",
        parse_mode="HTML",
        reply_markup=reply_kb
    )
    return GETTING_INSTITUTION

async def get_institution(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text == "🏫 Institute Name":
        await update.message.reply_text("দয়া করে নতুন **ইনস্টিটিউশনের নাম (Institution Name)** ম্যানুয়ালি টাইপ করে পাঠান:", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
        return GETTING_INSTITUTION
    
    context.user_data["institution_name"] = text
    reply_kb = ReplyKeyboardMarkup([[KeyboardButton("🏫 Institute Name")]], resize_keyboard=True)
    
    await update.message.reply_text(
        f"ইনস্টিটিউশনের নাম সংরক্ষিত হয়েছে: <b>{text}</b>\n\nএখন শিক্ষার্থীর রোল নম্বর বা রোল রেঞ্জ দিন (উদা: <code>800001</code> অথবা <code>800001-800010</code>):",
        parse_mode="HTML",
        reply_markup=reply_kb
    )
    return GETTING_ROLL

async def handle_roll_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_search_id
    t = update.message.text.strip()
    
    if t == "🏫 Institute Name":
        await update.message.reply_text("দয়া করে নতুন **ইনস্টিটিউশনের নাম (Institution Name)** ম্যানুয়ালি টাইপ করে পাঠান:", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
        return GETTING_INSTITUTION

    current_search_id += 1 
    try:
        if "-" in t:
            s, e = map(int, t.split("-"))
            await run_search(update, context, s, e)
        elif t.isdigit():
            await run_search(update, context, int(t), int(t))
        else:
            await update.message.reply_text("❌ সঠিক রোল বা রেঞ্জ দিন।\nউদাহরণ: <code>800001</code> অথবা <code>800001-800010</code>", parse_mode="HTML")
    except Exception:
        pass
    return GETTING_ROLL

async def next_500_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_search_id
    query = update.callback_query
    await query.answer()
    if query.data == "next_500":
        current_search_id += 1
        last_end = context.user_data.get("current_end", 0)
        await run_search(query, context, last_end + 1, last_end + 500)


# ==============================
# MAIN RUNNER
# ==============================
if __name__ == "__main__":
    keep_alive()
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .build()
    )
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECTING_BOARD: [CallbackQueryHandler(board_selected, pattern="^board_")],
            GETTING_INSTITUTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_institution)],
            GETTING_ROLL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_roll_input)]
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(next_500_callback, pattern="^next_500$"))
    
    print("🤖 Scanner Bot is running...")
    application.run_polling(drop_pending_updates=True)
