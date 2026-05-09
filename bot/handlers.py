"""
Telegram Bot Command Handlers — Interactive Button UI

Uses InlineKeyboardButtons and ConversationHandler for a polished,
button-driven user experience. No need to type commands manually.
"""

import logging
import re
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from database import Database
from email_sender import check_all_dns, check_verification_txt

logger = logging.getLogger(__name__)

DOMAIN_REGEX = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z]{2,})+$")
EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

# ── Conversation states ──────────────────────────────────────
WAITING_DOMAIN = 1
WAITING_EMAIL = 2

# Compose email states
COMPOSE_WAITING_TO = 10
COMPOSE_WAITING_SUBJECT = 11
COMPOSE_WAITING_BODY = 12

# Block sender states
WAITING_BLOCK_SENDER = 20


def get_db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.bot_data["db"]


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Build the main menu button grid."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add Domain", callback_data="menu_add_domain"),
            InlineKeyboardButton("✅ Verify Domain", callback_data="menu_verify"),
        ],
        [
            InlineKeyboardButton("🌐 My Domains", callback_data="menu_domains"),
            InlineKeyboardButton("🗑️ Delete Domain", callback_data="menu_del_domain"),
        ],
        [
            InlineKeyboardButton("📧 Create Email", callback_data="menu_create_email"),
            InlineKeyboardButton("📋 My Emails", callback_data="menu_list"),
        ],
        [
            InlineKeyboardButton("✉️ Send Email", callback_data="menu_compose"),
            InlineKeyboardButton("📤 Sent History", callback_data="menu_sent"),
        ],
        [
            InlineKeyboardButton("🗑️ Delete Email", callback_data="menu_delete"),
            InlineKeyboardButton("🚫 Blocked Senders", callback_data="menu_blocked"),
        ],
        [
            InlineKeyboardButton("❓ Help", callback_data="menu_help"),
        ],
    ])


# ══════════════════════════════════════════════════════════════
#  /start  &  Main Menu
# ══════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Welcome message with main menu buttons."""
    text = (
        "📬 <b>Email Telegram Bot</b>\n\n"
        "Send \u0026 receive emails from your own domain right here in Telegram!\n\n"
        "<b>How it works:</b>\n"
        "1️⃣ Add your domain\n"
        "2️⃣ Set DNS records\n"
        "3️⃣ Verify the domain\n"
        "4️⃣ Create email addresses\n"
        "5️⃣ Receive \u0026 send emails 🎉\n\n"
        "Choose an option below 👇"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, reply_markup=main_menu_keyboard(), parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=main_menu_keyboard(), parse_mode="HTML"
        )
    return ConversationHandler.END


async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Return to main menu from any callback."""
    return await start(update, context)


# ══════════════════════════════════════════════════════════════
#  Help
# ══════════════════════════════════════════════════════════════

async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help via button."""
    query = update.callback_query
    await query.answer()
    text = (
        "📋 <b>How to Use</b>\n\n"
        "➕ <b>Add Domain</b> — Register your domain\n"
        "✅ <b>Verify Domain</b> — Activate after DNS setup\n"
        "📧 <b>Create Email</b> — Add email addresses\n"
        "📋 <b>My Emails</b> — View all your emails\n"
        "✉️ <b>Send Email</b> — Send an email\n"
        "📤 <b>Sent History</b> — View sent emails\n"
        "🗑️ <b>Delete Email</b> — Remove an email\n"
        "🚫 <b>Blocked Senders</b> — Block/unblock senders\n\n"
        "You can also type commands:\n"
        "<code>/start</code> — Main menu\n"
        "<code>/adddomain example.com</code>\n"
        "<code>/verifydomain example.com</code>\n"
        "<code>/createemail hello@example.com</code>\n"
        "<code>/listemails</code>\n"
        "<code>/deletemail hello@example.com</code>\n"
        "<code>/blocksender spam@example.com</code>\n"
        "<code>/blocksender @spamdomain.com</code>"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
    ])
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")


# ══════════════════════════════════════════════════════════════
#  Add Domain  (button flow)
# ══════════════════════════════════════════════════════════════

async def add_domain_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask user to type their domain."""
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="back_menu")]
    ])
    await query.edit_message_text(
        "🌐 <b>Add Domain</b>\n\nSend me your domain name (e.g. <code>example.com</code>):",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    return WAITING_DOMAIN


async def add_domain_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process the domain name the user typed."""
    domain = update.message.text.lower().strip()

    if not DOMAIN_REGEX.match(domain):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Try Again", callback_data="menu_add_domain")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await update.message.reply_text(
            "❌ Invalid domain format.\nExample: <code>example.com</code>",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return ConversationHandler.END

    chat_id = str(update.effective_chat.id)
    db = get_db(context)

    # Block if domain is already verified by another user
    if db.is_domain_verified_by_others(domain, chat_id):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
        ])
        await update.message.reply_text(
            f"❌ Domain <code>{domain}</code> is already owned by another user.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return ConversationHandler.END

    existing = db.get_domain(chat_id, domain)

    if existing:
        status = "✅ verified" if existing["verified"] else "⏳ pending verification"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
        ])
        await update.message.reply_text(
            f"Domain <code>{domain}</code> is already registered ({status}).",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return ConversationHandler.END

    # Generate a unique verification token for this user+domain
    token = f"crystal-verify={uuid.uuid4().hex[:16]}"
    db.add_domain(chat_id, domain, verification_token=token)
    server_ip = context.bot_data.get("server_ip", "YOUR_SERVER_IP")

    text = (
        f"✅ Domain <code>{domain}</code> registered!\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📥 <b>FOR RECEIVING EMAILS</b>\n\n"
        "📌 <b>Step 1 — Add an A record:</b>\n\n"
        f"  Type:   <code>A</code>\n"
        f"  Name:   <code>mail</code>\n"
        f"  Value:  <code>{server_ip}</code>\n"
        f"  TTL:    <code>300</code>\n\n"
        "📌 <b>Step 2 — Add an MX record:</b>\n\n"
        f"  Type:     <code>MX</code>\n"
        f"  Name:     <code>@</code>\n"
        f"  Value:    <code>mail.{domain}</code>\n"
        f"  Priority: <code>10</code>\n"
        f"  TTL:      <code>300</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📤 <b>FOR SENDING EMAILS</b>\n\n"
        "📌 <b>Step 3 — Add an SPF record:</b>\n\n"
        f"  Type:   <code>TXT</code>\n"
        f"  Name:   <code>@</code>\n"
        f"  Value:  <code>v=spf1 a mx ip4:{server_ip} -all</code>\n"
        f"  TTL:    <code>300</code>\n\n"
        "📌 <b>Step 4 — Add a DMARC record:</b>\n\n"
        f"  Type:   <code>TXT</code>\n"
        f"  Name:   <code>_dmarc</code>\n"
        f"  Value:  <code>v=DMARC1; p=none;</code>\n"
        f"  TTL:    <code>300</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔑 <b>DOMAIN VERIFICATION</b>\n\n"
        "📌 <b>Step 5 — Add a Verification TXT record:</b>\n\n"
        f"  Type:   <code>TXT</code>\n"
        f"  Name:   <code>@</code>\n"
        f"  Value:  <code>{token}</code>\n"
        f"  TTL:    <code>300</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "⏳ After adding all DNS records, tap <b>Check DNS</b> to verify."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔍 Check DNS for {domain}", callback_data=f"dnscheck_{domain}")],
        [InlineKeyboardButton(f"✅ Verify {domain}", callback_data=f"verify_{domain}")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
    ])
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    return ConversationHandler.END


