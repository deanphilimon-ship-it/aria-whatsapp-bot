from flask import Flask, request
import requests
import os
import yt_dlp
import random
from datetime import datetime
import pytz

app = Flask(__name__)
last_explain_topic = {}

# === CONFIG ===
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
UNSPLASH_KEY = os.getenv("UNSPLASH_KEY") # YOU MUST ADD THIS TO RENDER
GROQ_KEY = os.getenv("GROQ_KEY")

def send_text(to, text):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    requests.post(url, headers=headers, json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text[:4096]}})

def send_image_url(to, image_url, caption=""):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    requests.post(url, headers=headers, json={"messaging_product": "whatsapp", "to": to, "type": "image", "image": {"link": image_url, "caption": caption}})

def send_audio(to, audio_path):
    upload_url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    res = requests.post(upload_url, headers=headers, files={'file': open(audio_path, 'rb'), 'type': 'audio/mpeg'}).json()
    media_id = res.get("id")
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    requests.post(url, headers=headers, json={"messaging_product": "whatsapp", "to": to, "type": "audio", "audio": {"id": media_id}})
    os.remove(audio_path)

# === AI - FIXED FOR "ENTITY TOO LARGE" ===
def groq_call(prompt, system="You are ARIA. Be helpful and concise. Max 400 words."):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "groq/compound",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt[:1500]}],
        "temperature": 0.7,
        "max_tokens": 400 # FURTHER REDUCED
    }
    try:
        res = requests.post(url, headers=headers, json=data, timeout=30).json()
        if 'choices' in res: return res['choices'][0]['message']['content']
        return f"Sorry Sir, Groq error: {res.get('error', {}).get('message', 'Unknown')}"
    except: return "Sorry Sir, connection error."

def ai_explain(topic, from_number):
    last_explain_topic[from_number] = topic
    prompt = f"Explain '{topic}' from 7 fields: Physics, History, Biology, Economics, Psychology, Philosophy, CS. 1 sentence each. **Bold** titles."
    result = groq_call(prompt)
    return result + "\n\nReply `deeper` or `explain Physics` for more."

def ai_verify_image(image_url):
    return groq_call(f"Describe this image in 4 sentences max: {image_url}")

# === MEDIA - PINTEREST REMOVED, UNSPLASH ONLY ===
def get_unsplash_image(query):
    if not UNSPLASH_KEY: return None, None
    url = f"https://api.unsplash.com/search/photos?query={query}&per_page=1&client_id={UNSPLASH_KEY}"
    try:
        res = requests.get(url, timeout=10).json()
        if res.get("results"):
            img = res["results"][0]
            return img["urls"]["regular"], img["links"]["html"]
    except: pass
    return None, None

def download_mp3(query):
    ydl_opts = {'format': 'bestaudio/best', 'outtmpl': 'downloads/%(title)s.%(ext)s', 'noplaylist': True, 'quiet': True, 'nocheckcertificate': True, 'extractor_args': {'youtube': {'player_client': ['android']}}, 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}]}
    os.makedirs("downloads", exist_ok=True)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch:{query}", download=True)['entries'][0]
            filepath = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')
            return filepath, None
    except:
        return None, f"https://www.youtube.com/results?search_query={query}"

# === WEBHOOK ===
@app.route("/webhook", methods=["POST"])
def webhook():
    global last_explain_topic
    data = request.get_json()
    try:
        msg = data["entry"][0]["changes"][0]["value"]["messages"][0]
        from_number = msg["from"]
        
        if msg.get("type") == "image" and msg.get("caption", "").lower().startswith(".verify"):
            image_id = msg["image"]["id"]
            send_text(from_number, "Analyzing image...")
            media_url = requests.get(f"https://graph.facebook.com/v20.0/{image_id}", headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}).json().get("url")
            send_text(from_number, f"*Image Analysis:*\n{ai_verify_image(media_url)}")
            return "OK", 200
        
        text = msg["text"]["body"].strip()
        tl = text.lower()
        
        if tl in [".status", "status"]:
            lt = datetime.now(pytz.timezone('Africa/Lagos')).strftime("%I:%M %p")
            send_text(from_number, f"""*ARIA SYSTEM STATUS v8.2*
Powered by: Groq groq/compound

.status - Show Commands
.pint <keyword> - Unsplash Wallpaper <-- CHANGED FROM PINTEREST
.play <song name> - Real MP3
.imagine <prompt> - AI Image
explain <topic> - 7 field explanation
.verify - Send image + this to describe it

Just chat with me for anything else Sir.""")
        
        elif tl.startswith(".pint"): # PINTEREST CODE DELETED
            query = text[5:].strip()
            send_text(from_number, f"Searching Unsplash for: {query}...") # CHANGED TEXT
            img_url, page_url = get_unsplash_image(query)
            if img_url: send_image_url(from_number, img_url, f"Unsplash: {query}\n{page_url}")
            else: send_text(from_number, "No images found Sir. Add UNSPLASH_KEY to Render.")
        
        elif tl.startswith(".play"):
            query = text[5:].strip()
            send_text(from_number, f"Downloading: {query}...")
            filepath, fallback = download_mp3(query)
            if filepath: send_audio(from_number, filepath)
            else: send_text(from_number, f"Blocked. Link: {fallback}")
        elif tl.startswith("imagine") or tl.startswith("create"):
            prompt = text.split(" ", 1)[1]
            send_text(from_number, f"Generating image for: {prompt}...")
            send_image_url(from_number, f"https://image.pollinations.ai/prompt/{requests.utils.quote(prompt)}?width=1024&height=1024", f"AI: {prompt}")
        elif tl.startswith("explain") or tl == "deeper":
            topic = text.split(" ", 1)[1] if " " in text else last_explain_topic.get(from_number, "")
            if not topic: send_text(from_number, "Usage: explain <topic>")
            else: send_text(from_number, ai_explain(topic, from_number))
        else:
            send_text(from_number, groq_call(text))
    except: pass
    return "OK", 200

if __name__ == "__main__":
    app.run(port=5000)
