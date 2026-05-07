"""
Email Telegram Bot — Entry Point (self-hosted, no AWS)

Runs the Telegram bot + a built-in SMTP server side by side.
Uses ConversationHandler for button-driven multi-step flows.
"""

import logging
import os
import sys

from dotenv import load_dotenv
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from database import Database
from email_sender import EmailSender
from handlers import (
    COMPOSE_WAITING_BODY,
    COMPOSE_WAITING_SUBJECT,
    COMPOSE_WAITING_TO,
    WAITING_DOMAIN,
    WAITING_EMAIL,
    add_domain_command,
    add_domain_prompt,
    add_domain_receive,
    back_to_menu,
    compose_cancel,
    compose_confirm,
    compose_emails_page,
    compose_menu,
    compose_select_domain,
    dns_check_callback,
    compose_receive_body,
    compose_receive_subject,
    compose_receive_to,
    compose_select_from,
    create_email_command,
    create_email_menu,
    create_email_on_domain,
    create_email_receive,
    delete_domain_command,
    delete_domain_confirm,
    delete_domain_execute,
    delete_domain_menu,
    delete_email_command,
    delete_email_confirm,
    delete_email_execute,
    delete_email_menu,
    error_handler,
    help_callback,
    list_emails_callback,
    list_emails_command,
    sent_history_callback,
    start,
    verify_domain_action,
    verify_domain_command,
    verify_menu,
    view_domains_callback,
    view_domains_command,
)
from smtp_server import start_smtp_server
from telegraph_publisher import TelegraphClient

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SMTP_HOST = os.getenv("SMTP_HOST", "0.0.0.0")
SMTP_PORT = int(os.getenv("SMTP_PORT", "25"))
SERVER_IP = os.getenv("SERVER_IP", "YOUR_SERVER_IP")

if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN is not set. Exiting.")
    sys.exit(1)


def main() -> None:
    """Start the Telegram bot and SMTP server."""
    db = Database()
    logger.info("Database initialized at %s", db.db_path)

    # ── Initialize Telegraph client ──────────────────────────
    telegraph_client = TelegraphClient()
    logger.info("Telegraph client ready (will create account on first email)")

    # ── Initialize outgoing email sender (direct delivery) ───
    email_sender = EmailSender()
    logger.info("Outgoing email sender ready (direct delivery from VPS)")

    # ── Start SMTP server (background thread) ────────────────
    smtp_controller = start_smtp_server(
        bot_token=TELEGRAM_BOT_TOKEN,
        db=db,
        host=SMTP_HOST,
        port=SMTP_PORT,
        telegraph_client=telegraph_client,
    )

    # ── Build Telegram bot ───────────────────────────────────
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.bot_data["db"] = db
    application.bot_data["server_ip"] = SERVER_IP
    application.bot_data["email_sender"] = email_sender

    # ── Conversation: Add Domain ─────────────────────────────
    add_domain_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_domain_prompt, pattern="^menu_add_domain$"),
        ],
        states={
            WAITING_DOMAIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_domain_receive),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(back_to_menu, pattern="^back_menu$"),
            CommandHandler("start", start),
        ],
        per_message=False,
    )

    # ── Conversation: Create Email ───────────────────────────
    create_email_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(create_email_on_domain, pattern=r"^create_on_"),
        ],
        states={
            WAITING_EMAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_email_receive),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(back_to_menu, pattern="^back_menu$"),
            CommandHandler("start", start),
        ],
        per_message=False,
    )

    # ── Conversation: Compose Email (Send) ───────────────────
    compose_email_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(compose_select_from, pattern=r"^compose_from_"),
        ],
        states={
            COMPOSE_WAITING_TO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, compose_receive_to),
            ],
            COMPOSE_WAITING_SUBJECT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, compose_receive_subject),
            ],
            COMPOSE_WAITING_BODY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, compose_receive_body),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(back_to_menu, pattern="^back_menu$"),
            CommandHandler("start", start),
        ],
        per_message=False,
    )

    # ── Register handlers (order matters!) ───────────────────

    # Conversation handlers first (they have priority for their patterns)
    application.add_handler(add_domain_conv)
    application.add_handler(create_email_conv)
    application.add_handler(compose_email_conv)

    # /start command
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))

    # Text command fallbacks
    application.add_handler(CommandHandler("adddomain", add_domain_command))
    application.add_handler(CommandHandler("verifydomain", verify_domain_command))
    application.add_handler(CommandHandler("createemail", create_email_command))
    application.add_handler(CommandHandler("listemails", list_emails_command))
    application.add_handler(CommandHandler("deletemail", delete_email_command))
    application.add_handler(CommandHandler("mydomains", view_domains_command))
    application.add_handler(CommandHandler("deletedomain", delete_domain_command))

    # Button callbacks
    application.add_handler(CallbackQueryHandler(back_to_menu, pattern="^back_menu$"))
    application.add_handler(CallbackQueryHandler(help_callback, pattern="^menu_help$"))
    application.add_handler(CallbackQueryHandler(verify_menu, pattern="^menu_verify$"))
    application.add_handler(CallbackQueryHandler(dns_check_callback, pattern=r"^dnscheck_"))
    application.add_handler(CallbackQueryHandler(verify_domain_action, pattern=r"^verify_"))
    application.add_handler(CallbackQueryHandler(view_domains_callback, pattern="^menu_domains$"))
    application.add_handler(CallbackQueryHandler(delete_domain_menu, pattern="^menu_del_domain$"))
    application.add_handler(CallbackQueryHandler(delete_domain_confirm, pattern=r"^deldomain_"))
    application.add_handler(CallbackQueryHandler(delete_domain_execute, pattern=r"^confirm_deldomain_"))
    application.add_handler(CallbackQueryHandler(create_email_menu, pattern="^menu_create_email$"))
    application.add_handler(CallbackQueryHandler(list_emails_callback, pattern="^menu_list$"))
    application.add_handler(CallbackQueryHandler(delete_email_menu, pattern="^menu_delete$"))
    application.add_handler(CallbackQueryHandler(delete_email_confirm, pattern=r"^del_"))
    application.add_handler(CallbackQueryHandler(delete_email_execute, pattern=r"^confirm_del_"))

    # Compose email callbacks
    application.add_handler(CallbackQueryHandler(compose_menu, pattern="^menu_compose$"))
    application.add_handler(CallbackQueryHandler(compose_select_domain, pattern=r"^send_domain_"))
    application.add_handler(CallbackQueryHandler(compose_emails_page, pattern=r"^send_emails_"))
    application.add_handler(CallbackQueryHandler(compose_confirm, pattern="^compose_confirm$"))
    application.add_handler(CallbackQueryHandler(compose_cancel, pattern="^compose_cancel$"))
    application.add_handler(CallbackQueryHandler(sent_history_callback, pattern="^menu_sent$"))

    # Noop handler (for pagination page number display button)
    application.add_handler(CallbackQueryHandler(
        lambda update, context: update.callback_query.answer(),
        pattern="^noop$",
    ))

    # Error handler
    application.add_error_handler(error_handler)

    logger.info("Bot starting in polling mode...")

    try:
        application.run_polling(drop_pending_updates=True)
    finally:
        smtp_controller.stop()
        logger.info("SMTP server stopped.")


if __name__ == "__main__":
    main()
