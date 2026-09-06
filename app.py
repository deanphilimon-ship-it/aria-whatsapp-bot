from flask import Flask, request
import requests
import os
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
CHAT_MODEL = "openai/gpt-oss-120b"
VISION_MODEL = "llama-3.2-11b-vision-preview"

def send_text(to, text):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    requests.post(url, headers=headers, json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text[:4096]}})

def send_image_url(to, image_url, caption=""):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    requests.post(url, headers=headers, json={"messaging_product": "whatsapp", "to": to, "type": "image", "image": {"link": image_url, "caption": caption}})

def send_audio_url(to, audio_url):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    requests.post(url, headers=headers, json={"messaging_product": "whatsapp", "to": to, "type": "audio", "audio": {"link": audio_url}})

def groq_call(prompt, system="You are ARIA. Be helpful and concise. Max 400 words.", model=CHAT_MODEL):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    data = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt[:1500]}], "temperature": 0.7, "max_tokens": 400}
    try:
        res = requests.post(url, headers=headers, json=data, timeout=30).json()
        if 'choices' in res: return res['choices'][0]['message']['content']
        return f"AI error"
    except: return "Connection error."

def groq_vision(image_url, prompt="Describe this image and verify any facts/text in it. Be concise."):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    data = {
        "model": VISION_MODEL,
        "messages": [{"role": "user","content": [{"type": "text", "text": prompt},{"type": "image_url", "image_url": {"url": image_url}}]}
        ],"max_tokens": 500}
    try:
        res = requests.post(url, headers=headers, json=data, timeout=40).json()
        if 'choices' in res: return res['choices'][0]['message']['content']
        return f"Vision error"
    except: return "Vision connection error."

def ai_explain(topic, field, from_number):
    last_explain_topic[from_number] = topic
    if field == "all":
        system = "You are a professor. Answer from knowledge only. 1 sentence per field. Max 7 sentences."
        prompt = f"Explain '{topic}' from 7 fields: Physics, History, Biology, Economics, Psychology, Philosophy, CS. **Bold** titles."
        result = groq_call(prompt, system=system)
        result += "\n\nReply `explain Physics` to go deeper into 1 field."
    else:
        system = "You are an expert lecturer. Answer from knowledge only. 4 bullet points max."
        prompt = f"Go deep into '{topic}' from the perspective of {field}. Give 4 bullet points with examples."
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

# FIX: NO YOUTUBE API KEY NEEDED. USE COBALT DIRECT
def download_mp3_cobalt(query):
    youtube_url = f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}"
    cobalt_url = "https://api.cobalt.tools/api/json"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    data = {"url": youtube_url, "isAudioOnly": True, "isMp3": True, "quality": "128"}
    try:
        res = requests.post(cobalt_url, headers=headers, json=data, timeout=20).json()
        if res.get("url"):
            return res["url"], query
    except: pass
    try:
        savetube = requests.post("https://api.savetube.me/v1/api/convert", json={"url": youtube_url, "format": "mp3"}, timeout=20).json()
        if savetube.get("data", {}).get("downloadUrl"):
            return savetube["data"]["downloadUrl"], query
    except: pass
    return None, f"YouTube blocked Sir. Watch here: {youtube_url}"

def get_runtime():
    seconds = int(time.time() - start_time)
    h, m, s = seconds//3600, (seconds%3600)//60, seconds%60
    return f"{h}h {m}m {s}s"

def get_menu():
    lt = datetime.now(pytz.timezone('Africa/Lagos')).strftime("%I:%M %p")
    return f"""─────〔 *ARIA v9.7* 〕─────
◆ *Owner*: Sir
◆ *Commands*: 13
◆ *Runtime*: {get_runtime()}
◆ *Prefix*:.
◆ *Mode*: public
◆ *Time*: {lt}
◆ *AI*: GPT-OSS-120B + Vision

『 *CORE* 』
├─ ○.status
├─ ○.aria
└─ ○.joke

『 *AI* 』
├─ ○ explain <topic>
├─ ○ explain <topic> <field>
├─ ○ imagine <prompt>
├─ ○.describe *reply to image*
└─ ○.verify *reply to image*

『 *MEDIA* 』
├─ ○.pint <keyword>
├─ ○.play <song name>
└─ ○.yt <link>

『 *TOOLS* 』
└─ ○.menu

Send image +.describe to test vision Sir."""

@app.route("/webhook", methods=["POST"])
def webhook():
    global last_explain_topic
    data = request.get_json()
    try:
        msg = data["entry"][0]["changes"][0]["value"]["messages"][0]
        from_number = msg["from"]
        
        # FIX: HANDLE IMAGE WITH CAPTION OR REPLY
        if msg.get("type") == "image":
            image_id = msg["image"]["id"]
            caption = msg.get("caption", "").lower()
            
            # Get image URL from WhatsApp
            media_info = requests.get(f"https://graph.facebook.com/v20.0/{image_id}", headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}).json()
            image_url = media_info.get("url")
            
            if "describe" in caption or "verify" in caption:
                send_text(from_number, "Analyzing image with AI vision...")
                prompt = "Describe this image in detail. If there is text, read it. If there are facts/claims, verify if they are true or false." if "verify" in caption else "Describe this image in 4 sentences. What logo is this?"
                result = groq_vision(image_url, prompt)
                send_text(from_number, f"〔 *IMAGE ANALYSIS* 〕\n{result}")
                return "OK", 200
        
        text = msg["text"]["body"].strip()
        tl = text.lower()
        
        if tl in [".status", "status", ".menu"]:
            send_text(from_number, get_menu())
        elif tl in [".aria", "aria"]:
            send_text(from_number, "Yes Sir. ARIA online with Vision 🚀")
        elif tl.startswith(".pint"):
            query = text[5:].strip()
            send_text(from_number, f"Searching Unsplash for: {query}...")
            img_url, page_url = get_unsplash_image(query)
            if img_url: send_image_url(from_number, img_url, f"Unsplash: {query}\n{page_url}")
            elif page_url == "MISSING_KEY": send_text(from_number, "Bug: Add UNSPLASH_KEY to Render")
            else: send_text(from_number, "No images found Sir.")
        elif tl.startswith(".play"):
            query = text[5:].strip()
            send_text(from_number, f"Fetching MP3 for: {query}...")
            audio_url, title = download_mp3_cobalt(query)
            if audio_url: 
                send_text(from_number, f"Found: *{title}*\nSending audio...")
                send_audio_url(from_number, audio_url)
            else: send_text(from_number, f"Failed Sir: {title}")
        elif tl.startswith("imagine") or tl.startswith("create"):
            prompt = text.split(" ", 1)[1]
            send_text(from_number, f"Generating image for: {prompt}...")
            send_image_url(from_number, f"https://image.pollinations.ai/prompt/{requests.utils.quote(prompt)}?width=1024&height=1024", f"AI: {prompt}")
        elif tl.startswith("explain"):
            parts = text.split(" ", 2)
            if len(parts) == 1: send_text(from_number, "Usage: explain <topic>")
            elif len(parts) == 2: send_text(from_number, ai_explain(parts[1], "all", from_number))
            else: send_text(from_number, ai_explain(parts[1], parts[2], from_number))
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
