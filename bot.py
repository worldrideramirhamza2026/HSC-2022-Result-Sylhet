import os
import re
import time
import asyncio
import logging
import threading
import urllib3
import requests

from bs4 import BeautifulSoup
from flask import Flask
from html import escape

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove
)

from telegram.constants import ParseMode

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =====================================================
# FLASK WEB SERVER (FOR KEEP-ALIVE)
# =====================================================
app = Flask('')

@app.route('/')
def home():
    return "Combined Recheck Scanner Bot is Online!"

@app.route('/health')
def health():
    return {"status": "online"}

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

def keep_alive():
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()


# =====================================================
# CONFIGURATIONS & TOKENS
# =====================================================
BOT_TOKEN = "9036729577:AAEVuw-tlO8fDNloA47HDPIigZZGJqM0uPg"

# --- Sonali Configs ---
SONALI_BASE_URL = "https://billpay.sonalibank.com.bd"
SONALI_SEARCH_URL = SONALI_BASE_URL + "/BoardRescrutiny/Home/Search"
SONALI_VOUCHER_URL = SONALI_BASE_URL + "/BoardRescrutiny/Home/Voucher/"

sonali_session = requests.Session()
sonali_headers = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; K) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0.0.0 Mobile Safari/537.36"
    ),
    "Referer": SONALI_BASE_URL + "/BoardRescrutiny/Home/Search"
}

BOARDS = [
    "Dhaka Board", "Barisal Board", "Chattogram Board", 
    "Comilla Board", "Dinajpur Board", "Jessore Board", 
    "Mymensingh Board", "Rajshahi Board", "Sylhet Board", 
    "Madrasah Board", "BTEB"
]

current_search_id = 0

# --- Ctg Configs ---
EXAM = "HSC"
YEAR = 2026

BOARD_NAME = "Chattogram"
BOARD_CODE = "14"

TIMEOUT = 30
COOLDOWN = 5
BATCH_SIZE = 500

user_cooldowns = {}
active_batch_jobs = {}

CTG_BASE_URL = "https://hscresult.bise-ctg.gov.bd"
REFERER = CTG_BASE_URL + "/h22_31_x1_26/individual/index.php"
RESULT_URL = CTG_BASE_URL + "/h22_31_x1_26/individual/result_mark_details.php"
API_URL = "https://rescrutiny.eduboardresults.gov.bd/api/rescrutiny/getStudentInfo"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# =====================================================
# SONALI DATA EXTRACTION & LOGIC
# =====================================================
def get_sonali_data(tid):
    url = f"{SONALI_VOUCHER_URL}{tid}"
    try:
        r = sonali_session.get(url, headers=sonali_headers, timeout=15, verify=False)
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

async def run_sonali_search(update_or_query, context, s_r, e_r):
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
                sonali_session.get(SONALI_BASE_URL + "/BoardRescrutiny/Home/Search", headers=sonali_headers, verify=False)
            
            search_url = f"{SONALI_SEARCH_URL}?searchStr={roll}"
            r = sonali_session.get(search_url, headers=sonali_headers, timeout=12, verify=False)
            ids = re.findall(r'/BoardRescrutiny/Home/Voucher/([A-Za-z0-9_-]+)', r.text, re.I)
            
            if ids:
                v_list = []
                for tid in set(ids):
                    d = get_sonali_data(tid)
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
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👉 Next 500?", callback_data="sonali_next_500")]]))


# =====================================================
# CTG DATA EXTRACTION & LOGIC
# =====================================================
def get_ctg_headers():
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": CTG_BASE_URL,
        "Referer": REFERER
    }

def get_board_result(roll):
    session = requests.Session()
    try:
        initial = session.get(REFERER, headers=get_ctg_headers(), timeout=TIMEOUT)
        initial.raise_for_status()

        payload = {"roll": roll, "button2": ""}
        response = session.post(RESULT_URL, data=payload, headers=get_ctg_headers(), timeout=TIMEOUT, allow_redirects=True)
        response.raise_for_status()

        if not response.text.strip():
            return None, "EMPTY"

        if re.search(r"<title>\s*404|<h1>\s*Not Found", response.text, re.IGNORECASE):
            return None, "NOT_FOUND"

        return response.text, "OK"
    except requests.Timeout:
        return None, "TIMEOUT"
    except requests.RequestException:
        return None, "NETWORK"
    finally:
        session.close()

