import os
import re
import asyncio
import urllib3
import requests
from bs4 import BeautifulSoup
from flask import Flask
from threading import Thread

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==============================
# FLASK WEB SERVER (FOR KEEP-ALIVE)
# ==============================
app = Flask('')

@app.route('/')
def home():
    return "HSC Rescrutiny Scanner is Online!"

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
async def process_student_results(update_or_query, data_list):
    msg_source = update_or_query.message if hasattr(update_or_query, 'message') else update_or_query
    final_output = "🏦 <b>Sonali Bank - HSC Rescrutiny Result</b>\n\n"
    phones = []

    for i, data in enumerate(data_list, 1):
        final_output += (
            f"🎯 Result {i}\n"
            f"<pre>"
            f"🆔 Transaction Id: {data['id']}\n"
            f"👤 Student Name : {data['name']}\n"
            f"🔢 Roll         : {data['roll']}\n"
            f"🏫 Board        : {data['board']}\n"
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
# SCANNER LOGIC
# ==============================
async def run_search(update_or_query, context, s_r, e_r):
    global current_search_id
    this_id = current_search_id 
    
    msg_source = update_or_query.message if hasattr(update_or_query, 'message') else update_or_query
    status_msg = await msg_source.reply_text("⏳ <b>Scanning...</b>", parse_mode="HTML")
    context.user_data["current_end"] = e_r
    found_students = 0
    total_range = e_r - s_r + 1
    
    for i, roll in enumerate(range(s_r, e_r + 1), 1):
        if this_id != current_search_id:
            return 

        try:
            search_url = f"{SEARCH_URL}?searchStr={roll}"
            r = session.get(search_url, headers=headers, timeout=12, verify=False)
            ids = re.findall(r'/BoardRescrutiny/Home/Voucher/([A-Za-z0-9_-]+)', r.text, re.I)
            
            if ids:
                v_list = []
                for tid in set(ids):
                    d = get_data(tid)
                    if d and d["name"] != "N/A":
                        v_list.append(d)
                if v_list:
                    found_students += 1
                    await process_student_results(update_or_query, v_list)

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
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👉 Next 500?", callback_data="next_500")]])
    )


# ==============================
# BOT HANDLERS
# ==============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_search_id
    current_search_id += 1 
    await update.message.reply_text(
        "🏦 <b>HSC Rescrutiny Fee Scanner</b>\n\n"
        "রোল নম্বর পাঠিয়ে সার্চ করুন।",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Start Search", callback_data="btn_ready")]])
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_search_id
    t = update.message.text.strip()
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

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_search_id
    query = update.callback_query
    await query.answer()
    
    if query.data == "btn_ready":
        current_search_id += 1
        await query.message.reply_text("🚀 রোল বা রেঞ্জ পাঠান (উদা: <code>800001</code> অথবা <code>800001-800050</code>)", parse_mode="HTML")
    elif query.data == "next_500":
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
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("🤖 Scanner Bot is running...")
    application.run_polling(drop_pending_updates=True)
