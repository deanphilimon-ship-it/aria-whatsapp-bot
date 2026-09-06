from flask import Flask, request
import requests
import os
import random
from datetime import datetime
import pytz
import time
from io import BytesIO

app = Flask(__name__)
last_explain_topic = {}
user_waiting_image = {}
start_time = time.time()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
UNSPLASH_KEY = os.getenv("UNSPLASH_KEY")
GROQ_KEY = os.getenv("GROQ_KEY")
CHAT_MODEL = "openai/gpt-oss-120b"
VISION_MODEL = "llama-3.2-11b-vision-preview"

def send_text(to, text):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)] # Auto split
    for chunk in chunks:
        requests.post(url, headers=headers, json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": chunk}})

def send_image_url(to, image_url, caption=""):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    requests.post(url, headers=headers, json={"messaging_product": "whatsapp", "to": to, "type": "image", "image": {"link": image_url, "caption": caption}})

def send_audio_url(to, audio_url):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    requests.post(url, headers=headers, json={"messaging_product": "whatsapp", "to": to, "type": "audio", "audio": {"link": audio_url}})

def groq_call(prompt, system="You are ARIA. Be helpful, concise, max 200 words. No tables. Use bullets and line breaks only.", model=CHAT_MODEL):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    data = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt[:1000]}], "temperature": 0.7, "max_tokens": 250}
    try:
        res = requests.post(url, headers=headers, json=data, timeout=30).json()
        if 'choices' in res: return res['choices'][0]['message']['content']
        return f"AI error"
    except: return "Connection error."

def groq_vision(image_url, prompt):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    data = {"model": VISION_MODEL,"messages": [{"role": "user","content": [{"type": "text", "text": prompt},{"type": "image_url", "image_url": {"url": image_url}}]}
        ],"max_tokens": 400}
    try:
        res = requests.post(url, headers=headers, json=data, timeout=40).json()
        if 'choices' in res: return res['choices'][0]['message']['content']
        return f"Vision error: {res}"
    except: return "Vision connection error."

def ai_explain(topic, field, from_number):
    last_explain_topic[from_number] = topic
    if field == "all":
        system = "You are a professor. Short. Max 7 bullets. No tables. No markdown tables."
        prompt = f"Explain '{topic}' in 7 fields: Physics, History, Biology, Economics, Psychology, Philosophy, CS. 1 line per field."
        result = groq_call(prompt, system=system)
        result += "\n\nReply `explain Physics` to go deeper."
    else:
        system = "You are an expert lecturer. 4 bullets max. No tables."
        prompt = f"Go deep into '{topic}' from {field}. 4 bullet points with examples."
        result = groq_call(prompt, system=system)
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

# FIX: USE 'COBALT' WITH PROXY + FALLBACK TO 'SSSYOUTUBE'
def download_mp3_final(query):
    youtube_url = f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}"
    # Try ssyoutube api - no key needed
    try:
        search = requests.get(f"https://api.ssstik.io/yt/search?q={requests.utils.quote(query)}", timeout=10).json()
        video_url = search['data'][0]['url']
        title = search['data'][0]['title']
        
        convert = requests.post("https://api.ssstik.io/yt/convert", json={"url": video_url, "format": "mp3"}, timeout=20).json()
        if convert.get("data", {}).get("url"):
            return convert["data"]["url"], title
    except: pass
    return None, f"All downloaders blocked. Watch: {youtube_url}"

def get_runtime():
    seconds = int(time.time() - start_time)
    h, m, s = seconds//3600, (seconds%3600)//60, seconds%60
    return f"{h}h {m}m {s}s"

def get_menu():
    lt = datetime.now(pytz.timezone('Africa/Lagos')).strftime("%I:%M %p")
    return f"""─────〔 *ARIA v9.9* 〕─────
◆ *Owner*: Sir
◆ *Runtime*: {get_runtime()}
◆ *Prefix*:.
◆ *Time*: {lt}

『 *AI* 』
├─ ○ explain <topic>
├─ ○.describe *send image*
└─ ○.verify *send image*

『 *MEDIA* 』
├─ ○.pint <keyword>
└─ ○.play <song name>

Send image then.describe Sir"""

@app.route("/webhook", methods=["POST"])
def webhook():
    global last_explain_topic, user_waiting_image
    data = request.get_json()
    try:
        msg = data["entry"][0]["changes"][0]["value"]["messages"][0]
        from_number = msg["from"]
        
        # FIX: HANDLE REPLY TO IMAGE
        if msg.get("type") == "image":
            image_id = msg["image"]["id"]
            caption = msg.get("caption", "").lower()
            media_info = requests.get(f"https://graph.facebook.com/v20.0/{image_id}", headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}).json()
            image_url = media_info.get("url")
            user_waiting_image[from_number] = {"url": image_url}
            
            if "describe" in caption or "verify" in caption:
                prompt = "Describe this image in detail and verify any text/facts." if "verify" in caption else "Describe this image. What logo is this? 4 sentences max."
                result = groq_vision(image_url, prompt)
                send_text(from_number, f"〔 *IMAGE ANALYSIS* 〕\n{result}")
            else:
                send_text(from_number, "Image saved. Now send `.describe` or `.verify`")
            return "OK", 200
        
        text = msg["text"]["body"].strip()
        tl = text.lower()
        
        # FIX: If user sends.describe after image
        if tl in [".describe", ".verify"] and user_waiting_image.get(from_number):
            img_data = user_waiting_image.pop(from_number)
            send_text(from_number, "Analyzing image...")
            prompt = "Describe this image in detail and verify any text/facts." if tl == ".verify" else "Describe this image. What logo is this? 4 sentences max."
            result = groq_vision(img_data["url"], prompt)
            send_text(from_number, f"〔 *IMAGE ANALYSIS* 〕\n{result}")
            return "OK", 200
            
        if tl in [".status", ".menu"]:
            send_text(from_number, get_menu())
        elif tl.startswith(".pint"):
            query = text[5:].strip()
            send_text(from_number, f"Searching Unsplash for: {query}...")
            img_url, page_url = get_unsplash_image(query)
            if img_url: send_image_url(from_number, img_url, f"Unsplash: {query}")
            else: send_text(from_number, "No images found Sir.")
        elif tl.startswith(".play"):
            query = text[5:].strip()
            send_text(from_number, f"Fetching MP3 for: {query}...")
            audio_url, title = download_mp3_final(query)
            if audio_url: 
                send_text(from_number, f"Found: *{title}*")
                send_audio_url(from_number, audio_url)
            else: send_text(from_number, f"Failed Sir: {title}")
        elif tl.startswith("explain"):
            parts = text.split(" ", 2)
            if len(parts) == 1: send_text(from_number, "Usage: explain <topic>")
            elif len(parts) == 2: send_text(from_number, ai_explain(parts[1], "all", from_number))
            else: send_text(from_number, ai_explain(parts[1], parts[2], from_number))
        else:
            send_text(from_number, groq_call(text))
    except Exception as e:
        print("Error:", e)
    return "OK", 200

if __name__ == "__main__":
    app.run(port=5000)
