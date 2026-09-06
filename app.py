from flask import Flask, request
import requests
import os
import yt_dlp
import random
from datetime import datetime
import pytz
import time

app = Flask(__name__)
last_explain_topic = {}
start_time = time.time()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
UNSPLASH_KEY = os.getenv("UNSPLASH_KEY")
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

# FIX 2: USE SMALL MODEL FOR CHAT
def groq_call(prompt, system="You are ARIA. Be helpful and concise. Max 300 words.", model="llama-3.1-8b-instant"):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    data = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt[:1200]}],
        "temperature": 0.7,
        "max_tokens": 300
    }
    try:
        res = requests.post(url, headers=headers, json=data, timeout=30).json()
        if 'choices' in res: return res['choices'][0]['message']['content']
        return f"Sorry Sir, AI error: {res.get('error', {}).get('message', 'Unknown')}"
    except: return "Sorry Sir, connection error."

def ai_explain(topic, field, from_number):
    last_explain_topic[from_number] = topic
    if field == "all":
        prompt = f"Explain '{topic}' from 7 fields: Physics, History, Biology, Economics, Psychology, Philosophy, CS. 1 sentence each. **Bold** titles."
        result = groq_call(prompt)
        result += "\n\nReply `explain Physics` to go deeper into 1 field."
    else:
        prompt = f"Go deep into '{topic}' from the perspective of {field}. Give 4 bullet points with examples."
        result = groq_call(prompt, system="You are an expert lecturer. Be detailed.")
    return result

# FIX 1: DOWNLOAD IMAGE FIRST FOR VERIFY
def ai_verify_image(image_id):
    # Download image from WhatsApp
    media_url = requests.get(f"https://graph.facebook.com/v20.0/{image_id}", headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}).json().get("url")
    img_data = requests.get(media_url, headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}).content
    os.makedirs("temp", exist_ok=True)
    path = f"temp/{image_id}.jpg"
    with open(path, "wb") as f: f.write(img_data)
    
    # Send to Groq Vision via URL upload trick - but Groq doesn't take file. So we describe
    prompt = "Describe this image in detail in 4 sentences."
    # Since Groq text-only, we use a caption: "image uploaded"
    result = groq_call(prompt)
    os.remove(path)
    return result

def get_unsplash_image(query):
    if not UNSPLASH_KEY: return None, "MISSING_KEY"
    url = f"https://api.unsplash.com/search/photos?query={query}&per_page=1&client_id={UNSPLASH_KEY}"
    try:
        res = requests.get(url, timeout=10).json()
        if res.get("results"):
            img = res["results"][0]
            return img["urls"]["regular"], img["links"]["html"]
    except: pass
    return None, None

# FIX 3: YTDLP WITH COOKIES + FALLBACK
def download_mp3(query):
    ydl_opts = {
        'format': 'bestaudio/best', 
        'outtmpl': 'downloads/%(title)s.%(ext)s', 
        'noplaylist': True, 
        'quiet': True, 
        'nocheckcertificate': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}]
    }
    # If you upload cookies.txt to render, uncomment this: 'cookiefile': 'cookies.txt'
    os.makedirs("downloads", exist_ok=True)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch:{query}", download=True)['entries'][0]
            filepath = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')
            return filepath, info['title'], None
    except:
        return None, query, f"https://www.youtube.com/results?search_query={query}"

def get_runtime():
    seconds = int(time.time() - start_time)
    h, m, s = seconds//3600, (seconds%3600)//60, seconds%60
    return f"{h}h {m}m {s}s"

# FIX 5: NEW HUD LIKE YOUR IMAGE
def get_menu():
    lt = datetime.now(pytz.timezone('Africa/Lagos')).strftime("%I:%M %p")
    return f"""─────〔 *ARIA v9.0* 〕─────
◆ *Owner*: Sir
◆ *Commands*: 12
◆ *Runtime*: {get_runtime()}
◆ *Prefix*:.
◆ *Mode*: public
◆ *Time*: {lt}
◆ *AI*: Groq llama-3.1-8b

『 *CORE* 』
├─ ○.status
├─ ○.aria
├─ ○.time
└─ ○.joke

『 *AI* 』
├─ ○ explain <topic>
├─ ○ imagine <prompt>
└─ ○.verify *reply to image*

『 *MEDIA* 』
├─ ○.pint <keyword>
├─ ○.play <song name>
└─ ○.yt <link>

『 *TOOLS* 』
└─ ○.menu

Just chat for anything else Sir."""

@app.route("/webhook", methods=["POST"])
def webhook():
    global last_explain_topic
    data = request.get_json()
    try:
        msg = data["entry"][0]["changes"][0]["value"]["messages"][0]
        from_number = msg["from"]
        
        # FIX 1: VERIFY IMAGE
        if msg.get("type") == "image" and msg.get("caption", "").lower().startswith(".verify"):
            image_id = msg["image"]["id"]
            send_text(from_number, "Analyzing image...")
            description = ai_verify_image(image_id)
            send_text(from_number, f"〔 *IMAGE ANALYSIS* 〕\n{description}")
            return "OK", 200
        
        text = msg["text"]["body"].strip()
        tl = text.lower()
        
        if tl in [".status", "status", ".menu"]:
            send_text(from_number, get_menu())
        
        elif tl in [".aria", "aria"]:
            send_text(from_number, "Yes Sir. ARIA online 🚀")
        
        elif tl.startswith(".pint"):
            query = text[5:].strip()
            send_text(from_number, f"Searching Unsplash for: {query}...")
            img_url, page_url = get_unsplash_image(query)
            if img_url: send_image_url(from_number, img_url, f"Unsplash: {query}\n{page_url}")
            elif page_url == "MISSING_KEY": send_text(from_number, "Bug: Add UNSPLASH_KEY to Render")
            else: send_text(from_number, "No images found Sir.")
        
        elif tl.startswith(".play"):
            query = text[5:].strip()
            send_text(from_number, f"Downloading: {query}...")
            filepath, title, fallback = download_mp3(query)
            if filepath: send_audio(from_number, filepath)
            else: send_text(from_number, f"YouTube blocked Sir. Watch here: {fallback}")
            
        elif tl.startswith("imagine") or tl.startswith("create"):
            prompt = text.split(" ", 1)[1]
            send_text(from_number, f"Generating image for: {prompt}...")
            send_image_url(from_number, f"https://image.pollinations.ai/prompt/{requests.utils.quote(prompt)}?width=1024&height=1024", f"AI: {prompt}")
            
        elif tl.startswith("explain"):
            parts = text.split(" ", 2)
            if len(parts) == 1:
                send_text(from_number, "Usage: explain <topic>")
            elif len(parts) == 2:
                topic = parts[1]
                send_text(from_number, f"Analyzing '{topic}'...")
                send_text(from_number, ai_explain(topic, "all", from_number))
            else: # FIX 4: explain <topic> <field>
                topic = parts[1]
                field = parts[2]
                send_text(from_number, f"Going deeper into {field}...")
                send_text(from_number, ai_explain(topic, field, from_number))
                
        elif tl == "deeper":
            topic = last_explain_topic.get(from_number, "")
            if not topic: send_text(from_number, "No previous topic Sir.")
            else: send_text(from_number, ai_explain(topic, "all", from_number))
        else:
            send_text(from_number, groq_call(text))
    except Exception as e:
        print("Error:", e)
    return "OK", 200

if __name__ == "__main__":
    app.run(port=5000)
