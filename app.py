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
    data = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}}
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

# === AI FUNCTIONS - GROQ gpt-oss-120b ===
def groq_call(prompt, system="You are ARIA, a helpful assistant. The user calls you Sir. Be helpful and direct."):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "gpt-oss-120b",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 800 # Reduced to avoid timeout
    }
    try:
        res = requests.post(url, headers=headers, json=data, timeout=25).json()
        return res['choices'][0]['message']['content']
    except Exception as e:
        return f"Groq Error: {e}"

def ai_chat(prompt):
    return groq_call(prompt)

def ai_explain(topic):
    # PATCH: Do 1 call that asks for all 7 fields at once. Faster
    send_text = "" # placeholder
    prompt = f"Explain '{topic}' in 2 sentences each from the perspective of: Physics, History, Biology, Economics, Psychology, Philosophy, Computer Science. Format with **Field**: explanation"
    result = groq_call(prompt, system="You are an expert educator. Be concise and clear.")
    result += "\n\nReply with `explain <field>` to go deeper into 1 field. Ex: `explain Physics`"
    return result

def ai_image(prompt):
    safe_prompt = requests.utils.quote(prompt)
    return f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1024&height=1024&model=flux"

# === MEDIA FUNCTIONS - PATCHED ===
def get_pinterest_image(query):
    # PATCH: Add aesthetic and try 3 results
    query = query + " aesthetic"
    url = f"https://api.pinterest.com/v5/search/pins?query={query}&limit=3"
    headers = {"Authorization": f"Bearer {PINTEREST_TOKEN}"}
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        if res.get("items"):
            pin = res["items"][0]
            return pin["media"]["images"]["736x"]["url"], pin["link"]
    except: pass
    return None, None

def download_mp3(query):
    # PATCH: Stronger anti-bot args
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

# === WEBHOOK ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    try:
        msg = data["entry"][0]["changes"][0]["value"]["messages"][0]
        from_number = msg["from"]
        text = msg["text"]["body"].strip()
        
        # 1. JARVIS COMMANDS
        if text.lower() in [".status", "status"]:
            lagos_time = datetime.now(pytz.timezone('Africa/Lagos')).strftime("%I:%M %p")
            send_text(from_number, f"""*ARIA SYSTEM STATUS v7.3*
Powered by: Groq gpt-oss-120b

aria - Boot Jarvis
status - Show Commands
time - Lagos Time: {lagos_time}
joke - Tell joke
.pint <keyword> - Real Pinterest
.play <song name> - Real MP3
.imagine <prompt> - AI Image
.create <prompt> - AI Image
explain <topic> - 7 field explanation""")
        
        elif text.lower() in [".aria", "aria"]:
            send_text(from_number, "Yes Sir. How can I assist? 🚀")
        
        elif text.lower() in ["tnx", "thanks"]:
            send_text(from_number, "Anytime Sir 🚀")
        
        elif text.lower() == "joke":
            jokes = ["Why don't skeletons fight? No guts.", "What do you call fake pasta? An impasta."]
            send_text(from_number, random.choice(jokes))
        
        elif text.lower().startswith("time"):
            lagos_time = datetime.now(pytz.timezone('Africa/Lagos')).strftime("%I:%M %p")
            send_text(from_number, f"Lagos Time: {lagos_time}")

        # 2. MEDIA COMMANDS
        elif text.lower().startswith(".pint"):
            query = text[5:].strip()
            send_text(from_number, f"Searching Pinterest for: {query}...")
            img_url, pin_url = get_pinterest_image(query)
            if img_url: send_image_url(from_number, img_url, f"Pinterest: {query}\n{pin_url}")
            else: send_text(from_number, "No pins found. Try: batman art, goth aesthetic, dark wallpaper Sir.")
        
        elif text.lower().startswith(".play"):
            query = text[5:].strip()
            send_text(from_number, f"Downloading: {query}... This takes 20-30s Sir")
            try:
                filepath, title = download_mp3(query)
                send_audio(from_number, filepath)
            except Exception as e:
                send_text(from_number, f"Download failed: {str(e)[:200]}")

        # 3. AI IMAGE COMMANDS
        elif text.lower().startswith("imagine") or text.lower().startswith("create"):
            prompt = text.split(" ", 1)[1]
            send_text(from_number, f"Generating image for: {prompt}...")
            img_url = ai_image(prompt)
            send_image_url(from_number, img_url, f"AI Image: {prompt}")
        
        # 4. AI EXPLAIN COMMAND - PATCHED
        elif text.lower().startswith("explain"):
            parts = text.split(" ", 1)
            if len(parts) < 2:
                send_text(from_number, "Usage: explain <topic>\nI will explain from 7 fields of study.")
            else:
                topic = parts[1]
                send_text(from_number, f"Analyzing '{topic}' from 7 fields... 1 moment Sir")
                explanation = ai_explain(topic) # Now 1 API call instead of 7
                send_text(from_number, explanation)

        # 5. DEFAULT AI CHAT - WORKS WITHOUT COMMAND
        else:
            reply = ai_chat(text)
            send_text(from_number, reply)
            
    except Exception as e:
        print("Webhook Error:", e)
    return "OK", 200

if __name__ == "__main__":
    app.run(port=5000)