def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()

def title_text(value):
    return clean_text(value).title()

def normalize_key(value):
    return re.sub(r"[^a-z0-9]", "", clean_text(value).lower())

def parse_board_result(html, requested_roll):
    soup = BeautifulSoup(html, "html.parser")
    info = soup.select_one(".info")

    if not info:
        return None

    fields = {}
    elements = info.find_all("div", recursive=False)

    for i in range(0, len(elements) - 1, 2):
        key = clean_text(elements[i].get_text(" ", strip=True))
        value = clean_text(elements[i + 1].get_text(" ", strip=True))
        if key:
            fields[normalize_key(key)] = value

    def get_field(*names):
        for name in names:
            key = normalize_key(name)
            if key in fields:
                return fields[key]
        return "Not Available"

    registration = get_field("Reg. NO", "Reg No", "Registration No", "Registration Number", "Reg. Number", "Registration")
    student_roll = get_field("Roll No", "Roll", "Roll Number")
    name = get_field("Name")

    if registration == "Not Available" or not registration.isdigit():
        return None
    if name == "Not Available":
        return None
    if student_roll != "Not Available" and student_roll != requested_roll:
        return None

    subjects = []
    marks_table = soup.select_one("table.marks")

    if marks_table:
        rows = marks_table.select("tbody tr")
        if not rows:
            rows = marks_table.select("tr")

        for row in rows:
            cells = row.find_all("td", recursive=False)
            if len(cells) < 2:
                continue

            raw_subject_name = clean_text(cells[0].get_text(" ", strip=True))
            subject_marks = clean_text(" ".join(cell.get_text(" ", strip=True) for cell in cells[1:]))

            upper_sub = raw_subject_name.upper()
            code_match = re.search(r"(\(\d+\))", raw_subject_name)
            code_str = code_match.group(1) if code_match else ""

            if "INFORMATION" in upper_sub or "ICT" in upper_sub:
                formatted_sub = f"ICT {code_str}".strip()
            elif "BUSINESS ORGANIZATION" in upper_sub:
                formatted_sub = f"BUSINESS {code_str}".strip()
            elif "FINANCE" in upper_sub:
                formatted_sub = f"FINANCE {code_str}".strip()
            else:
                formatted_sub = raw_subject_name

            if formatted_sub and subject_marks:
                subjects.append({"name": formatted_sub, "marks": subject_marks})

    return {
        "roll": requested_roll,
        "registration": registration,
        "board": title_text(get_field("Board")),
        "group": title_text(get_field("Group")),
        "result": get_field("Result").upper(),
        "gpa": get_field("GPA"),
        "institute": title_text(get_field("Institute")),
        "subjects": subjects
    }