# Text command fallback
async def add_domain_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /adddomain <domain> text command."""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "Usage: <code>/adddomain example.com</code>",
            parse_mode="HTML",
        )
        return
    # Simulate by setting the text and calling the receiver
    update.message.text = context.args[0]
    await add_domain_receive(update, context)


# ══════════════════════════════════════════════════════════════
#  Verify Domain
# ══════════════════════════════════════════════════════════════

async def dns_check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check all DNS records for a domain and show status."""
    query = update.callback_query
    await query.answer("Checking DNS records… 🔍")

    domain = query.data.replace("dnscheck_", "", 1)
    chat_id = str(update.effective_chat.id)
    server_ip = context.bot_data.get("server_ip", "YOUR_SERVER_IP")
    db = get_db(context)
    token = db.get_verification_token(chat_id, domain) or ""

    status = check_all_dns(domain, server_ip, verification_token=token)

    lines = [f"🔍 <b>DNS Check for</b> <code>{domain}</code>\n"]
    lines.append("━━━━━━━━━━━━━━━━━━━━━━\n")

    # 1. A Record
    a = status["a_record"]
    if a.get("correct"):
        lines.append(f"✅ <b>A Record</b> — <code>mail.{domain}</code> → <code>{a['value']}</code>")
    elif a.get("exists"):
        lines.append(
            f"⚠️ <b>A Record</b> — points to <code>{a['value']}</code> "
            f"(expected <code>{server_ip}</code>)"
        )
    else:
        lines.append(
            f"❌ <b>A Record</b> — not found\n"
            f"  Type: <code>A</code>\n"
            f"  Name: <code>mail</code>\n"
            f"  Value: <code>{server_ip}</code>"
        )

    # 2. MX Record
    mx = status["mx_record"]
    if mx.get("correct"):
        lines.append(f"\n✅ <b>MX Record</b> — <code>{domain}</code> → <code>{mx['value']}</code>")
    elif mx.get("exists"):
        lines.append(
            f"\n⚠️ <b>MX Record</b> — points to <code>{mx['value']}</code> "
            f"(expected <code>mail.{domain}</code>)"
        )
    else:
        lines.append(
            f"\n❌ <b>MX Record</b> — not found\n"
            f"  Type: <code>MX</code>\n"
            f"  Name: <code>@</code>\n"
            f"  Value: <code>mail.{domain}</code>\n"
            f"  Priority: <code>10</code>"
        )

    # 3. SPF Record
    spf = status["spf_record"]
    if spf["exists"]:
        lines.append(f"\n✅ <b>SPF Record</b> — <code>{spf['record']}</code>")
    else:
        lines.append(
            f"\n❌ <b>SPF Record</b> — not found\n"
            f"  Type: <code>TXT</code>\n"
            f"  Name: <code>@</code>\n"
            f"  Value: <code>v=spf1 a mx ip4:{server_ip} -all</code>"
        )

    # 4. DMARC Record
    dmarc = status["dmarc_record"]
    if dmarc:
        lines.append(f"\n✅ <b>DMARC Record</b> — found")
    else:
        lines.append(
            f"\n❌ <b>DMARC Record</b> — not found\n"
            f"  Type: <code>TXT</code>\n"
            f"  Name: <code>_dmarc</code>\n"
            f"  Value: <code>v=DMARC1; p=none;</code>"
        )

    # 5. Verification TXT Record
    verify = status["verify_txt"]
    if verify["found"]:
        lines.append(f"\n✅ <b>Verification TXT</b> — found")
    else:
        lines.append(
            f"\n❌ <b>Verification TXT</b> — not found\n"
            f"  Type: <code>TXT</code>\n"
            f"  Name: <code>@</code>\n"
            f"  Value: <code>{token}</code>"
        )

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")

    # Summary
    if status["all_ready"]:
        lines.append("\n🎉 <b>All DNS records are set up!</b> You can verify and start using your domain.")
    else:
        if status["receive_ready"]:
            lines.append("\n📥 Receiving: ✅ Ready")
        else:
            lines.append("\n📥 Receiving: ❌ Not ready")
        if status["send_ready"]:
            lines.append("📤 Sending: ✅ Ready")
        else:
            lines.append("📤 Sending: ❌ Not ready")
        if status["verify_ready"]:
            lines.append("🔑 Ownership: ✅ Verified")
        else:
            lines.append("🔑 Ownership: ❌ Not verified")
        lines.append("\n💡 Add the missing records above, then tap <b>🔄 Refresh</b>.")

    keyboard_buttons = [
        [InlineKeyboardButton(f"🔄 Refresh", callback_data=f"dnscheck_{domain}")],
    ]
    if status["receive_ready"] and status["verify_ready"]:
        keyboard_buttons.append(
            [InlineKeyboardButton(f"✅ Verify {domain}", callback_data=f"verify_{domain}")]
        )
    keyboard_buttons.append(
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
    )

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard_buttons),
        parse_mode="HTML",
    )


