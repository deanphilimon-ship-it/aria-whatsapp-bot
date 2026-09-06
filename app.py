from flask import Flask, request
import requests
import os
import yt_dlp
import random
from datetime import datetime
import pytz

app = Flask(__name__)

# === MEMORY ===
last_explain_topic = {}

# === CONFIG ===
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
UNSPLASH_KEY = os.getenv("UNSPLASH_KEY")
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

# === AI FUNCTIONS - PATCHED FOR SIZE ERROR ===
def groq_call(prompt, system="You are ARIA. Be helpful and concise. Keep answers under 500 words."):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "groq/compound",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt[:2000]} # Truncate long prompts
        ],
        "temperature": 0.7,
        "max_tokens": 512 # PATCH: Lowered to prevent "Entity Too Large"
    }
    try:
        res = requests.post(url, headers=headers, json=data, timeout=30).json()
        if 'choices' in res and len(res['choices']) > 0:
            return res['choices'][0]['message']['content']
        else:
            return f"Sorry Sir, Groq error: {res.get('error', {}).get('message', 'Unknown')}"
    except Exception as e:
        return f"Sorry Sir, connection error. Try again."

def ai_chat(prompt):
    return groq_call(prompt)

def ai_explain(topic, from_number):
    global last_explain_topic
    last_explain_topic[from_number] = topic
    prompt = f"Explain '{topic}' briefly from: Physics, History, Biology, Economics, Psychology, Philosophy, Computer Science. 1-2 sentences each. Use **bold** titles."
    result = groq_call(prompt, system="You are an expert educator. Be concise.")
    result += "\n\nReply `deeper` or `explain Physics` for more detail."
    return result

def ai_image(prompt):
    safe_prompt = requests.utils.quote(prompt)
    return f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1024&height=1024&model=flux"

def ai_verify_image(image_url):
    prompt = f"Describe this image in detail in 4 sentences max: {image_url}"
    return groq_call(prompt, system="You are a vision assistant. Be descriptive but concise.")

# === MEDIA FUNCTIONS ===
def get_unsplash_image(query):
    url = f"https://api.unsplash.com/search/photos?query={query}&per_page=1&client_id={UNSPLASH_KEY}"
    try:
        res = requests.get(url, timeout=10).json()
        if res.get("results"):
            img = res["results"][0]
            return img["urls"]["regular"], img["links"]["html"]
    except Exception as e: print("Unsplash Error:", e)
    return None, None

def download_mp3(query):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'noplaylist': True,
        'quiet': True,
        'nocheckcertificate': True,
        'extractor_args': {'youtube': {'player_client': ['android']}},
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
    }
    os.makedirs("downloads", exist_ok=True)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch:{query}", download=True)['entries'][0]
            title = info['title']
            filepath = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')
            return filepath, title, None
    except Exception as e:
        return None, query, f"https://www.youtube.com/results?search_query={query}"

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
            send_text(from_number, "Analyzing image... 1 moment Sir")
            media_url = f"https://graph.facebook.com/v20.0/{image_id}"
            headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
            media_res = requests.get(media_url, headers=headers).json()
            image_url = media_res.get("url")
            description = ai_verify_image(image_url)
            send_text(from_number, f"*Image Analysis:*\n{description}")
            return "OK", 200
        
        text = msg["text"]["body"].strip()
        text_lower = text.lower()
        
        if text_lower in [".status", "status"]:
            lagos_time = datetime.now(pytz.timezone('Africa/Lagos')).strftime("%I:%M %p")
            send_text(from_number, f"""*ARIA SYSTEM STATUS v8.1*
Powered by: Groq groq/compound

.status - Show Commands
aria - Boot Jarvis
time - Lagos Time: {gmt_time}
joke - Tell joke
.pint <keyword> - Real Wallpaper
.play <song name> - Real MP3
.imagine <prompt> - AI Image
explain <topic> - 7 field explanation
.verify - Send image + this to describe it

Just chat with me for anything else Sir.""")
        
        elif text_lower in [".aria", "aria"]:
            send_text(from_number, "Yes Sir. How can I assist? 🚀")
        elif text_lower in ["tnx", "thanks"]:
            send_text(from_number, "Anytime Sir 🚀")
        elif text_lower == "joke":
            send_text(from_number, random.choice(["Why don't skeletons fight? No guts.", "What do you call fake pasta? An impasta."]))
        elif text_lower.startswith("time"):
            lagos_time = datetime.now(pytz.timezone('Africa/Lagos')).strftime("%I:%M %p")
            send_text(from_number, f"Lagos Time: {lagos_time}")
        elif text_lower.startswith(".pint"):
            query = text[5:].strip()
            send_text(from_number, f"Searching for: {query}...")
            img_url, page_url = get_unsplash_image(query)
            if img_url: send_image_url(from_number, img_url, f"Unsplash: {query}\n{page_url}")
            else: send_text(from_number, "No images found Sir.")
        elif text_lower.startswith(".play"):
            query = text[5:].strip()
            send_text(from_number, f"Downloading: {query}...")
            filepath, title, fallback = download_mp3(query)
            if filepath: send_audio(from_number, filepath)
            else: send_text(from_number, f"Download blocked. Here's the link: {fallback}")
        elif text_lower.startswith("imagine") or text_lower.startswith("create"):
            prompt = text.split(" ", 1)[1]
            send_text(from_number, f"Generating image for: {prompt}...")
            send_image_url(from_number, ai_image(prompt), f"AI Image: {prompt}")
        elif text_lower.startswith("explain") or text_lower == "deeper":
            parts = text.split(" ", 1)
            if len(parts) < 2 and text_lower!= "deeper":
                send_text(from_number, "Usage: explain <topic>")
            else:
                topic = parts[1] if len(parts) > 1 else last_explain_topic.get(from_number, "")
                if not topic: send_text(from_number, "No previous topic to go deeper on Sir.")
                else:
                    send_text(from_number, f"Analyzing '{topic}'... 1 moment Sir")
                    send_text(from_number, ai_explain(topic, from_number))
        else:
            send_text(from_number, ai_chat(text))
            
    except Exception as e:
        print("Webhook Error:", e)
    return "OK", 200

if __name__ == "__main__":
    app.run(port=5000)
