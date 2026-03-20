# SaveVideoClips Bot 🎬

A Telegram bot that downloads videos from any social media platform using yt-dlp.

**Supported platforms:** Twitter/X • Instagram • YouTube • Reddit • Facebook • TikTok & more

## Features

- Send any video URL — no commands needed, it just works
- HD / SD quality selection via inline buttons
- Auto-retries with lower quality if video exceeds Telegram's 50 MB limit
- Auto-deletes downloaded files to save disk space
- Basic stats tracking (users, downloads, errors)

## Setup

### 1. Create a Telegram Bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the bot token you receive

### 2. Run Locally

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/save-video-clips-bot.git
cd save-video-clips-bot

# Install dependencies
pip install -r requirements.txt

# Set your bot token
export TELEGRAM_BOT_TOKEN="your-token-here"

# Run the bot
python bot.py
```

### 3. Deploy on Render

1. Push this repo to GitHub
2. Go to [render.com](https://render.com) → **New** → **Background Worker**
3. Connect your GitHub repo (`save-video-clips-bot`)
4. Render will auto-detect `render.yaml` settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
5. Add environment variable: `TELEGRAM_BOT_TOKEN` = your bot token
6. Click **Create Background Worker**

The bot will start polling for messages automatically.

## Commands

| Command  | Description                    |
|----------|--------------------------------|
| /start   | Show welcome message           |
| /help    | Show usage instructions        |
| /stats   | Show bot statistics            |

## License

MIT