def fetch_recheck_result(roll, registration):
    url = f"{API_URL}/{roll}/{registration}/{BOARD_CODE}/{YEAR}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://rescrutiny.eduboardresults.gov.bd/"
    }

    try:
        response = requests.get(url, headers=headers, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()

        if not isinstance(data, dict) or data.get("status") != 200:
            return None

        result_data = data.get("result", {})
        info = result_data.get("info", {})

        if not isinstance(info, dict) or not info.get("name"):
            return None

        phone = clean_text(info.get("phoneNo", ""))
        if not phone or phone == "" or phone.lower() == "none" or phone == "N/A":
            return None

        return {
            "name": clean_text(info.get("name", "N/A")),
            "father": clean_text(info.get("fatherName", "N/A")),
            "mother": clean_text(info.get("motherName", "N/A")),
            "phone": phone,
            "roll": str(info.get("rollNo", roll)),
            "registration": str(info.get("regNo", registration)),
            "passing_year": clean_text(info.get("passYear", YEAR))
        }
    except Exception:
        return None

def combine_results(board_data, api_data):
    return {
        "roll": api_data["roll"],
        "registration": api_data["registration"],
        "name": api_data["name"],
        "father": api_data["father"],
        "mother": api_data["mother"],
        "phone": api_data["phone"],
        "passing_year": api_data["passing_year"],
        "board": board_data["board"] if board_data["board"] != "Not Available" else BOARD_NAME,
        "group": board_data["group"],
        "result": board_data["result"],
        "gpa": board_data["gpa"],
        "institute": board_data["institute"],
        "subjects": board_data["subjects"]
    }

def normalize_phone(phone):
    digits = re.sub(r"\D", "", str(phone or ""))
    if not digits:
        return None
    if digits.startswith("0088"):
        digits = digits[2:]
    if digits.startswith("880"):
        return digits
    if digits.startswith("0"):
        return "88" + digits
    if len(digits) == 10:
        return "880" + digits
    return digits

def format_single_result(data):
    subject_lines = [f"{s['name']} → {s['marks']}" for s in data["subjects"]]
    subject_text = "\n".join(subject_lines) if subject_lines else "Subject details unavailable."

    return (
        "📌 <b>Exam: HSC 2026</b>\n"
        "🎓 <b>HSC RECHECK RESULT (APPLIED)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 Roll: {escape(data['roll'])}\n"
        f"📝 Registration: {escape(data['registration'])}\n\n"
        f"👤 Name: {escape(data['name'])}\n"
        f"👨 Father: {escape(data['father'])}\n"
        f"👩 Mother: {escape(data['mother'])}\n"
        f"📞 Mobile: {escape(data['phone'])}\n\n"
        f"🏫 Board: {escape(data['board'])}\n"
        f"📚 Group: {escape(data['group'])}\n\n"
        f"📊 Result: {escape(data['result'])}\n"
        f"⭐ GPA: {escape(data['gpa'])}\n\n"
        f"🏫 Institute: {escape(data['institute'])}\n\n"
        "📊 <b>SUBJECT-WISE MARKS</b>\n\n"
        f"<pre>{escape(subject_text)}</pre>"
    )

def get_contact_keyboard(phone):
    full_phone = normalize_phone(phone)
    if not full_phone:
        return None
    keyboard = [[
        InlineKeyboardButton("🟢 WhatsApp", url=f"https://wa.me/{full_phone}"),
        InlineKeyboardButton("🔵 Telegram", url=f"tg://resolve?phone={full_phone}")
    ]]
    return InlineKeyboardMarkup(keyboard)

async def process_batch_rolls(bot, chat_id, user_id, start_roll, end_roll, message_to_edit=None):
    if start_roll > end_roll:
        if message_to_edit:
            await message_to_edit.edit_text("❌ শেষ রোল শুরুর রোলের চেয়ে ছোট হতে পারে না!")
        return

    rolls_to_check = [str(r) for r in range(start_roll, end_roll + 1)]
    if len(rolls_to_check) > BATCH_SIZE:
        rolls_to_check = rolls_to_check[:BATCH_SIZE]

    actual_start = int(rolls_to_check[0])
    actual_end = int(rolls_to_check[-1])
    total_in_batch = len(rolls_to_check)

    active_batch_jobs[user_id] = False

    if message_to_edit:
        wait_msg = message_to_edit
        try:
            await wait_msg.edit_text(
                f"🚀 <b>BATCH PROCESSING STARTED ({actual_start} - {actual_end})</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 Total Rolls in this Batch: {total_in_batch}\n"
                "🔍 Checking applications & phone numbers...\n\n"
                "🛑 Cancel with /stop",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
    else:
        wait_msg = await bot.send_message(
            chat_id=chat_id,
            text=(
                f"🚀 <b>BATCH PROCESSING STARTED ({actual_start} - {actual_end})</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 Total Rolls in this Batch: {total_in_batch}\n"
                "🔍 Checking applications & phone numbers...\n\n"
                "🛑 Cancel with /stop"
            ),
            parse_mode=ParseMode.HTML
        )

    successful_results = []
    skipped_count = 0
    processed_count = 0

    try:
        for idx, roll in enumerate(rolls_to_check, start=1):
            if active_batch_jobs.get(user_id, False):
                break

            html, error = await asyncio.to_thread(get_board_result, roll)
            if error == "OK":
                board_data = parse_board_result(html, roll)
                if board_data:
                    api_data = await asyncio.to_thread(fetch_recheck_result, roll, board_data["registration"])
                    if api_data:
                        final_data = combine_results(board_data, api_data)
                        successful_results.append(final_data)
                        
                        msg = format_single_result(final_data)
                        markup = get_contact_keyboard(final_data["phone"])
                        try:
                            await bot.send_message(
                                chat_id=chat_id,
                                text=msg,
                                parse_mode=ParseMode.HTML,
                                reply_markup=markup
                            )
                        except Exception:
                            pass
                    else:
                        skipped_count += 1
                else:
                    skipped_count += 1
            else:
                skipped_count += 1

            processed_count += 1

            if idx == 1 or idx % 3 == 0 or idx == len(rolls_to_check):
                try:
                    await wait_msg.edit_text(
                        "🔍 <b>SCANNING IN PROGRESS...</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"📈 Range: {actual_start} - {actual_end}\n"
                        f"📊 Progress: {idx}/{total_in_batch}\n"
                        f"✅ Valid Found (Live): {len(successful_results)} | ❌ Skipped: {skipped_count}\n"
                        f"Current Roll: <code>{roll}</code>\n\n"
                        "🛑 Cancel with /stop",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass

            await asyncio.sleep(0.4)

        if user_id in active_batch_jobs:
            del active_batch_jobs[user_id]

        if not successful_results:
            await wait_msg.edit_text(
                f"❌ <b>BATCH COMPLETED ({actual_start} - {actual_end})</b>\n\n"
                f"এই ব্যাচে কোনো রিচেক আবেদনকৃত (ফোন নম্বরযুক্ত) শিক্ষার্থী পাওয়া যায়নি।"
            )
            return

        file_lines = []
        file_lines.append("==========================================")
        file_lines.append(f" HSC 2026 APPLIED RECHECK REPORT ({actual_start} to {actual_end})")
        file_lines.append(f" Board: {BOARD_NAME} | Total Found: {len(successful_results)}")
        file_lines.append("==========================================\n")

        for res in successful_results:
            file_lines.append(f"Roll: {res['roll']} | Reg: {res['registration']}")
            file_lines.append(f"Name: {res['name']}")
            file_lines.append(f"Father: {res['father']} | Mother: {res['mother']}")
            file_lines.append(f"Mobile: {res['phone']}")
            file_lines.append(f"Group: {res['group']} | Result: {res['result']} | GPA: {res['gpa']}")
            file_lines.append(f"Institute: {res['institute']}")
            file_lines.append("Subjects & Marks:")
            for s in res['subjects']:
                file_lines.append(f"  - {s['name']} : {s['marks']}")
            file_lines.append("-" * 40 + "\n")

        file_content = "\n".join(file_lines)
        file_path = f"applied_hsc_{actual_start}_{actual_end}_{user_id}.txt"

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(file_content)

        summary_text = (
            "✅ <b>BATCH COMPLETED!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 Range: {actual_start} - {actual_end}\n"
            f"✅ Total Valid Sent: {len(successful_results)}\n"
            f"❌ Skipped: {skipped_count}\n\n"
            "📁 নিচে কমপ্লিট টেক্সট ফাইল ও Next 500 বাটন দেওয়া হলো:"
        )

        await wait_msg.edit_text(summary_text, parse_mode=ParseMode.HTML)

        with open(file_path, "rb") as f:
            next_start = actual_end + 1
            next_end = next_start + BATCH_SIZE - 1
            
            callback_data = f"ctg_next_{next_start}_{next_end}"
            
            keyboard = [[
                InlineKeyboardButton(f"👉 Next 500? ({next_start}-{next_end})", callback_data=callback_data)
            ]]
            next_markup = InlineKeyboardMarkup(keyboard)

            await bot.send_document(
                chat_id=chat_id,
                document=f,
                filename=f"Results_{actual_start}_to_{actual_end}.txt",
                caption=f"📄 রেঞ্জ ({actual_start} - {actual_end})-এর কমপ্লিট ব্যাকআপ ফাইল।",
                reply_markup=next_markup
            )

        if os.path.exists(file_path):
            os.remove(file_path)

    except Exception as e:
        logger.exception("Batch processing error")
        if user_id in active_batch_jobs:
            del active_batch_jobs[user_id]
        await wait_msg.edit_text("⚠️ প্রসেসিং চলাকালীন একটি সমস্যা হয়েছে। দয়া করে আবার চেষ্টা করুন।")


# =====================================================
# COMBINED HANDLERS & ROUTING
# =====================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    
    keyboard = [
        [InlineKeyboardButton("Recheck Sonali", callback_data="mode_sonali")],
        [InlineKeyboardButton("Recheck Ctg", callback_data="mode_ctg")]
    ]
    
    await update.message.reply_text(
        "🤖 <b>Multi-Scanner Bot Menu</b>\n\nদয়া করে নিচের বাটনগুলো থেকে আপনার কাঙ্ক্ষিত মোডটি সিলেক্ট করুন:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def mode_selection_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    global current_search_id
    
    if data == "mode_sonali":
        context.user_data["active_mode"] = "sonali"
        context.user_data["sonali_step"] = "institution"  # স্টেপ ইনিশিয়ালাইজ করা হলো
        current_search_id += 1
        
        keyboard = []
        for board in BOARDS:
            keyboard.append([InlineKeyboardButton(board, callback_data=f"board_{board}")])
        
        await query.message.reply_text(
            "🏦 <b>Rescrutiny Fee Scanner Bot (Sonali Mode)</b>\n\nদয়া করে নিচের তালিকা থেকে আপনার শিক্ষা বোর্ডটি সিলেক্ট করুন:", 
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data == "mode_ctg":
        context.user_data["active_mode"] = "ctg"
        await query.message.reply_text(
            "🎓 <b>HSC RECHECK FILTER BOT (Ctg Mode)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🏫 Board: Chattogram | Year: 2026\n\n"
            "💡 সঠিক রোল (যেমন: `520081`) অথবা রেঞ্জ (যেমন: `520081-525000`) প্রদান করুন।\n\n"
            "🛑 প্রসেস থামাতে `/stop` লিখুন.",
            parse_mode="HTML"
        )
    
    elif data.startswith("board_"):
        board_name = data.split("_", 1)[1]
        context.user_data["selected_board"] = board_name
        context.user_data["sonali_step"] = "institution"
        
        reply_kb = ReplyKeyboardMarkup([[KeyboardButton("🏫 Institute Name")]], resize_keyboard=True)
        await query.message.reply_text(
            f"আপনি সিলেক্ট করেছেন: <b>{board_name}</b>\n\nএখন নতুন ইনস্টিটিউটের নাম দিতে চাইলে নিচের <b>'🏫 Institute Name'</b> বাটনে ক্লিক করুন অথবা সরাসরি নাম টাইপ করুন:",
            parse_mode="HTML",
            reply_markup=reply_kb
        )
    
    elif data == "sonali_next_500":
        current_search_id += 1
        last_end = context.user_data.get("current_end", 0)
        await run_sonali_search(query, context, last_end + 1, last_end + 500)
    
    elif data.startswith("ctg_next_"):
        parts = data.split("_")
        if len(parts) == 4:
            next_start = int(parts[2])
            next_end = int(parts[3])
            user_id = update.effective_user.id
            wait_msg = await query.message.reply_text(f"🔄 পরবর্তী ব্যাচ ({next_start} - {next_end}) লোড হচ্ছে...")
            await process_batch_rolls(context.bot, query.message.chat_id, user_id, next_start, next_end, wait_msg)

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    text = (update.message.text or "").strip()
    user_id = update.effective_user.id
    mode = context.user_data.get("active_mode")

    if not mode:
        await update.message.reply_text("দয়া করে প্রথমে /start কমান্ড দিয়ে মোড সিলেক্ট করুন।")
        return

    # Sonali Mode Handling
    if mode == "sonali":
        step = context.user_data.get("sonali_step", "institution")

        if text == "🏫 Institute Name":
            context.user_data["sonali_step"] = "institution"
            await update.message.reply_text("দয়া করে নতুন **ইনস্টিটিউশনের নাম (Institution Name)** ম্যানুয়ালি টাইপ করে পাঠান:", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
            return

        if step == "institution":
            context.user_data["institution_name"] = text
            context.user_data["sonali_step"] = "roll"
            reply_kb = ReplyKeyboardMarkup([[KeyboardButton("🏫 Institute Name")]], resize_keyboard=True)
            await update.message.reply_text(
                f"ইনস্টিটিউশনের নাম সংরক্ষিত হয়েছে: <b>{text}</b>\n\nএখন শিক্ষার্থীর রোল নম্বর বা রোল রেঞ্জ দিন (উদা: <code>800001</code> অথবা <code>800001-800010</code>):",
                parse_mode="HTML",
                reply_markup=reply_kb
            )
            return

        elif step == "roll":
            if text == "🏫 Institute Name":
                context.user_data["sonali_step"] = "institution"
                await update.message.reply_text("দয়া করে নতুন **ইনস্টিটিউশনের নাম (Institution Name)** ম্যানুয়ালি টাইপ করে পাঠান:", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
                return

            global current_search_id
            current_search_id += 1 
            try:
                if "-" in text:
                    s, e = map(int, text.split("-"))
                    await run_sonali_search(update, context, s, e)
                elif text.isdigit():
                    await run_sonali_search(update, context, int(text), int(text))
                else:
                    await update.message.reply_text("❌ সঠিক রোল বা রেঞ্জ দিন।\nউদাহরণ: <code>800001</code> অথবা <code>800001-800010</code>", parse_mode="HTML")
            except Exception:
                pass
            return

    # Ctg Mode Handling
    elif mode == "ctg":
        single_match = re.fullmatch(r"[0-9]{4,8}", text)
        range_match = re.fullmatch(r"([0-9]{4,8})\s*-\s*([0-9]{4,8})", text)

        if not single_match and not range_match:
            await update.message.reply_text(
                "❌ সঠিক ফরম্যাট নয়!\n\n"
                "একটি সঠিক রোল (যেমন: `520081`) অথবা রেঞ্জ (যেমন: `520081-525000`) প্রদান করুন।"
            )
            return

        now = time.monotonic()
        if single_match:
            previous = user_cooldowns.get(user_id, 0)
            if now - previous < COOLDOWN:
                await update.message.reply_text("⏳ দয়া করে কয়েক সেকেন্ড অপেক্ষা করুন।")
                return
            user_cooldowns[user_id] = now

            wait_msg = await update.message.reply_text("🔍 সার্চ করা হচ্ছে...")
            html, error = await asyncio.to_thread(get_board_result, text)
            if error == "OK":
                board_data = parse_board_result(html, text)
                if board_data:
                    api_data = await asyncio.to_thread(fetch_recheck_result, text, board_data["registration"])
                    if api_data:
                        final_data = combine_results(board_data, api_data)
                        msg = format_single_result(final_data)
                        markup = get_contact_keyboard(final_data["phone"])
                        await wait_msg.edit_text(msg, parse_mode=ParseMode.HTML, reply_markup=markup)
                        return
            await wait_msg.edit_text("❌ এই রোলটির জন্য কোনো রিচেক আবেদন বা ফোন নম্বর পাওয়া যায়নি।")
            return

        start_roll = int(range_match.group(1))
        end_roll = int(range_match.group(2))

        if start_roll > end_roll:
            start_roll, end_roll = end_roll, start_roll

        wait_msg = await update.message.reply_text("🚀 রেঞ্জ প্রসেসিং শুরু হচ্ছে...")
        batch_end = min(start_roll + BATCH_SIZE - 1, end_roll)
        await process_batch_rolls(context.bot, update.effective_chat.id, user_id, start_roll, batch_end, wait_msg)

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in active_batch_jobs:
        active_batch_jobs[user_id] = True
        await update.message.reply_text("🛑 আপনার সার্চ প্রক্রিয়া বন্ধ করার নির্দেশ দেওয়া হয়েছে।")
    else:
        global current_search_id
        current_search_id += 1
        await update.message.reply_text("🛑 প্রসেস বন্ধ বা রিসেট করা হয়েছে। নতুন সার্চ শুরু করতে /start দিন।")


# =====================================================
# MAIN FUNCTION
# =====================================================
def main():
    if not BOT_TOKEN or BOT_TOKEN == "PASTE_YOUR_NEW_BOT_TOKEN_HERE":
        raise ValueError("Please add your BotFather Token!")

    keep_alive()

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop_command))
    
    application.add_handler(CallbackQueryHandler(mode_selection_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))

    print("======================================")
    print("COMBINED RECHECK BOT STARTED SUCCESSFULLY")
    print("======================================")

    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
