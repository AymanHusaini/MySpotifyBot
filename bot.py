import os
import csv
import io
import asyncio
import sqlite3
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
import yt_dlp

# --- CONFIGURATION ---
TELEGRAM_TOKEN = '8764605242:AAF-bkYG6vFKQnOt8LLwweeuYrhEZS7vqnM'

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- SQLITE DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect('playlists.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS custom_playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            playlist_name TEXT,
            song_title TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- YOUTUBE DOWNLOAD FUNCTION ---
def download_mp3_from_yt(search_query):
    ydl_opts = {
        'format': 'bestaudio/best',
        'default_search': 'ytsearch',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
        'no_warnings': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"{search_query} audio", download=True)
        if 'entries' in info and len(info['entries']) > 0:
            entry = info['entries'][0]
        else:
            entry = info
        filename = ydl.prepare_filename(entry)
        mp3_filename = os.path.splitext(filename)[0] + '.mp3'
        return mp3_filename

# --- COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Welcome! Your Music Downloader Bot is active.\n\n"
        "📜 **Commands & Usage:**\n"
        "• Upload a `.csv` file directly to save a playlist.\n"
        "• `/importtext <playlist_name>` + line break + paste song list.\n"
        "• `/playlists` - View saved playlists.\n"
        "• `/play <playlist_name>` - Auto-search YT & send MP3s.\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# 1. IMPORT VIA TEXT PASTE
async def import_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "Usage:\n"
            "`/importtext <playlist_name>` then paste song titles on new lines.\n\n"
            "Example:\n"
            "`/importtext rock`\n"
            "Judika - Jikalau Kau Cinta\n"
            "Sheila On 7 - Dan",
            parse_mode="Markdown"
        )
        return

    pl_name = context.args[0].lower()
    full_text = update.message.text.split("\n")
    songs = [line.strip() for line in full_text[1:] if line.strip()]

    if not songs:
        await update.message.reply_text("❌ No songs detected below the command!")
        return

    conn = sqlite3.connect('playlists.db')
    cursor = conn.cursor()
    count = 0
    for song in songs:
        cursor.execute('INSERT INTO custom_playlists (user_id, playlist_name, song_title) VALUES (?, ?, ?)',
                       (user_id, pl_name, song))
        count += 1
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ Saved {count} songs into `{pl_name}`!", parse_mode="Markdown")

# 2. IMPORT VIA CSV FILE UPLOAD
async def handle_csv_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    document = update.message.document

    if not document.file_name.endswith('.csv'):
        await update.message.reply_text("Please upload a valid `.csv` file!")
        return

    pl_name = os.path.splitext(document.file_name)[0].lower()
    await update.message.reply_text(f"⏳ Reading CSV file for playlist `{pl_name}`...")

    file = await context.bot.get_file(document.file_id)
    file_bytes = await file.download_as_bytearray()

    csv_data = io.StringIO(file_bytes.decode('utf-8'))
    reader = csv.reader(csv_data)
    
    # Skip header if present
    next(reader, None)

    conn = sqlite3.connect('playlists.db')
    cursor = conn.cursor()
    count = 0

    for row in reader:
        if row:
            # Join columns or take first non-empty text
            song_title = " - ".join([col.strip() for col in row if col.strip()])
            if song_title:
                cursor.execute('INSERT INTO custom_playlists (user_id, playlist_name, song_title) VALUES (?, ?, ?)',
                               (user_id, pl_name, song_title))
                count += 1

    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ Successfully imported {count} songs into playlist `{pl_name}`!", parse_mode="Markdown")

# 3. LIST PLAYLISTS
async def list_playlists(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect('playlists.db')
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT playlist_name FROM custom_playlists WHERE user_id = ?', (user_id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("No playlists saved yet.")
        return

    text = "🎵 **Your Saved Playlists:**\n"
    for r in rows:
        text += f"• `{r[0]}`\n"
    text += "\nType `/play <playlist_name>` to download and listen!"
    await update.message.reply_text(text, parse_mode="Markdown")

# 4. PLAY / DOWNLOAD PLAYLIST
async def play_playlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Please provide a playlist name! Example: `/play rock`")
        return

    pl_name = context.args[0].lower()
    conn = sqlite3.connect('playlists.db')
    cursor = conn.cursor()
    cursor.execute('SELECT song_title FROM custom_playlists WHERE user_id = ? AND playlist_name = ?', (user_id, pl_name))
    songs = cursor.fetchall()
    conn.close()

    if not songs:
        await update.message.reply_text(f"Playlist `{pl_name}` not found.", parse_mode="Markdown")
        return

    await update.message.reply_text(f"🚀 Starting download for {len(songs)} tracks from YouTube...")

    os.makedirs('downloads', exist_ok=True)
    for index, (song,) in enumerate(songs, 1):
        try:
            status_msg = await update.message.reply_text(f"🔎 [{index}/{len(songs)}] Searching YT & Downloading: `{song}`...", parse_mode="Markdown")
            
            loop = asyncio.get_event_loop()
            mp3_path = await loop.run_in_executor(None, download_mp3_from_yt, song)
            
            await update.message.reply_text(f"📤 Sending MP3: `{song}`...")
            with open(mp3_path, 'rb') as audio_file:
                await update.message.reply_audio(audio=audio_file, title=song)
                
            if os.path.exists(mp3_path):
                os.remove(mp3_path)
            await status_msg.delete()
        except Exception as e:
            await update.message.reply_text(f"❌ Error processing `{song}`: {e}", parse_mode="Markdown")

# --- MAIN RUNNER ---
if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("importtext", import_text))
    app.add_handler(CommandHandler("playlists", list_playlists))
    app.add_handler(CommandHandler("play", play_playlist))
    app.add_handler(MessageHandler(filters.Document.FileExtension("csv"), handle_csv_file))

    print("Bot is running...")
    app.run_polling()

