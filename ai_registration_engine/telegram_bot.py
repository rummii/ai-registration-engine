import os
import sys
import sqlite3
import telebot
from telebot import types
from datetime import datetime
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_CHAT_ID, DB_PATH, VOUCHER_DIR

# --- SINGLE-INSTANCE LOCK MECHANISM ---
LOCK_FILE = "bot.lock"

if os.path.exists(LOCK_FILE):
    print("Another instance of the bot is already running. Exiting.")
    sys.exit(0)

with open(LOCK_FILE, "w") as f:
    f.write(str(os.getpid()))
# -------------------------------------

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# FIXED: Match EXACTLY with budget_controller.py - NO trailing spaces!
EXPENSE_STRUCTURE = {
    "Other Expenses": ["Power", "Water", "IT", "Communication", "Stationery", "Service/Maintainance", "Misc", "Other"],
    "Promotion Expenses": ["Marketing", "Promotions", "Colletrals", "Printing/Advertising", "Travel", "Transportation"],
    "Payroll & Pilotage fee": ["Pilotage", "Payroll", "Misc", "Other"],
    "Fixed Costs": ["Rent", "Tax"]
}

user_states = {}

def is_authorized(message):
    return message.chat.id == TELEGRAM_ALLOWED_CHAT_ID

@bot.message_handler(commands=['start', 'expense'])
def start_expense(message):
    if not is_authorized(message):
        return
    user_states[message.chat.id] = {}
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(cat, callback_data=f"cat_{cat}") for cat in EXPENSE_STRUCTURE.keys()]
    markup.add(*buttons)
    bot.send_message(message.chat.id, "Select category:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('cat_'))
def handle_category(call):
    if not is_authorized(call.message):
        return
    category = call.data.split('cat_', 1)[1]
    user_states[call.message.chat.id] = {'category': category}
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(item, callback_data=f"item_{item}") for item in EXPENSE_STRUCTURE[category]]
    markup.add(*buttons)
    bot.edit_message_text(f"Selected: {category}\n\n⚙️ Select item:", 
                         call.message.chat.id, 
                         call.message.message_id, 
                         reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('item_'))
def handle_item(call):
    if not is_authorized(call.message):
        return
    item = call.data.split('item_', 1)[1]
    user_states[call.message.chat.id]['item'] = item
    msg = bot.send_message(call.message.chat.id, f"✅ Item: {item}\n\n💵 Enter amount:")
    bot.register_next_step_handler(msg, process_amount)

def process_amount(message):
    try:
        amount = float(message.text)
        user_states[message.chat.id]['amount'] = amount
        msg = bot.send_message(message.chat.id, "📸 Upload receipt/voucher photo (or send /skip):")
        bot.register_next_step_handler(msg, process_voucher)
    except ValueError:
        bot.send_message(message.chat.id, "Invalid number. Please enter a valid amount:")
        msg = bot.send_message(message.chat.id, "Enter amount:")
        bot.register_next_step_handler(msg, process_amount)

def process_voucher(message):
    if message.text and message.text.strip() == '/skip':
        save_expense(message, None)
        return
    
    if not message.photo:
        bot.send_message(message.chat.id, "❌ Please upload a photo or send /skip:")
        msg = bot.send_message(message.chat.id, "Upload voucher:")
        bot.register_next_step_handler(msg, process_voucher)
        return
    
    file_info = bot.get_file(message.photo[-1].file_id)
    file = bot.download_file(file_info.file_path)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    voucher_filename = f"{timestamp}_{message.chat.id}.jpg"
    voucher_path = str(VOUCHER_DIR / voucher_filename)
    
    with open(voucher_path, 'wb') as f:
        f.write(file)
    
    save_expense(message, voucher_path)

