# 📬 Email Telegram Bot (Self-Hosted)

A Telegram bot that lets you **receive and send** emails from your own custom domain directly in Telegram. **No AWS, no third-party relay needed** — runs everything from your VPS.

## ✨ Features

- 📧 **Receive emails** from custom domains directly in Telegram
- ✉️ **Send emails** directly from your domain addresses (no relay needed)
- 📎 **Attachment support** — photos, documents, and files forwarded to chat
- 🌐 **Full email viewer** — view complete emails via Telegraph (telegra.ph) with images
- 🔒 **Secure links** — Telegraph URLs use random UUIDs (unguessable)
- 📤 **Sent history** — track all outgoing emails with status
- 🗂️ **Multi-domain** — manage unlimited domains and email addresses
- 🖱️ **Button UI** — interactive menus for domain & email management

## 🤖 Live Demo

Want to try it out? A live instance is already deployed and running:

👉 **[@gajaman234_bot](https://t.me/gajaman234_bot)**

Open the bot in Telegram and send `/start` to get started!

## How It Works

```
                    RECEIVING
Sender → MX Record → Your VPS (SMTP :25) → Bot → Telegram
                                             ↓
                                       Telegraph Page
                                   (View Full Email + Images)

                    SENDING
Telegram → Bot → Resolve recipient MX → Deliver directly → Recipient Inbox
```

### Receiving Emails
1. **Add your domain** to the bot
2. **Set DNS records** (A record + MX record pointing to your server)
3. **Verify** the domain through the bot
4. **Create email addresses** on your domain
5. **Receive emails** forwarded to your Telegram chat 🎉
6. **View full emails** by tapping the "🌐 View Full Email" button

### Sending Emails
1. Tap **✉️ Send Email** in the bot menu
2. **Choose your domain** → **Select From address**
3. **Enter recipient** → **Subject** → **Body**
4. **Preview & Send** — delivered directly from your VPS ✉️

---

## Prerequisites

- **VPS/Server** with a public IP and **port 25 open** (both inbound and outbound)
- **Domain** with access to DNS settings
- **Python 3.11+**

---

## Setup Guide

### 1. Create a Telegram Bot

1. Open Telegram → talk to [@BotFather](https://t.me/BotFather)
2. Send `/newbot`, pick a name and username
3. Copy the **bot token**

### 2. Clone the Repository

```bash
git clone https://github.com/nithilamandiw/telegram-mail-bot.git
cd telegram-mail-bot
```

### 3. Install Dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r bot/requirements.txt
```

### 4. Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:
```env
TELEGRAM_BOT_TOKEN=123456:ABC-your-bot-token
SERVER_IP=203.0.113.10
SMTP_HOST=0.0.0.0
SMTP_PORT=25
```

### 5. Open Port 25 on Your VPS

> ⚠️ **Port 25 must be open both inbound (receiving) and outbound (sending).**

#### Inbound (for receiving emails)

**On your VPS provider's dashboard** (e.g. AWS Lightsail, DigitalOcean, etc.):

1. Go to your instance → **Networking** / **Firewall** settings
2. Add a firewall rule:

| Protocol | Port | Direction | Source |
|---|---|---|---|
| **TCP** | **25** | **Inbound** | Any (`0.0.0.0/0`) |

**Also open port 25 on the OS firewall:**
```bash
sudo ufw allow 25/tcp
```

#### Outbound (for sending emails)

> ⚠️ **AWS blocks outbound port 25 by default.** You must request removal before sending emails will work.

**For AWS Lightsail / EC2:**

1. Go to the [AWS SMTP Limit Removal Form](https://aws.amazon.com/forms/ec2-email-limit-rdns-request)
2. Fill in:
   - **Email address**: your AWS account email
   - **Use case**: "I run a self-hosted email server for my personal domain"
   - **Elastic IP / Instance IP**: your server's public IP
   - ✅ Check "I agree to only send to people who've requested my mail"
3. Submit — AWS usually approves within **24 hours**

**Test if outbound port 25 is open:**
```bash
nc -zv gmail-smtp-in.l.google.com 25 -w 5
```
- ✅ `Connection succeeded` → sending will work
- ❌ `Timed out` → outbound port 25 is still blocked

### 6. Run the Bot

**Quick test (manual):**
```bash
# Port 25 requires root on Linux
sudo /home/ubuntu/telegram-mail-bot/venv/bin/python bot/main.py
```

**Production (PM2 — runs 24/7, auto-restarts):**
```bash
# Install PM2 if not installed
sudo npm install -g pm2

# Start the bot
sudo pm2 start ecosystem.config.js

# Save & enable auto-start on reboot
sudo pm2 save
sudo pm2 startup
```

**Useful PM2 commands:**
```bash
sudo pm2 status              # Check if running
sudo pm2 logs email-bot      # View logs
sudo pm2 restart email-bot   # Restart after code changes
```

### 7. DNS Setup

> 💡 Once the bot is running, use `/adddomain` to register your domain. The bot will show you exactly which DNS records to add and let you verify them with the **🔍 Check DNS** button.

#### For Receiving Emails

The bot gives you two DNS records to add:

| Step | Type | Host | Value | Priority |
|---|---|---|---|---|
| 1 | **A** | `mail` | `<your-server-ip>` | — |
| 2 | **MX** | `@` | `mail.yourdomain.com` | 10 |

> ⚠️ MX records require a **hostname**, not an IP address. That's why the A record is needed first.

#### For Sending Emails (Recommended)

To improve deliverability and avoid spam folders, add these DNS records:

| Type | Host | Value | Purpose |
|---|---|---|---|
| **TXT** | `@` | `v=spf1 a mx ip4:<your-server-ip> -all` | SPF — authorizes your VPS to send |
| **TXT** | `_dmarc` | `v=DMARC1; p=none;` | DMARC — email authentication policy |
| **PTR** | *(set via VPS provider)* | `mail.yourdomain.com` | Reverse DNS — proves IP ownership |

> 💡 **SPF is the most important one.** It tells recipient mail servers that your VPS IP is authorized to send emails for your domain.

---

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message & main menu |
| `/adddomain <domain>` | Register a domain, get MX instructions |
| `/verifydomain <domain>` | Mark domain as active |
| `/createemail <email>` | Create an email address |
| `/listemails` | List all your emails and domains |
| `/deletemail <email>` | Delete an email address |
| `/mydomains` | View all registered domains |
| `/deletedomain <domain>` | Delete a domain and its emails |
| `/help` | Show all commands |

### Button Menu

| Button | Action |
|---|---|
| ➕ Add Domain | Register a new domain |
| ✅ Verify Domain | Verify DNS records |
| 🌐 My Domains | View all domains & status |
| 🗑️ Delete Domain | Remove a domain |
| 📧 Create Email | Create a new email address |
| 📋 My Emails | List all email addresses |
| ✉️ Send Email | **Send an email from your domain** |
| 📤 Sent History | **View sent email history** |
| 🗑️ Delete Email | Remove an email address |
| ❓ Help | Show help guide |

---

## Usage Flow

### Receiving
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

### Sending
```
Tap "✉️ Send Email"
  → Select From: hello@example.com     ← your own domain email
  → Enter To: someone@gmail.com
  → Enter Subject: Hello!
  → Type your message
  → Preview & confirm
  → ✅ Email sent directly from your VPS!
```

---

## Architecture

```
┌─────────────┐         ┌──────────────────────┐
│  Incoming    │──MX────▶│  Your VPS            │
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
                        │  ┌────────────────┐  │         ┌──────────────┐
                        │  │ Telegram Bot   │  │         │  Recipient   │
                        │  │ (polling)      │  │         │  Mail Server │
                        │  └───────┬────────┘  │         └──────▲───────┘
                        │          │           │                │
                        │  ┌───────▼────────┐  │   MX resolve  │
                        │  │ Email Sender   │──────────────────┘
                        │  │ (aiosmtplib)   │  │  Direct delivery
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
│   ├── email_sender.py       # Outgoing email — direct MX delivery
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
| Sent email lands in spam | Add SPF TXT record to your domain DNS |
| Outbound port 25 blocked | Some VPS providers block this — contact support |
| Send fails with "connection refused" | Recipient server may be blocking your IP |

---

## License

MIT
