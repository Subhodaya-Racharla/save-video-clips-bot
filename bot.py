import os
import re
import logging
import asyncio
import threading
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
import yt_dlp

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stats (in-memory; resets on restart)
# ---------------------------------------------------------------------------
stats = {"users": set(), "downloads": 0, "errors": 0}

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
DOWNLOAD_DIR = Path(__file__).parent / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)
TELEGRAM_MAX_SIZE = 50 * 1024 * 1024  # 50 MB

URL_REGEX = re.compile(r"https?://[^\s<>\"']+")

WELCOME_MESSAGE = (
    "Hey! I'm SaveVideoClips Bot 🎬\n\n"
    "Just send me any video link and I'll download it for you.\n\n"
    "Supported: Twitter/X • Instagram • YouTube • Reddit • Facebook & more\n\n"
    "Try it — paste a link right now!"
)

HELP_MESSAGE = (
    "📖 *How to use this bot*\n\n"
    "1️⃣ Send me any video link\n"
    "2️⃣ Choose quality (HD or SD)\n"
    "3️⃣ I'll download and send the video!\n\n"
    "*Supported platforms:*\n"
    "Twitter/X • Instagram • YouTube • Reddit • Facebook • TikTok • and many more\n\n"
    "*Notes:*\n"
    "• Telegram limits files to 50 MB. If a video is larger I'll try a lower quality automatically.\n"
    "• Some private or age-restricted videos may not be downloadable.\n\n"
    "Just paste a link to get started! 🎬"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _yt_dlp_opts(quality: str, output_path: str) -> dict:
    """Return yt-dlp option dicts for the requested quality."""
    common = {
        "outtmpl": output_path,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "merge_output_format": "mp4",
        "socket_timeout": 30,
    }
    if quality == "hd":
        common["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    else:
        common["format"] = (
            "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/"
            "best[height<=480][ext=mp4]/worst[ext=mp4]/worst"
        )
    return common


async def _download_video(url: str, quality: str) -> Path | None:
    """Download video with yt-dlp and return the file path."""
    suffix = datetime.now().strftime("%Y%m%d%H%M%S%f")
    output_path = str(DOWNLOAD_DIR / f"video_{suffix}.%(ext)s")
    opts = _yt_dlp_opts(quality, output_path)

    loop = asyncio.get_running_loop()

    def _do_download():
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)

    try:
        filename = await loop.run_in_executor(None, _do_download)
    except Exception:
        return None

    path = Path(filename)
    # yt-dlp may change the extension after merging
    if not path.exists():
        for p in DOWNLOAD_DIR.glob(f"video_{suffix}.*"):
            if p.suffix != ".part":
                return p
        return None
    return path


def _cleanup(path: Path | None):
    """Delete a downloaded file if it exists."""
    try:
        if path and path.exists():
            path.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats["users"].add(update.effective_user.id)
    await update.message.reply_text(WELCOME_MESSAGE)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats["users"].add(update.effective_user.id)
    await update.message.reply_text(HELP_MESSAGE, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle any incoming text message — detect URLs automatically."""
    stats["users"].add(update.effective_user.id)
    text = update.message.text or ""

    urls = URL_REGEX.findall(text)
    if not urls:
        await update.message.reply_text(
            "Just send me a video link and I'll download it for you! 🎬"
        )
        return

    url = urls[0]  # process the first URL found

    keyboard = [
        [
            InlineKeyboardButton("🎬 HD", callback_data=f"hd|{url}"),
            InlineKeyboardButton("📱 SD", callback_data=f"sd|{url}"),
        ]
    ]
    await update.message.reply_text(
        "Choose video quality:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def quality_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle quality selection button press."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if "|" not in data:
        return
    quality, url = data.split("|", 1)

    status_msg = await query.edit_message_text("⏳ Downloading...")

    path = await _download_video(url, quality)

    if path is None:
        stats["errors"] += 1
        await status_msg.edit_text(
            "❌ Couldn't download that video. The link may be invalid, "
            "the site unsupported, or the video private/restricted."
        )
        return

    # Check file size
    file_size = path.stat().st_size
    if file_size > TELEGRAM_MAX_SIZE:
        logger.info("File too large (%s bytes), retrying with SD quality", file_size)
        _cleanup(path)

        if quality == "hd":
            await status_msg.edit_text("⏳ Video too large — retrying in lower quality...")
            path = await _download_video(url, "sd")
            if path is None:
                stats["errors"] += 1
                await status_msg.edit_text("❌ Couldn't download a smaller version of this video.")
                return
            file_size = path.stat().st_size

        if file_size > TELEGRAM_MAX_SIZE:
            _cleanup(path)
            stats["errors"] += 1
            await status_msg.edit_text(
                "❌ This video is too large for Telegram (>50 MB) even at lower quality."
            )
            return

    await status_msg.edit_text("⚙️ Processing...")

    try:
        with open(path, "rb") as video_file:
            await query.message.reply_video(
                video=video_file,
                supports_streaming=True,
                read_timeout=120,
                write_timeout=120,
            )
        stats["downloads"] += 1
        logger.info(
            "Sent video to user %s | total downloads: %d",
            update.effective_user.id,
            stats["downloads"],
        )
        await status_msg.delete()
    except Exception as exc:
        stats["errors"] += 1
        logger.error("Failed to send video: %s", exc)
        await status_msg.edit_text("❌ Failed to send the video. It might be too large or corrupted.")
    finally:
        _cleanup(path)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only stats (anyone can use for now)."""
    text = (
        f"📊 *Bot Stats*\n\n"
        f"Unique users: {len(stats['users'])}\n"
        f"Downloads: {stats['downloads']}\n"
        f"Errors: {stats['errors']}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# Health-check server (keeps Render web service alive)
# ---------------------------------------------------------------------------
class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass  # suppress noisy request logs


def _start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Health-check server running on port %s", port)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable is not set!")
        raise SystemExit(1)

    _start_health_server()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CallbackQueryHandler(quality_callback))
    # This catches ALL text messages (including first message with no /start)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