async def verify_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show list of unverified domains as buttons."""
    query = update.callback_query
    await query.answer()

    chat_id = str(update.effective_chat.id)
    db = get_db(context)
    domains = db.get_domains_for_chat(chat_id)
    unverified = [d for d in domains if not d["verified"]]

    if not unverified:
        text = "✅ All your domains are already verified!" if domains else "No domains registered yet."
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Domain", callback_data="menu_add_domain")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
        return

    buttons = [
        [InlineKeyboardButton(f"🌐 {d['domain']}", callback_data=f"verify_{d['domain']}")]
        for d in unverified
    ]
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")])

    await query.edit_message_text(
        "⏳ <b>Select a domain to verify:</b>",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def verify_domain_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Verify a specific domain (callback: verify_<domain>)."""
    query = update.callback_query
    await query.answer()

    domain = query.data.replace("verify_", "", 1)
    chat_id = str(update.effective_chat.id)
    db = get_db(context)
    record = db.get_domain(chat_id, domain)

    if not record:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Domain", callback_data="menu_add_domain")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await query.edit_message_text(
            f"❌ Domain <code>{domain}</code> not found.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    if record["verified"]:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📧 Create Email on {domain}", callback_data=f"create_on_{domain}")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await query.edit_message_text(
            f"✅ <code>{domain}</code> is already verified!",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    # Check verification TXT token in DNS before allowing verification
    token = db.get_verification_token(chat_id, domain) or ""
    if token:
        result = check_verification_txt(domain, token)
        if not result["found"]:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🔍 Check DNS for {domain}", callback_data=f"dnscheck_{domain}")],
                [InlineKeyboardButton("🔄 Try Again", callback_data=f"verify_{domain}")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
            ])
            await query.edit_message_text(
                f"❌ <b>Verification failed</b> for <code>{domain}</code>\n\n"
                "Your verification TXT record was not found in DNS.\n\n"
                "📌 Please add this TXT record:\n\n"
                f"  Type:   <code>TXT</code>\n"
                f"  Name:   <code>@</code>\n"
                f"  Value:  <code>{token}</code>\n"
                f"  TTL:    <code>300</code>\n\n"
                "💡 DNS changes can take a few minutes to propagate.",
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            return

    db.verify_domain(chat_id, domain)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📧 Create Email on {domain}", callback_data=f"create_on_{domain}")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
    ])
    await query.edit_message_text(
        f"✅ Domain <code>{domain}</code> verified!\n\n"
        "⚠️ DNS propagation can take up to 48 hours.\n"
        "You can now create email addresses 👇",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# Text command fallback
async def verify_domain_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /verifydomain <domain> text command."""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: <code>/verifydomain example.com</code>", parse_mode="HTML")
        return

    domain = context.args[0].lower().strip()
    chat_id = str(update.effective_chat.id)
    db = get_db(context)
    record = db.get_domain(chat_id, domain)

    if not record:
        await update.message.reply_text(f"❌ Domain <code>{domain}</code> not registered.", parse_mode="HTML")
        return
    if record["verified"]:
        await update.message.reply_text(f"✅ <code>{domain}</code> is already verified!", parse_mode="HTML")
        return

    # Check verification TXT token in DNS before allowing verification
    token = db.get_verification_token(chat_id, domain) or ""
    if token:
        result = check_verification_txt(domain, token)
        if not result["found"]:
            await update.message.reply_text(
                f"❌ <b>Verification failed</b> for <code>{domain}</code>\n\n"
                "Your verification TXT record was not found in DNS.\n\n"
                "📌 Please add this TXT record:\n\n"
                f"  Type:   <code>TXT</code>\n"
                f"  Name:   <code>@</code>\n"
                f"  Value:  <code>{token}</code>\n"
                f"  TTL:    <code>300</code>\n\n"
                "💡 DNS changes can take a few minutes to propagate.",
                parse_mode="HTML",
            )
            return

    db.verify_domain(chat_id, domain)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📧 Create Email", callback_data=f"create_on_{domain}")],
        [InlineKeyboardButton("🔙 Menu", callback_data="back_menu")],
    ])
    await update.message.reply_text(
        f"✅ <code>{domain}</code> verified!\nCreate emails below 👇",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# ══════════════════════════════════════════════════════════════
#  Create Email
# ══════════════════════════════════════════════════════════════

async def create_email_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show verified domains to create email on."""
    query = update.callback_query
    await query.answer()

    chat_id = str(update.effective_chat.id)
    db = get_db(context)
    domains = db.get_domains_for_chat(chat_id)
    verified = [d for d in domains if d["verified"]]

    if not verified:
        text = "No verified domains yet." if not domains else "No verified domains. Verify a domain first."
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Domain", callback_data="menu_add_domain")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
        return ConversationHandler.END

    buttons = [
        [InlineKeyboardButton(f"🌐 {d['domain']}", callback_data=f"create_on_{d['domain']}")]
        for d in verified
    ]
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")])

    await query.edit_message_text(
        "📧 <b>Select a domain to create an email on:</b>",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def create_email_on_domain(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask user to type the email prefix for a specific domain."""
    query = update.callback_query
    await query.answer()

    domain = query.data.replace("create_on_", "", 1)
    context.user_data["create_domain"] = domain

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="back_menu")]
    ])
    await query.edit_message_text(
        f"📧 <b>Create Email on {domain}</b>\n\n"
        f"Send the full email address\n(e.g. <code>hello@{domain}</code>):",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    return WAITING_EMAIL


async def create_email_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process the email address the user typed."""
    addr = update.message.text.lower().strip()

    if not EMAIL_REGEX.match(addr):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Try Again", callback_data="menu_create_email")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await update.message.reply_text(
            "❌ Invalid email format.\nExample: <code>hello@example.com</code>",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return ConversationHandler.END

    domain = addr.split("@")[1]
    chat_id = str(update.effective_chat.id)
    db = get_db(context)

    domain_rec = db.get_domain(chat_id, domain)
    if not domain_rec:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Domain", callback_data="menu_add_domain")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await update.message.reply_text(
            f"❌ Domain <code>{domain}</code> is not registered.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return ConversationHandler.END

    if not domain_rec["verified"]:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ Verify {domain}", callback_data=f"verify_{domain}")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await update.message.reply_text(
            f"❌ Domain <code>{domain}</code> is not verified yet.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return ConversationHandler.END

    existing = db.get_email(addr)
    if existing:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
        ])
        await update.message.reply_text(
            f"⚠️ <code>{addr}</code> already exists.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return ConversationHandler.END

    db.add_email(addr, chat_id, domain)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📧 Create Another", callback_data="menu_create_email")],
        [InlineKeyboardButton("📋 My Emails", callback_data="menu_list")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
    ])
    await update.message.reply_text(
        f"✅ <code>{addr}</code> is now active!\n\nIncoming emails will appear here 📬",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    return ConversationHandler.END


# Text command fallback
async def create_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /createemail <email> text command."""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: <code>/createemail hello@example.com</code>", parse_mode="HTML")
        return
    update.message.text = context.args[0]
    await create_email_receive(update, context)


# ══════════════════════════════════════════════════════════════
#  List Emails
# ══════════════════════════════════════════════════════════════

async def list_emails_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all domains and emails with action buttons."""
    query = update.callback_query
    await query.answer()
    await _show_email_list(query.edit_message_text, update, context)


async def list_emails_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /listemails text command."""
    await _show_email_list(update.message.reply_text, update, context)


async def _show_email_list(send_fn, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shared logic for listing emails."""
    chat_id = str(update.effective_chat.id)
    db = get_db(context)
    domains = db.get_domains_for_chat(chat_id)

    if not domains:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Domain", callback_data="menu_add_domain")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await send_fn("No domains registered yet.", reply_markup=keyboard, parse_mode="HTML")
        return

    emails = db.get_emails_for_chat(chat_id)
    lines = ["📧 <b>Your Email Addresses</b>\n"]

    for d in domains:
        icon = "✅" if d["verified"] else "⏳"
        lines.append(f"\n<b>{d['domain']}</b> {icon}")
        domain_emails = [e for e in emails if e["domain"] == d["domain"]]
        if domain_emails:
            for e in domain_emails:
                lines.append(f"  • <code>{e['email']}</code>")
        else:
            lines.append("  <i>No emails yet</i>")

    buttons = []
    buttons.append([InlineKeyboardButton("📧 Create Email", callback_data="menu_create_email")])
    if emails:
        buttons.append([InlineKeyboardButton("🗑️ Delete Email", callback_data="menu_delete")])
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")])

    await send_fn(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


# ══════════════════════════════════════════════════════════════
#  Delete Email
# ══════════════════════════════════════════════════════════════

async def delete_email_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all emails as buttons to delete."""
    query = update.callback_query
    await query.answer()

    chat_id = str(update.effective_chat.id)
    db = get_db(context)
    emails = db.get_emails_for_chat(chat_id)

    if not emails:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📧 Create Email", callback_data="menu_create_email")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await query.edit_message_text("No emails to delete.", reply_markup=keyboard, parse_mode="HTML")
        return

    buttons = [
        [InlineKeyboardButton(f"🗑️ {e['email']}", callback_data=f"del_{e['email']}")]
        for e in emails
    ]
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")])

    await query.edit_message_text(
        "🗑️ <b>Select an email to delete:</b>",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def delete_email_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ask for confirmation before deleting."""
    query = update.callback_query
    await query.answer()

    email_addr = query.data.replace("del_", "", 1)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, delete", callback_data=f"confirm_del_{email_addr}"),
            InlineKeyboardButton("❌ No, keep it", callback_data="back_menu"),
        ]
    ])
    await query.edit_message_text(
        f"⚠️ Delete <code>{email_addr}</code>?\n\nYou will stop receiving emails at this address.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def delete_email_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Actually delete the email after confirmation."""
    query = update.callback_query
    await query.answer()

    email_addr = query.data.replace("confirm_del_", "", 1)
    chat_id = str(update.effective_chat.id)
    db = get_db(context)

    record = db.get_email(email_addr)
    if not record or record["chat_id"] != chat_id:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
        ])
        await query.edit_message_text("❌ Email not found or doesn't belong to you.", reply_markup=keyboard)
        return

    db.delete_email(email_addr)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 My Emails", callback_data="menu_list")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
    ])
    await query.edit_message_text(
        f"🗑️ <code>{email_addr}</code> deleted.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# Text command fallback
async def delete_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /deletemail <email> text command."""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: <code>/deletemail hello@example.com</code>", parse_mode="HTML")
        return

    addr = context.args[0].lower().strip()
    chat_id = str(update.effective_chat.id)
    db = get_db(context)
    record = db.get_email(addr)

    if not record:
        await update.message.reply_text(f"❌ <code>{addr}</code> not found.", parse_mode="HTML")
        return
    if record["chat_id"] != chat_id:
        await update.message.reply_text("❌ That email doesn't belong to you.", parse_mode="HTML")
        return

    db.delete_email(addr)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Menu", callback_data="back_menu")]
    ])
    await update.message.reply_text(f"🗑️ <code>{addr}</code> deleted.", reply_markup=keyboard, parse_mode="HTML")


# ══════════════════════════════════════════════════════════════
#  View Domains
# ══════════════════════════════════════════════════════════════

async def view_domains_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all registered domains with status."""
    query = update.callback_query
    await query.answer()
    await _show_domains(query.edit_message_text, update, context)


async def view_domains_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /mydomains text command."""
    await _show_domains(update.message.reply_text, update, context)


async def _show_domains(send_fn, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shared logic for listing domains."""
    chat_id = str(update.effective_chat.id)
    db = get_db(context)
    domains = db.get_domains_for_chat(chat_id)

    if not domains:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Domain", callback_data="menu_add_domain")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await send_fn("No domains registered yet.", reply_markup=keyboard, parse_mode="HTML")
        return

    lines = ["🌐 <b>Your Domains</b>\n"]
    for d in domains:
        icon = "✅" if d["verified"] else "⏳"
        status = "Verified" if d["verified"] else "Pending"
        emails = db.get_emails_for_domain(chat_id, d["domain"])
        email_count = len(emails)
        lines.append(f"\n{icon} <b>{d['domain']}</b> — {status}")
        lines.append(f"    📧 {email_count} email{'s' if email_count != 1 else ''}")
        if emails:
            for e in emails:
                lines.append(f"    • <code>{e['email']}</code>")

    buttons = [
        [InlineKeyboardButton("➕ Add Domain", callback_data="menu_add_domain")],
    ]
    unverified = [d for d in domains if not d["verified"]]
    if unverified:
        buttons.append([InlineKeyboardButton("✅ Verify Domain", callback_data="menu_verify")])
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")])

    await send_fn("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")


# ══════════════════════════════════════════════════════════════
#  Delete Domain
# ══════════════════════════════════════════════════════════════

async def delete_domain_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all domains as buttons to delete."""
    query = update.callback_query
    await query.answer()

    chat_id = str(update.effective_chat.id)
    db = get_db(context)
    domains = db.get_domains_for_chat(chat_id)

    if not domains:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Domain", callback_data="menu_add_domain")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await query.edit_message_text("No domains to delete.", reply_markup=keyboard, parse_mode="HTML")
        return

    buttons = []
    for d in domains:
        icon = "✅" if d["verified"] else "⏳"
        emails = db.get_emails_for_domain(chat_id, d["domain"])
        label = f"{icon} {d['domain']} ({len(emails)} emails)"
        buttons.append([InlineKeyboardButton(label, callback_data=f"deldomain_{d['domain']}")
        ])
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")])

    await query.edit_message_text(
        "🗑️ <b>Select a domain to delete:</b>\n\n"
        "⚠️ This will also delete all email addresses on that domain.",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def delete_domain_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ask for confirmation before deleting a domain."""
    query = update.callback_query
    await query.answer()

    domain = query.data.replace("deldomain_", "", 1)
    chat_id = str(update.effective_chat.id)
    db = get_db(context)
    emails = db.get_emails_for_domain(chat_id, domain)
    email_count = len(emails)

    warning = f"\n\n📧 <b>{email_count} email{'s' if email_count != 1 else ''}</b> will also be deleted." if email_count else ""

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, delete", callback_data=f"confirm_deldomain_{domain}"),
            InlineKeyboardButton("❌ No, keep it", callback_data="back_menu"),
        ]
    ])
    await query.edit_message_text(
        f"⚠️ Delete domain <code>{domain}</code>?{warning}",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def delete_domain_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Actually delete the domain after confirmation."""
    query = update.callback_query
    await query.answer()

    domain = query.data.replace("confirm_deldomain_", "", 1)
    chat_id = str(update.effective_chat.id)
    db = get_db(context)

    record = db.get_domain(chat_id, domain)
    if not record:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
        ])
        await query.edit_message_text("❌ Domain not found.", reply_markup=keyboard)
        return

    db.delete_domain(chat_id, domain)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 My Domains", callback_data="menu_domains")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
    ])
    await query.edit_message_text(
        f"🗑️ Domain <code>{domain}</code> and all its emails deleted.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# Text command fallback
async def delete_domain_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /deletedomain <domain> text command."""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: <code>/deletedomain example.com</code>", parse_mode="HTML")
        return

    domain = context.args[0].lower().strip()
    chat_id = str(update.effective_chat.id)
    db = get_db(context)
    record = db.get_domain(chat_id, domain)

    if not record:
        await update.message.reply_text(f"❌ <code>{domain}</code> not found.", parse_mode="HTML")
        return

    db.delete_domain(chat_id, domain)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Menu", callback_data="back_menu")]
    ])
    await update.message.reply_text(
        f"🗑️ <code>{domain}</code> and all its emails deleted.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# ══════════════════════════════════════════════════════════════
#  Send Email (Outgoing)
# ══════════════════════════════════════════════════════════════

EMAILS_PER_PAGE = 10

def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def compose_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 1: Show verified domains to pick which domain to send from."""
    query = update.callback_query
    await query.answer()

    chat_id = str(update.effective_chat.id)
    db = get_db(context)
    domains = db.get_domains_for_chat(chat_id)
    verified = [d for d in domains if d["verified"]]

    if not verified:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Domain", callback_data="menu_add_domain")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await query.edit_message_text(
            "📭 You don't have any verified domains yet.\n\n"
            "Add and verify a domain first!",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return ConversationHandler.END

    buttons = [
        [InlineKeyboardButton(f"🌐 {d['domain']}", callback_data=f"send_domain_{d['domain']}")]
        for d in verified
    ]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="back_menu")])

    await query.edit_message_text(
        "✉️ <b>Send Email</b>\n\n"
        "Select the <b>domain</b> to send from:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def compose_select_domain(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 2: User picked a domain — show paginated emails for that domain."""
    query = update.callback_query
    await query.answer()

    domain = query.data.replace("send_domain_", "", 1)
    context.user_data["compose"] = {"domain": domain}

    return await _show_emails_page(update, context, domain, page=0)


async def compose_emails_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle pagination for email selection."""
    query = update.callback_query
    await query.answer()

    # Pattern: send_emails_<domain>_page_<N>
    data = query.data.replace("send_emails_", "", 1)
    parts = data.rsplit("_page_", 1)
    domain = parts[0]
    page = int(parts[1]) if len(parts) == 2 else 0

    return await _show_emails_page(update, context, domain, page)


async def _show_emails_page(update: Update, context, domain: str, page: int) -> int:
    """Show a page of emails for a domain."""
    query = update.callback_query
    chat_id = str(update.effective_chat.id)
    db = get_db(context)
    emails = db.get_emails_for_domain(chat_id, domain)

    if not emails:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📧 Create Email", callback_data="menu_create_email")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_compose")],
        ])
        await query.edit_message_text(
            f"📭 No email addresses on <code>{domain}</code>.\n\n"
            "Create one first!",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return ConversationHandler.END

    total = len(emails)
    total_pages = (total + EMAILS_PER_PAGE - 1) // EMAILS_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    start_idx = page * EMAILS_PER_PAGE
    page_emails = emails[start_idx:start_idx + EMAILS_PER_PAGE]

    buttons = [
        [InlineKeyboardButton(f"📧 {e['email']}", callback_data=f"compose_from_{e['email']}")]
        for e in page_emails
    ]

    # Pagination buttons
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"send_emails_{domain}_page_{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"send_emails_{domain}_page_{page + 1}"))
        buttons.append(nav)

    buttons.append([InlineKeyboardButton("🔙 Back to Domains", callback_data="menu_compose")])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="back_menu")])

    await query.edit_message_text(
        f"✉️ <b>Send Email</b>\n\n"
        f"Domain: <code>{domain}</code>\n\n"
        f"Select the <b>From</b> address ({total} total):",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def compose_select_from(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User selected a 'From' address — ask for the recipient."""
    query = update.callback_query
    await query.answer()

    from_addr = query.data.replace("compose_from_", "", 1)
    context.user_data["compose"] = {"from": from_addr}

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="back_menu")]
    ])
    await query.edit_message_text(
        "✉️ <b>Send Email</b>\n\n"
        f"<b>From:</b> <code>{from_addr}</code>\n\n"
        "Now enter the <b>recipient's email address</b>:\n"
        "<i>(e.g. someone@gmail.com)</i>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    return COMPOSE_WAITING_TO


async def compose_receive_to(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User typed the recipient — validate and ask for subject."""
    to_addr = update.message.text.strip().lower()

    if not EMAIL_REGEX.match(to_addr):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="back_menu")]
        ])
        await update.message.reply_text(
            "❌ Invalid email address.\n\n"
            "Please enter a valid email (e.g. <code>someone@gmail.com</code>):",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return COMPOSE_WAITING_TO

    context.user_data["compose"]["to"] = to_addr

    compose = context.user_data["compose"]
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="back_menu")]
    ])
    await update.message.reply_text(
        "✉️ <b>Send Email</b>\n\n"
        f"<b>From:</b> <code>{compose['from']}</code>\n"
        f"<b>To:</b> <code>{to_addr}</code>\n\n"
        "Enter the <b>subject</b>:",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    return COMPOSE_WAITING_SUBJECT


async def compose_receive_subject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User typed the subject — ask for body."""
    subject = update.message.text.strip()

    if not subject:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="back_menu")]
        ])
        await update.message.reply_text(
            "❌ Subject cannot be empty. Please enter a subject:",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return COMPOSE_WAITING_SUBJECT

    context.user_data["compose"]["subject"] = subject

    compose = context.user_data["compose"]
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="back_menu")]
    ])
    await update.message.reply_text(
        "✉️ <b>Send Email</b>\n\n"
        f"<b>From:</b> <code>{compose['from']}</code>\n"
        f"<b>To:</b> <code>{compose['to']}</code>\n"
        f"<b>Subject:</b> {_escape_html(subject)}\n\n"
        "Now type your <b>message body</b>:",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    return COMPOSE_WAITING_BODY


async def compose_receive_body(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User typed the body — show preview and ask for confirmation."""
    body = update.message.text.strip()

    if not body:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="back_menu")]
        ])
        await update.message.reply_text(
            "❌ Message body cannot be empty. Please type your message:",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return COMPOSE_WAITING_BODY

    context.user_data["compose"]["body"] = body

    compose = context.user_data["compose"]

    # Truncate body preview if too long
    preview_body = _escape_html(body)
    if len(preview_body) > 500:
        preview_body = preview_body[:500] + "\n\n… [truncated in preview]"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Send", callback_data="compose_confirm"),
            InlineKeyboardButton("❌ Cancel", callback_data="compose_cancel"),
        ],
    ])

    await update.message.reply_text(
        "✉️ <b>Review Your Email</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>From:</b> <code>{compose['from']}</code>\n"
        f"<b>To:</b> <code>{compose['to']}</code>\n"
        f"<b>Subject:</b> {_escape_html(compose['subject'])}\n\n"
        "─" * 20 + "\n\n"
        f"{preview_body}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Send this email?",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def compose_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the composed email directly from the VPS."""
    query = update.callback_query
    await query.answer("Checking DNS & sending… ✉️")

    compose = context.user_data.get("compose")
    if not compose or "body" not in compose:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
        ])
        await query.edit_message_text(
            "⚠️ Compose session expired. Please start again.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    email_sender = context.bot_data.get("email_sender")
    if not email_sender:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
        ])
        await query.edit_message_text(
            "⚠️ Email sending is not configured.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    # ── Check DNS records before sending ─────────────────────
    from_domain = compose["from"].split("@")[1]
    server_ip = context.bot_data.get("server_ip", "YOUR_SERVER_IP")

    dns_status = check_all_dns(from_domain, server_ip)

    if not dns_status["send_ready"]:
        missing = []
        if not dns_status["spf_record"]["exists"]:
            missing.append("SPF")
        if not dns_status["dmarc_record"]:
            missing.append("DMARC")
        missing_str = ", ".join(missing)
        dns_help = []
        if not dns_status["spf_record"]["exists"]:
            dns_help.append(
                f"📌 <b>SPF record:</b>\n"
                f"  Type: <code>TXT</code>\n"
                f"  Name: <code>@</code>\n"
                f"  Value: <code>v=spf1 a mx ip4:{server_ip} -all</code>"
            )
        if not dns_status["dmarc_record"]:
            dns_help.append(
                f"📌 <b>DMARC record:</b>\n"
                f"  Type: <code>TXT</code>\n"
                f"  Name: <code>_dmarc</code>\n"
                f"  Value: <code>v=DMARC1; p=none;</code>"
            )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Check Again & Send", callback_data="compose_confirm")],
            [InlineKeyboardButton("❌ Cancel", callback_data="compose_cancel")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await query.edit_message_text(
            f"⚠️ <b>DNS Not Ready for Sending</b>\n\n"
            f"Your domain <code>{from_domain}</code> is missing "
            f"<b>{missing_str}</b> DNS record(s).\n\n"
            "Without these, emails will be rejected or land in spam.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Add these DNS records:\n\n"
            + "\n\n".join(dns_help) + "\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "After adding the records, wait a few minutes for DNS to propagate, "
            "then tap <b>Check Again & Send</b>.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    # ── DNS is good — send the email ─────────────────────────
    await query.edit_message_text(
        "✅ DNS verified!\n⏳ <b>Sending your email…</b>",
        parse_mode="HTML",
    )

    # Send the email
    result = await email_sender.send_email(
        from_addr=compose["from"],
        to_addr=compose["to"],
        subject=compose["subject"],
        body=compose["body"],
    )

    chat_id = str(update.effective_chat.id)
    db = get_db(context)

    if result["success"]:
        # Save to sent history
        email_id = str(uuid.uuid4())
        try:
            db.save_sent_email(
                email_id=email_id,
                chat_id=chat_id,
                from_addr=compose["from"],
                to_addr=compose["to"],
                subject=compose["subject"],
                body=compose["body"],
                status="sent",
            )
        except Exception:
            logger.exception("Failed to save sent email to DB")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✉️ Send Another", callback_data="menu_compose")],
            [InlineKeyboardButton("📤 Sent History", callback_data="menu_sent")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await query.edit_message_text(
            "✅ <b>Email Sent!</b>\n\n"
            f"<b>From:</b> <code>{compose['from']}</code>\n"
            f"<b>To:</b> <code>{compose['to']}</code>\n"
            f"<b>Subject:</b> {_escape_html(compose['subject'])}\n\n"
            "📬 Your email has been delivered.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    else:
        # Save failed attempt
        try:
            db.save_sent_email(
                email_id=str(uuid.uuid4()),
                chat_id=chat_id,
                from_addr=compose["from"],
                to_addr=compose["to"],
                subject=compose["subject"],
                body=compose["body"],
                status="failed",
            )
        except Exception:
            logger.exception("Failed to save failed email to DB")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Try Again", callback_data="menu_compose")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await query.edit_message_text(
            "❌ <b>Failed to Send</b>\n\n"
            f"<b>Error:</b> {_escape_html(result['error'] or 'Unknown error')}",
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    # Clear compose data
    context.user_data.pop("compose", None)


async def compose_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel the compose flow."""
    query = update.callback_query
    await query.answer()
    context.user_data.pop("compose", None)
    return await start(update, context)


# ══════════════════════════════════════════════════════════════
#  Sent History
# ══════════════════════════════════════════════════════════════

async def sent_history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show recent sent emails."""
    query = update.callback_query
    await query.answer()

    chat_id = str(update.effective_chat.id)
    db = get_db(context)
    sent = db.get_sent_emails_for_chat(chat_id, limit=10)

    if not sent:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✉️ Send Email", callback_data="menu_compose")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await query.edit_message_text(
            "📤 <b>Sent History</b>\n\nNo emails sent yet.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    lines = ["📤 <b>Sent History</b> (last 10)\n"]
    for i, em in enumerate(sent, 1):
        status_icon = "✅" if em["status"] == "sent" else "❌"
        subj = _escape_html(em["subject"])
        if len(subj) > 40:
            subj = subj[:40] + "…"
        lines.append(
            f"\n{status_icon} <b>{i}.</b> → <code>{em['to_addr']}</code>\n"
            f"    📝 {subj}\n"
            f"    🕐 {em['created_at'][:16]}"
        )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✉️ Compose Email", callback_data="menu_compose")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
    ])

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n\n… [truncated]"

    await query.edit_message_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# ══════════════════════════════════════════════════════════════
#  Blocked Senders
# ══════════════════════════════════════════════════════════════

BLOCKED_PER_PAGE = 10


async def blocked_senders_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show paginated list of blocked senders."""
    query = update.callback_query
    await query.answer()
    await _show_blocked_page(query.edit_message_text, update, context, page=0)


async def blocked_senders_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle pagination for blocked senders list."""
    query = update.callback_query
    await query.answer()
    # Pattern: blocked_page_<N>
    page = int(query.data.replace("blocked_page_", "", 1))
    await _show_blocked_page(query.edit_message_text, update, context, page=page)


async def _show_blocked_page(send_fn, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int) -> None:
    """Shared logic for displaying blocked senders list."""
    chat_id = str(update.effective_chat.id)
    db = get_db(context)
    blocked = db.get_blocked_senders(chat_id)

    if not blocked:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Block a Sender", callback_data="menu_block_sender")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await send_fn(
            "🚫 <b>Blocked Senders</b>\n\nNo senders blocked yet.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    total = len(blocked)
    total_pages = (total + BLOCKED_PER_PAGE - 1) // BLOCKED_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    start_idx = page * BLOCKED_PER_PAGE
    page_items = blocked[start_idx:start_idx + BLOCKED_PER_PAGE]

    lines = [f"🚫 <b>Blocked Senders</b> ({total} total)\n"]
    for i, item in enumerate(page_items, start_idx + 1):
        lines.append(f"{i}. <code>{item['sender']}</code>")

    buttons = [
        [InlineKeyboardButton(f"🔓 {item['sender']}", callback_data=f"unblock_{item['sender']}")]
        for item in page_items
    ]

    # Pagination
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"blocked_page_{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"blocked_page_{page + 1}"))
        buttons.append(nav)

    buttons.append([InlineKeyboardButton("➕ Block a Sender", callback_data="menu_block_sender")])
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")])

    await send_fn(
        "\n".join(lines) + "\n\nTap a sender to <b>unblock</b> them:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def block_sender_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask user to type the email or domain to block."""
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="menu_blocked")]
    ])
    await query.edit_message_text(
        "🚫 <b>Block a Sender</b>\n\n"
        "Send me the email address or domain to block:\n\n"
        "• <code>spam@example.com</code> — blocks one address\n"
        "• <code>@example.com</code> — blocks entire domain",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    return WAITING_BLOCK_SENDER


async def block_sender_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process the email/domain the user typed to block."""
    text = update.message.text.strip().lower()

    # Validate: must be an email or @domain
    is_domain = text.startswith("@") and "." in text
    is_email = EMAIL_REGEX.match(text)

    if not is_domain and not is_email:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Try Again", callback_data="menu_block_sender")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await update.message.reply_text(
            "❌ Invalid format.\n\n"
            "Use an email: <code>spam@example.com</code>\n"
            "Or a domain: <code>@example.com</code>",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return ConversationHandler.END

    chat_id = str(update.effective_chat.id)
    db = get_db(context)

    if not db.add_blocked_sender(chat_id, text):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 Blocked List", callback_data="menu_blocked")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await update.message.reply_text(
            f"⚠️ <code>{text}</code> is already blocked.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return ConversationHandler.END

    label = "domain" if is_domain else "sender"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 View Blocked List", callback_data="menu_blocked")],
        [InlineKeyboardButton("➕ Block Another", callback_data="menu_block_sender")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
    ])
    await update.message.reply_text(
        f"✅ {label.capitalize()} <code>{text}</code> blocked!\n\n"
        "Emails from this sender will no longer be forwarded.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def block_from_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Quick-block a sender from the incoming email notification button."""
    query = update.callback_query
    await query.answer()

    sender = query.data.replace("block_", "", 1).strip().lower()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, block", callback_data=f"confirm_block_{sender}"),
            InlineKeyboardButton("❌ No, cancel", callback_data="back_menu"),
        ],
        [
            InlineKeyboardButton(f"🌐 Block @{sender.split('@')[-1]}", callback_data=f"confirm_block_@{sender.split('@')[-1]}"),
        ] if "@" in sender else [],
    ])
    # Filter out empty rows
    keyboard = InlineKeyboardMarkup([row for row in keyboard.inline_keyboard if row])

    await query.edit_message_text(
        f"🚫 <b>Block Sender</b>\n\n"
        f"Block <code>{sender}</code>?\n\n"
        "You will no longer receive emails from this sender.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def block_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm and execute blocking a sender."""
    query = update.callback_query
    await query.answer()

    sender = query.data.replace("confirm_block_", "", 1).strip().lower()
    chat_id = str(update.effective_chat.id)
    db = get_db(context)

    if not db.add_blocked_sender(chat_id, sender):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 Blocked List", callback_data="menu_blocked")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await query.edit_message_text(
            f"⚠️ <code>{sender}</code> is already blocked.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    is_domain = sender.startswith("@")
    label = "Domain" if is_domain else "Sender"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 View Blocked List", callback_data="menu_blocked")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
    ])
    await query.edit_message_text(
        f"✅ {label} <code>{sender}</code> blocked!\n\n"
        "Emails from this sender will no longer be forwarded.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def unblock_sender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ask for confirmation before unblocking."""
    query = update.callback_query
    await query.answer()

    sender = query.data.replace("unblock_", "", 1)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, unblock", callback_data=f"confirm_unblock_{sender}"),
            InlineKeyboardButton("❌ No, keep blocked", callback_data="menu_blocked"),
        ]
    ])
    await query.edit_message_text(
        f"🔓 <b>Unblock Sender</b>\n\n"
        f"Unblock <code>{sender}</code>?\n\n"
        "You will start receiving emails from this sender again.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def unblock_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Execute unblocking a sender."""
    query = update.callback_query
    await query.answer()

    sender = query.data.replace("confirm_unblock_", "", 1)
    chat_id = str(update.effective_chat.id)
    db = get_db(context)

    if not db.remove_blocked_sender(chat_id, sender):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 Blocked List", callback_data="menu_blocked")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
        ])
        await query.edit_message_text(
            f"⚠️ <code>{sender}</code> was not found in your blocklist.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Blocked List", callback_data="menu_blocked")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
    ])
    await query.edit_message_text(
        f"🔓 <code>{sender}</code> unblocked!\n\n"
        "You will now receive emails from this sender.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# Text command fallback
async def block_sender_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /blocksender <email|@domain> text command."""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "Usage:\n"
            "<code>/blocksender spam@example.com</code>\n"
            "<code>/blocksender @spamdomain.com</code>",
            parse_mode="HTML",
        )
        return

    sender = context.args[0].lower().strip()
    is_domain = sender.startswith("@") and "." in sender
    is_email = EMAIL_REGEX.match(sender)

    if not is_domain and not is_email:
        await update.message.reply_text(
            "❌ Invalid format. Use an email or @domain.",
            parse_mode="HTML",
        )
        return

    chat_id = str(update.effective_chat.id)
    db = get_db(context)

    if not db.add_blocked_sender(chat_id, sender):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Menu", callback_data="back_menu")]
        ])
        await update.message.reply_text(
            f"⚠️ <code>{sender}</code> is already blocked.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    label = "Domain" if is_domain else "Sender"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Blocked List", callback_data="menu_blocked")],
        [InlineKeyboardButton("🔙 Menu", callback_data="back_menu")],
    ])
    await update.message.reply_text(
        f"✅ {label} <code>{sender}</code> blocked!",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# ══════════════════════════════════════════════════════════════
#  Error handler
# ══════════════════════════════════════════════════════════════

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors caused by updates."""
    logger.error("Exception while handling update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("⚠️ An unexpected error occurred. Try again later.")

