from flask import Flask, request
import requests
import os
import yt_dlp
import random
from datetime import datetime
import pytz

app = Flask(__name__)

# === CONFIG ===
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
PINTEREST_TOKEN = os.getenv("PINTEREST_TOKEN")
GROQ_KEY = os.getenv("GROQ_KEY")

# === SEND FUNCTIONS ===
def send_text(to, text):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text[:4096]}}
    requests.post(url, headers=headers, json=data)

def send_image_url(to, image_url, caption=""):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": to, "type": "image", "image": {"link": image_url, "caption": caption}}
    requests.post(url, headers=headers, json=data)

def send_audio(to, audio_path):
    upload_url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    files = {'file': open(audio_path, 'rb'), 'type': 'audio/mpeg'}
    res = requests.post(upload_url, headers=headers, files=files).json()
    media_id = res.get("id")
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": to, "type": "audio", "audio": {"id": media_id}}
    requests.post(url, headers=headers, json=data)
    os.remove(audio_path)

# === AI FUNCTIONS - GROQ groq/compound ===
def groq_call(prompt, system="You are ARIA, a helpful assistant. The user calls you Sir. Be helpful, friendly, and direct."):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "groq/compound", # CHANGED TO WORKING MODEL
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.8,
        "max_tokens": 1024
    }
    try:
        res = requests.post(url, headers=headers, json=data, timeout=30).json()
        if 'choices' in res and len(res['choices']) > 0:
            return res['choices'][0]['message']['content']
        else:
            print("Groq Full Response:", res)
            return f"Sorry Sir, Groq didn't respond. Error: {res.get('error', {}).get('message', 'Unknown')}"
    except Exception as e:
        print("Groq Exception:", e)
        return f"Sorry Sir, I'm having trouble connecting to Groq right now. Try again."

def ai_chat(prompt):
    return groq_call(prompt)

def ai_explain(topic):
    prompt = f"Explain '{topic}' in 2 sentences each from the perspective of: Physics, History, Biology, Economics, Psychology, Philosophy, Computer Science. Use **bold** for each field title."
    result = groq_call(prompt, system="You are an expert educator. Be concise, clear, and use markdown.")
    result += "\n\nReply with `explain <field>` to go deeper into 1 field. Ex: `explain Physics`"
    return result

def ai_image(prompt):
    safe_prompt = requests.utils.quote(prompt)
    return f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1024&height=1024&model=flux"

# === MEDIA FUNCTIONS ===
def get_pinterest_image(query):
    query = query + " aesthetic"
    url = f"https://api.pinterest.com/v5/search/pins?query={query}&limit=3"
    headers = {"Authorization": f"Bearer {PINTEREST_TOKEN}"}
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        if res.get("items"):
            pin = res["items"][0]
            return pin["media"]["images"]["736x"]["url"], pin["link"]
    except Exception as e: print("Pinterest Error:", e)
    return None, None

def download_mp3(query):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'noplaylist': True,
        'quiet': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
    }
    os.makedirs("downloads", exist_ok=True)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch:{query}", download=True)['entries'][0]
        title = info['title']
        filepath = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')
        return filepath, title

# === WEBHOOK - CHAT IS DEFAULT ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    try:
        msg = data["entry"][0]["changes"][0]["value"]["messages"][0]
        from_number = msg["from"]
        text = msg["text"]["body"].strip()
        text_lower = text.lower()
        
        # 1. COMMANDS
        if text_lower in [".status", "status"]:
            lagos_time = datetime.now(pytz.timezone('Africa/Lagos')).strftime("%I:%M %p")
            send_text(from_number, f"""*ARIA SYSTEM STATUS v7.5*
Powered by: Groq groq/compound

aria - Boot Jarvis
status - Show Commands
time - Lagos Time: {lagos_time}
joke - Tell joke
.pint <keyword> - Real Pinterest
.play <song name> - Real MP3
.imagine <prompt> - AI Image
.create <prompt> - AI Image
explain <topic> - 7 field explanation

Just chat with me for anything else Sir.""")
        
        elif text_lower in [".aria", "aria"]:
            send_text(from_number, "Yes Sir. How can I assist? 🚀")
        
        elif text_lower in ["tnx", "thanks"]:
            send_text(from_number, "Anytime Sir 🚀")
        
        elif text_lower == "joke":
            jokes = ["Why don't skeletons fight? No guts.", "What do you call fake pasta? An impasta."]
            send_text(from_number, random.choice(jokes))
        
        elif text_lower.startswith("time"):
            lagos_time = datetime.now(pytz.timezone('Africa/Lagos')).strftime("%I:%M %p")
            send_text(from_number, f"Lagos Time: {lagos_time}")

        elif text_lower.startswith(".pint"):
            query = text[5:].strip()
            send_text(from_number, f"Searching Pinterest for: {query}...")
            img_url, pin_url = get_pinterest_image(query)
            if img_url: send_image_url(from_number, img_url, f"Pinterest: {query}\n{pin_url}")
            else: send_text(from_number, "No pins found. Try: batman art, goth aesthetic, dark wallpaper Sir.")
        
        elif text_lower.startswith(".play"):
            query = text[5:].strip()
            send_text(from_number, f"Downloading: {query}... This takes 20-30s Sir")
            try:
                filepath, title = download_mp3(query)
                send_audio(from_number, filepath)
            except Exception as e:
                send_text(from_number, f"Download failed: {str(e)[:200]}")

        elif text_lower.startswith("imagine") or text_lower.startswith("create"):
            prompt = text.split(" ", 1)[1]
            send_text(from_number, f"Generating image for: {prompt}...")
            img_url = ai_image(prompt)
            send_image_url(from_number, img_url, f"AI Image: {prompt}")
        
        elif text_lower.startswith("explain"):
            parts = text.split(" ", 1)
            if len(parts) < 2:
                send_text(from_number, "Usage: explain <topic>\nI will explain from 7 fields of study.")
            else:
                topic = parts[1]
                send_text(from_number, f"Analyzing '{topic}' from 7 fields... 1 moment Sir")
                explanation = ai_explain(topic)
                send_text(from_number, explanation)

        # 2. DEFAULT: NORMAL CHATBOT
        else:
            reply = ai_chat(text)
            send_text(from_number, reply)
            
    except Exception as e:
        print("Webhook Error:", e)
        send_text(from_number, "Sorry Sir, something went wrong. Please try again.")
    return "OK", 200

if __name__ == "__main__":
    app.run(port=5000)