def save_expense(message, voucher_path):
    state = user_states[message.chat.id]
    amount = state['amount']
    item = state['item']
    category = state['category']
    now = datetime.now()
    fiscal_year = now.year
    month_index = now.month
    
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    # Insert transaction record
    cursor.execute("""
        INSERT INTO expense_transactions (timestamp, fiscal_year, month_index, category, item, amount, voucher_path, chat_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (now.isoformat(), fiscal_year, month_index, category, item, amount, voucher_path, message.chat.id))
    
    # Update actuals cache - ensure record exists first
    cursor.execute("""
        INSERT OR IGNORE INTO budget_actuals_cache (fiscal_year, month_index, line_item_name, actual_amount)
        VALUES (?, ?, ?, 0.0)
    """, (fiscal_year, month_index, item))
    
    # Then update the amount
    cursor.execute("""
        UPDATE budget_actuals_cache 
        SET actual_amount = actual_amount + ?
        WHERE fiscal_year = ? AND month_index = ? AND line_item_name = ?
    """, (amount, fiscal_year, month_index, item))
    
    conn.commit()
    
    # Verify the update
    cursor.execute("""
        SELECT actual_amount FROM budget_actuals_cache 
        WHERE fiscal_year = ? AND month_index = ? AND line_item_name = ?
    """, (fiscal_year, month_index, item))
    row = cursor.fetchone()
    new_total = row[0] if row else 0.0
    
    conn.close()
    
    voucher_msg = " with voucher saved" if voucher_path else ""
    bot.send_message(message.chat.id, 
                    f"✅ Logged ₱{amount:,.2f} for {item}{voucher_msg}.\n"
                    f"📊 New total: ₱{new_total:,.2f}")
    
    del user_states[message.chat.id]

@bot.message_handler(commands=['correction'])
def start_correction(message):
    if not is_authorized(message):
        return
    msg = bot.send_message(message.chat.id, "️ Enter line item name for correction:")
    bot.register_next_step_handler(msg, process_correction_item)

def process_correction_item(message):
    user_states[message.chat.id] = {'correction_item': message.text.strip()}
    msg = bot.send_message(message.chat.id, "Enter the correct amount:")
    bot.register_next_step_handler(msg, process_correction_amount)

def process_correction_amount(message):
    try:
        new_amount = float(message.text)
        item = user_states[message.chat.id]['correction_item']
        now = datetime.now()
        fiscal_year = now.year
        month_index = now.month
        
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        
        # Get old value for audit
        cursor.execute("""
            SELECT actual_amount FROM budget_actuals_cache 
            WHERE fiscal_year = ? AND month_index = ? AND line_item_name = ?
        """, (fiscal_year, month_index, item))
        old_row = cursor.fetchone()
        old_amount = old_row[0] if old_row else 0.0
        
        # Update actuals
        cursor.execute("""
            UPDATE budget_actuals_cache 
            SET actual_amount = ?
            WHERE fiscal_year = ? AND month_index = ? AND line_item_name = ?
        """, (new_amount, fiscal_year, month_index, item))
        
        # Log correction
        cursor.execute("""
            INSERT INTO expense_transactions (timestamp, fiscal_year, month_index, category, item, amount, voucher_path, chat_id)
            VALUES (?, ?, ?, 'CORRECTION', ?, ?, ?, ?)
        """, (now.isoformat(), fiscal_year, month_index, item, new_amount, None, message.chat.id))
        
        conn.commit()
        conn.close()
        
        bot.send_message(message.chat.id, 
                        f"✅ Corrected {item}: ₱{old_amount:,.2f} → ₱{new_amount:,.2f}")
        
        del user_states[message.chat.id]
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {str(e)}")

if __name__ == '__main__':
    try:
        print("🤖 AIEC Expense Bot starting...")
        print(f"📁 Voucher directory: {VOUCHER_DIR}")
        print(f"📁 Database: {DB_PATH}")
        print("✅ Bot is running! Waiting for messages...")
        bot.remove_webhook()
        bot.infinity_polling()
    finally:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
