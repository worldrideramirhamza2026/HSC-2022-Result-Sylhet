import requests
from io import BytesIO
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from PIL import Image

from flask import Flask
from threading import Thread

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)

TOKEN = "8685902230:AAG-fUX5ObxUF9qJSQyJDuCV3eNhyRtCkYc"
BASE_URL = "https://esheba.sylhetboard.gov.bd/publicResult/"

user_data = {}

# ===== FLASK KEEP ALIVE =====
app_flask = Flask('')

@app_flask.route('/')
def home():
    return "Bot is alive!"

def run():
    app_flask.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ===== CAPTCHA RESIZE =====
def resize_captcha(image_bytes):
    img = Image.open(BytesIO(image_bytes))
    img = img.resize((250, 80))
    img = img.convert("L")

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

# ===== SAFE GET =====
def get_value(data, *keys):
    for key in keys:
        if key in data and data[key]:
            return data[key]
    return ""

# ===== EXTRACT =====
def extract(soup, keyword):
    data_dict = {}
    for table in soup.find_all("table"):
        if keyword in table.get_text():
            for row in table.find_all("tr"):
                cols = row.find_all("td")

                if len(cols) >= 4:
                    data_dict[cols[0].get_text(strip=True)] = cols[1].get_text(strip=True)
                    data_dict[cols[2].get_text(strip=True)] = cols[3].get_text(strip=True)

                elif len(cols) == 2:
                    data_dict[cols[0].get_text(strip=True)] = cols[1].get_text(strip=True)

    return data_dict

# ===== START =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["🚀 Start"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "📥 Start চাপ দিয়ে শুরু করো:",
        reply_markup=reply_markup
    )

# ===== HANDLE MESSAGE =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    text = update.message.text.strip()

    if text == "🚀 Start":
        await update.message.reply_text("📥 তোমার Roll নম্বর দাও:")
        return

    if user_id not in user_data:
        session = requests.Session()
        session.get(BASE_URL + "index.php")
        captcha = session.get(BASE_URL + "captcha.php")

        user_data[user_id] = {
            "roll": text,
            "session": session
        }

        small_img = resize_captcha(captcha.content)

        await update.message.reply_photo(
            photo=small_img,
            caption="🔐 CAPTCHA লিখো:"
        )

    else:
        captcha_text = text
        data = user_data[user_id]

        loading_msg = await update.message.reply_text(
            "⏳ একটু অপেক্ষা করো...\nResult আনতেছি..."
        )

        payload = {
            "hroll": data["roll"],
            "autocaptcha": captcha_text,
            "btnSubmit": "Submit",
            "btnaction": "c2hvd1B1YmxpY1Jlc3VsdA==",
            "param": "MjAyMg=="
        }

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": BASE_URL + "index.php"
        }

        res = data["session"].post(
            BASE_URL + "include/function.php",
            data=payload,
            headers=headers
        )

        html = res.text
        await loading_msg.delete()

        if "STUDENT INFORMATION" in html:
            soup = BeautifulSoup(html, "html.parser")

            for img in soup.find_all("img"):
                src = img.get("src")
                if src and ("jpg" in src or "jpeg" in src):
                    img_url = urljoin(BASE_URL, src)
                    await update.message.reply_photo(photo=img_url)
                    break

            student = extract(soup, "STUDENT INFORMATION")
            hsc = extract(soup, "HSC RESULT")

            name = get_value(student, "Name")
            father = get_value(student, "Father's Name")
            mother = get_value(student, "Mother's Name")
            dob = get_value(student, "Date of Birth")
            gender = get_value(student, "Gender")

            roll = get_value(hsc, "Roll No")
            reg = get_value(hsc, "Registration No", "Registration No.")
            board = get_value(hsc, "Board")
            group = get_value(hsc, "Group")
            result = get_value(hsc, "Result")
            gpa = get_value(hsc, "GPA")
            institute = get_value(hsc, "Institute")

            msg = (
                "🧑‍🎓 STUDENT INFORMATION\n"
                "━━━━━━━━━━━━━━\n\n"
                f"👤 Name: {name}\n"
                f"👨 Father: {father}\n"
                f"👩 Mother: {mother}\n\n"
                f"📅 DOB: {dob}\n"
                f"⚧ Gender: {gender}\n\n"
                "━━━━━━━━━━━━━━\n"
                "📘 HSC RESULT 2022\n"
                "━━━━━━━━━━━━━━\n\n"
                f"🆔 Roll No: {roll}\n"
                f"📄 Registration No: {reg}\n\n"
                f"🏫 Board: {board}\n"
                f"📚 Group: {group}\n\n"
                f"📊 Result: {result}\n"
                f"⭐ GPA: {gpa}\n\n"
                f"🏫 Institute: {institute}"
            )

            await update.message.reply_text(msg)

            next_roll = int(roll) + 1

            keyboard = [
                [InlineKeyboardButton(f"➡️ Next ({next_roll})", callback_data=f"next_{next_roll}")]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                "👉 Next করতে নিচের বাটনে চাপ দাও",
                reply_markup=reply_markup
            )

        else:
            await update.message.reply_text("❌ ভুল CAPTCHA বা Roll!")

        del user_data[user_id]

# ===== BUTTON =====
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.message.chat_id
    data = query.data

    if data.startswith("next_"):
        next_roll = data.split("_")[1]

        await query.edit_message_text("🔄 Loading...")

        session = requests.Session()
        session.get(BASE_URL + "index.php")
        captcha = session.get(BASE_URL + "captcha.php")

        user_data[user_id] = {
            "roll": next_roll,
            "session": session
        }

        small_img = resize_captcha(captcha.content)

        await query.message.reply_text(next_roll)

        await query.message.reply_photo(
            photo=small_img,
            caption="🔐 CAPTCHA লিখো:"
        )

# ===== RUN =====
if __name__ == "__main__":
    keep_alive()  # 🔥 IMPORTANT

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🤖 Bot Running...")
    app.run_polling()
