"""
Telegram Bot Command Handlers — Interactive Button UI

Uses InlineKeyboardButtons and ConversationHandler for a polished,
button-driven user experience. No need to type commands manually.
"""

import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from database import Database

logger = logging.getLogger(__name__)

DOMAIN_REGEX = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z]{2,})+$")
EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

# ── Conversation states ──────────────────────────────────────
WAITING_DOMAIN = 1
WAITING_EMAIL = 2


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
            InlineKeyboardButton("🗑️ Delete Email", callback_data="menu_delete"),
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
        "Receive emails from your own domain right here in Telegram!\n\n"
        "<b>How it works:</b>\n"
        "1️⃣ Add your domain\n"
        "2️⃣ Set DNS records (A + MX)\n"
        "3️⃣ Verify the domain\n"
        "4️⃣ Create email addresses\n"
        "5️⃣ Receive emails here 🎉\n\n"
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
        "🗑️ <b>Delete Email</b> — Remove an email\n\n"
        "You can also type commands:\n"
        "<code>/start</code> — Main menu\n"
        "<code>/adddomain example.com</code>\n"
        "<code>/verifydomain example.com</code>\n"
        "<code>/createemail hello@example.com</code>\n"
        "<code>/listemails</code>\n"
        "<code>/deletemail hello@example.com</code>"
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

    db.add_domain(chat_id, domain)
    server_ip = context.bot_data.get("server_ip", "YOUR_SERVER_IP")

    text = (
        f"✅ Domain <code>{domain}</code> registered!\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
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
        "⏳ After adding DNS records, click <b>Verify</b> below."
    )
    keyboard = InlineKeyboardMarkup([
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
#  Error handler
# ══════════════════════════════════════════════════════════════

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors caused by updates."""
    logger.error("Exception while handling update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("⚠️ An unexpected error occurred. Try again later.")
