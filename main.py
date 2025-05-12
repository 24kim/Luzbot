import os
import requests
import random
import json
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Estados para la conversación
(
    CHOOSING_ACTION,
    ENTERING_BIN,
    ENTERING_CARD_DETAILS,
    ENTERING_USER_DETAILS,
    HANDLE_MAIL,
) = range(5)

# Almacenamiento
pending_users = {}
authorized_users = set()

# --- APIs ---
async def fetch_random_user(gender: str, nationality: str) -> dict:
    url = f"https://randomuser.me/api/?gender={gender}&nat={nationality}"
    response = requests.get(url)
    return response.json().get("results", [{}])[0]

async def fetch_bin_info(bin_number: str) -> dict:
    url = f"https://lookup.binlist.net/{bin_number}"
    response = requests.get(url)
    return response.json() if response.status_code == 200 else {}

async def generate_temp_email() -> dict:
    url = "https://api.tempmail.io/generate"
    response = requests.get(url)
    return response.json() if response.status_code == 200 else {}

async def fetch_temp_mail_messages(email: str) -> list:
    url = f"https://api.tempmail.io/messages?email={email}"
    response = requests.get(url)
    return response.json() if response.status_code == 200 else []

# --- Generador de tarjetas ---
def luhn_checksum(card_number: str) -> int:
    digits = [int(x) for x in card_number]
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    checksum = sum(odd_digits)
    for d in even_digits:
        checksum += sum(divmod(d * 2, 10))
    return checksum % 10

