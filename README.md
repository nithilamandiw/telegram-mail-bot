# 📬 Email Telegram Bot (Self-Hosted)

A Telegram bot that lets you receive emails from your own custom domain directly in Telegram. **No AWS needed** — runs a built-in SMTP server alongside the bot.

## ✨ Features

- 📧 **Receive emails** from custom domains directly in Telegram
- 📎 **Attachment support** — photos, documents, and files forwarded to chat
- 🌐 **Full email viewer** — view complete emails via Telegraph (telegra.ph) with images
- 🔒 **Secure links** — Telegraph URLs use random UUIDs (unguessable)
- 🗂️ **Multi-domain** — manage unlimited domains and email addresses
- 🖱️ **Button UI** — interactive menus for domain & email management

## How It Works

```
Your Domain → MX Record → Your Server (SMTP :25) → Bot → Telegram
                                                    ↓
                                              Telegraph Page
                                          (View Full Email + Images)
```

1. **Add your domain** to the bot
2. **Set DNS records** (A record + MX record pointing to your server)
3. **Verify** the domain through the bot
4. **Create email addresses** on your domain
5. **Receive emails** forwarded to your Telegram chat 🎉
6. **View full emails** by tapping the "🌐 View Full Email" button

---

## Prerequisites

- **VPS/Server** with a public IP and **port 25 open**
- **Domain** with access to DNS settings
- **Python 3.11+**

---

## Setup Guide

### 1. Create a Telegram Bot

1. Open Telegram → talk to [@BotFather](https://t.me/BotFather)
2. Send `/newbot`, pick a name and username
3. Copy the **bot token**

### 2. Install Dependencies

```bash
cd bot
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:
```
TELEGRAM_BOT_TOKEN=123456:ABC-your-bot-token
SERVER_IP=203.0.113.10
SMTP_HOST=0.0.0.0
SMTP_PORT=25
```

### 4. Open Port 25 on Your VPS

> ⚠️ **This is required!** Your VPS must allow incoming traffic on **port 25 (TCP)** for emails to arrive.

**On your VPS provider's dashboard** (e.g. AWS Lightsail, DigitalOcean, etc.):

1. Go to your instance → **Networking** / **Firewall** settings
2. Add a new firewall rule:

| Protocol | Port | Source |
|---|---|---|
| **TCP** | **25** | **Any IPv4 address** (`0.0.0.0/0`) |

**Example (AWS Lightsail):**
- Instance → Networking tab → IPv4 Firewall → **+ Add rule**
- Application: `Custom`, Protocol: `TCP`, Port: `25`, Restricted to: `Any IPv4 address`

**Also open port 25 on the OS firewall:**
```bash
sudo ufw allow 25/tcp
```

### 5. Run the Bot

```bash
# Port 25 requires root on Linux
sudo python bot/main.py
```

Or use a non-privileged port and redirect with iptables:
```bash
# Run on port 2525
SMTP_PORT=2525 python bot/main.py

# Redirect port 25 → 2525
sudo iptables -t nat -A PREROUTING -p tcp --dport 25 -j REDIRECT --to-port 2525
```

---

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/adddomain <domain>` | Register a domain, get MX instructions |
| `/verifydomain <domain>` | Mark domain as active |
| `/createemail <email>` | Create an email address |
| `/listemails` | List all your emails and domains |
| `/deletemail <email>` | Delete an email address |
| `/help` | Show all commands |

---

## DNS Setup

When you run `/adddomain`, the bot gives you two DNS records to add:

| Step | Type | Host | Value | Priority |
|---|---|---|---|---|
| 1 | **A** | `mail` | `<your-server-ip>` | — |
| 2 | **MX** | `@` | `mail.yourdomain.com` | 10 |

> ⚠️ MX records require a **hostname**, not an IP address. That's why the A record is needed first.

---

## Usage Flow

```
/adddomain example.com
  → Bot shows A record + MX record instructions

(Add both DNS records in your provider)

/verifydomain example.com
  → Domain is now active

/createemail hello@example.com
  → Email is live!

(Someone sends email to hello@example.com)
  → You receive it in Telegram! 📧
```

---

## Architecture

```
┌─────────────┐         ┌──────────────────────┐
│  Incoming    │──MX────▶│  Your Server         │
│  Email       │         │                      │
└─────────────┘         │  ┌────────────────┐  │
                        │  │ SMTP Server    │  │
                        │  │ (aiosmtpd:25)  │  │
                        │  └───────┬────────┘  │
                        │          │           │
                        │  ┌───────▼────────┐  │
                        │  │ Parse Email    │  │
                        │  │ Store in SQLite│  │
                        │  └──┬─────────┬───┘  │
                        │     │         │      │
                        │  ┌──▼───┐ ┌───▼───┐  │
                        │  │Telegr│ │Telegra│  │
                        │  │am API│ │ph API │  │
                        │  │→Chat │ │→Page  │  │
                        │  └──────┘ └───────┘  │
                        │                      │
                        │  ┌────────────────┐  │
                        │  │ Telegram Bot   │  │
                        │  │ (polling)      │  │
                        │  └────────────────┘  │
                        └──────────────────────┘
```

---

## Project Structure

```
email-telegram-bot/
├── bot/
│   ├── main.py               # Entry point — starts bot + SMTP
│   ├── handlers.py           # Telegram command & button handlers
│   ├── smtp_server.py        # Built-in SMTP server (aiosmtpd)
│   ├── telegraph_publisher.py # Publishes emails to Telegraph
│   ├── database.py           # SQLite database layer
│   └── requirements.txt
├── data/
│   └── email_bot.db          # SQLite database (auto-created)
├── ecosystem.config.js       # PM2 config for deployment
├── .env.example
└── README.md
```

---

## Deployment

### Option A: PM2 (Recommended)

```bash
# Install PM2
sudo npm install -g pm2

# Start the bot (sudo needed for port 25)
sudo pm2 start ecosystem.config.js

# Auto-start on reboot
sudo pm2 save
sudo pm2 startup

# View logs
sudo pm2 logs email-bot
```

### Option B: systemd

Create `/etc/systemd/system/email-bot.service`:

```ini
[Unit]
Description=Email Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/path/to/email-telegram-bot
ExecStart=/usr/bin/python3 bot/main.py
Restart=always
RestartSec=5
EnvironmentFile=/path/to/email-telegram-bot/.env

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable email-bot
sudo systemctl start email-bot
```

---

## Troubleshooting

| Issue | Solution |
|---|---|
| Bot doesn't respond | Check `TELEGRAM_BOT_TOKEN` is correct |
| Port 25 permission denied | Run with `sudo` or use iptables redirect |
| Emails not arriving | Check both A + MX records, DNS propagation (up to 48h) |
| Port 25 blocked | Contact your VPS provider to unblock SMTP |
| Connection refused | Check firewall: `sudo ufw allow 25/tcp` |

---

## License

MIT
