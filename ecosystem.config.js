module.exports = {
  apps: [
    {
      name: "email-bot",
      script: "bot/main.py",
      interpreter: "/home/ubuntu/telegram-mail-bot/venv/bin/python3",
      cwd: "/home/ubuntu/telegram-mail-bot",
      env: {
        DOTENV_PATH: "/home/ubuntu/telegram-mail-bot/.env",
      },
      watch: false,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 5000,
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      error_file: "/home/ubuntu/telegram-mail-bot/logs/error.log",
      out_file: "/home/ubuntu/telegram-mail-bot/logs/output.log",
      merge_logs: true,
    },
  ],
};