async def generate_valid_card(bin_number: str, count: int = 1) -> list:
    cards = []
    for _ in range(count):
        random_part = "".join([str(random.randint(0, 9)) for _ in range(15 - len(bin_number))])
        card_candidate = bin_number + random_part
        checksum = luhn_checksum(card_candidate + "0")
        final_card = card_candidate + str((10 - checksum) % 10)
        month = str(random.randint(1, 12)).zfill(2)
        year = str(random.randint(23, 30))
        cvv = str(random.randint(100, 999))
        cards.append({
            "card": final_card,
            "expiry": f"{month}/{year}",
            "cvv": cvv
        })
    return cards

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        await update.message.reply_text("🛠 **Modo Administrador Activado**")
        return ConversationHandler.END

    if user_id in authorized_users:
        await show_actions(update)
        return ConversationHandler.END

    pending_users[user_id] = update.effective_user.full_name
    keyboard = [[InlineKeyboardButton("✅ Aceptar Usuario", callback_data=f"accept_{user_id}")]]
    await context.bot.send_message(
        ADMIN_ID,
        f"⚠️ **Nuevo Usuario**\n\nID: `{user_id}`\nNombre: {update.effective_user.full_name}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    await update.message.reply_text("⏳ Espera aprobación del administrador.")
    return ConversationHandler.END

async def handle_admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    user_id = int(data[1])

    if data[0] == "accept":
        authorized_users.add(user_id)
        await query.edit_message_text(f"✅ Usuario {pending_users[user_id]} aceptado.")
        await context.bot.send_message(user_id, "🎉 ¡Aprobado! Usa /help para ver opciones.")
    else:
        await query.edit_message_text(f"❌ Usuario {pending_users[user_id]} rechazado.")
        await context.bot.send_message(user_id, "❌ No tienes acceso al bot.")
    del pending_users[user_id]

async def show_actions(update: Update) -> None:
    keyboard = [
        [KeyboardButton("🔍 Consultar BIN")],
        [KeyboardButton("💳 Generar Tarjetas")],
        [KeyboardButton("👤 Generar Datos")],
        [KeyboardButton("📧 Generar Correo")]
    ]
    await update.message.reply_text(
        "✨ **Elige una acción:**",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )

async def handle_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "🔍 Consultar BIN":
        await update.message.reply_text("🔢 Ingresa el BIN (6 dígitos):")
        return ENTERING_BIN
    elif text == "💳 Generar Tarjetas":
        await update.message.reply_text("💳 Ingresa BIN y cantidad (ej: 123456 5):")
        return ENTERING_CARD_DETAILS
    elif text == "👤 Generar Datos":
        await update.message.reply_text("🌍 Ingresa país y género (ej: US male):")
        return ENTERING_USER_DETAILS
    elif text == "📧 Generar Correo":
        email_data = await generate_temp_email()
        if email_data:
            context.user_data["temp_email"] = email_data["email"]
            await update.message.reply_text(
                f"📧 **Correo Temporal:**\n\n`{email_data['email']}`\n\nUsa /inbox para ver mensajes.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ Error al generar correo.")
    return CHOOSING_ACTION

async def handle_bin_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    bin_number = update.message.text.strip()
    if len(bin_number) < 6 or not bin_number.isdigit():
        await update.message.reply_text("❌ BIN inválido. Ingresa 6+ dígitos.")
        return ENTERING_BIN

    bin_data = await fetch_bin_info(bin_number)
    if not bin_data:
        await update.message.reply_text("❌ No se encontró información del BIN.")
    else:
        response = (
            f"🏦 **BIN:** `{bin_number}`\n"
            f"📊 **Tipo:** {bin_data.get('type', 'N/A')}\n"
            f"🏛 **Banco:** {bin_data.get('bank', {}).get('name', 'N/A')}\n"
            f"🌍 **País:** {bin_data.get('country', {}).get('name', 'N/A')}"
        )
        await update.message.reply_text(response, parse_mode="Markdown")
    await show_actions(update)
    return CHOOSING_ACTION

async def handle_card_generation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        bin_number, count = update.message.text.split()
        count = min(int(count), 20)
    except:
        await update.message.reply_text("❌ Formato inválido. Ejemplo: `123456 5`")
        return ENTERING_CARD_DETAILS

    cards = await generate_valid_card(bin_number, count)
    response = "💳 **Tarjetas Generadas:**\n\n" + "\n".join(
        [f"`{card['card']}` | {card['expiry']} | {card['cvv']}" for card in cards]
    )
    await update.message.reply_text(response, parse_mode="Markdown")
    await show_actions(update)
    return CHOOSING_ACTION

async def handle_user_generation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        nationality, gender = update.message.text.lower().split()
    except:
        await update.message.reply_text("❌ Formato inválido. Ejemplo: `US male`")
        return ENTERING_USER_DETAILS

    user_data = await fetch_random_user(gender, nationality)
    if not user_data:
        await update.message.reply_text("❌ Error al generar datos.")
    else:
        response = (
            f"👤 **Nombre:** {user_data['name']['first']} {user_data['name']['last']}\n"
            f"📧 **Email:** `{user_data['email']}`\n"
            f"📞 **Teléfono:** `{user_data['phone']}`\n"
            f"🏠 **Dirección:** {user_data['location']['street']['name']}, {user_data['location']['city']}"
        )
        await update.message.reply_text(response, parse_mode="Markdown")
    await show_actions(update)
    return CHOOSING_ACTION

async def handle_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if "temp_email" not in context.user_data:
        await update.message.reply_text("❌ No hay correo temporal activo.")
        return

    messages = await fetch_temp_mail_messages(context.user_data["temp_email"])
    if not messages:
        await update.message.reply_text("📭 No hay mensajes nuevos.")
    else:
        response = "📨 **Mensajes Recibidos:**\n\n" + "\n\n".join(
            [f"**De:** {msg['from']}\n**Asunto:** {msg['subject']}\n**Mensaje:** {msg['body']}" 
            for msg in messages]
        )
        await update.message.reply_text(response, parse_mode="Markdown")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Operación cancelada.")
    await show_actions(update)
    return ConversationHandler.END

def main() -> None:
    application = Application.builder().token(TOKEN).build()

    # Handlers principales
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("inbox", handle_inbox))
    application.add_handler(CallbackQueryHandler(handle_admin_decision, pattern=r"^(accept|reject)_\d+$"))

    # ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_action)],
        states={
            ENTERING_BIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bin_input)],
            ENTERING_CARD_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_card_generation)],
            ENTERING_USER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_generation)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        map_to_parent={
            CHOOSING_ACTION: CHOOSING_ACTION,
        }
    )
    application.add_handler(conv_handler)

    application.run_polling()

if __name__ == "__main__":
    main()