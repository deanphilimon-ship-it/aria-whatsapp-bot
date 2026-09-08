from flask import Flask, request
import requests
import os
from datetime import datetime
import pytz
import time

app = Flask(__name__)
VERSION = "v10.4 RAPIDAPI" # DEBUG VERSION
last_explain_topic = {}
user_waiting_image = {}
start_time = time.time()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
UNSPLASH_KEY = os.getenv("UNSPLASH_KEY")
GROQ_KEY = os.getenv("GROQ_KEY")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
CHAT_MODEL = "openai/gpt-oss-120b"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

def send_text(to, text):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    # FORCE SPLIT TO AVOID WHATSAPP CUTOFF
    chunks = [text[i:i+1500] for i in range(0, len(text), 1500)] 
    for i, chunk in enumerate(chunks):
        if len(chunks) > 1: chunk = f"[{i+1}/{len(chunks)}]\n{chunk}"
        requests.post(url, headers=headers, json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": chunk}})

def send_image_url(to, image_url, caption=""):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    requests.post(url, headers=headers, json={"messaging_product": "whatsapp", "to": to, "type": "image", "image": {"link": image_url, "caption": caption}})

def send_audio_url(to, audio_url):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    requests.post(url, headers=headers, json={"messaging_product": "whatsapp", "to": to, "type": "audio", "audio": {"link": audio_url}})

def groq_call(prompt, system="You are ARIA. Be extremely concise. Max 120 words. No tables.", model=CHAT_MODEL):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    data = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt[:600]}], "temperature": 0.5, "max_tokens": 120} # REDUCED TOKENS
    try:
        res = requests.post(url, headers=headers, json=data, timeout=30).json()
        if 'choices' in res: return res['choices'][0]['message']['content']
        return f"AI error"
    except: return "Connection error."

def groq_vision(image_url, prompt):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    data = {"model": VISION_MODEL,"messages": [{"role": "user","content": [{"type": "text", "text": prompt},{"type": "image_url", "image_url": {"url": image_url}}]}
        ],"max_tokens": 150}
    try:
        res = requests.post(url, headers=headers, json=data, timeout=40).json()
        if 'choices' in res: return res['choices'][0]['message']['content']
        return f"Vision error"
    except: return "Vision connection error."

def ai_explain(topic, field, from_number):
    last_explain_topic[from_number] = topic
    if field == "all":
        system = "You are a professor. MAX 4 WEEKS. 2 BULLETS PER WEEK. NO TABLES. BE BRIEF." # ULTRA SHORT
        prompt = f"Make a study plan for '{topic}'. 4 weeks only. 2 bullets each."
        result = groq_call(prompt, system=system)
        result += "\n\nReply `explain Pharmacology` for details on 1 topic."
    else:
        system = "You are an expert. 3 bullets max. 1 line each."
        prompt = f"Explain '{topic}' from {field}. 3 short bullet points."
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

# WORKING RAPIDAPI - youtube-mp3
def download_mp3_rapid(query):
    if not RAPIDAPI_KEY:
        return None, "Bug: Add RAPIDAPI_KEY to Render"
    
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "youtube-mp3.p.rapidapi.com" # WORKING HOST
    }
    youtube_url = f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}"
    try:
        # This API does search + download in 1 call using query as id
        dl_url = "https://youtube-mp3.p.rapidapi.com/dl/"
        dl_res = requests.get(dl_url, headers=headers, params={"id": query}, timeout=20).json()
        
        if dl_res.get("status") == "ok" and dl_res.get("link"):
            return dl_res["link"], dl_res["title"]
        else:
            return None, f"No results. Watch: {youtube_url}"
            
    except Exception as e:
        print(e)
        return None, f"RapidAPI Error. Watch: {youtube_url}"

def get_runtime():
    seconds = int(time.time() - start_time)
    h, m, s = seconds//3600, (seconds%3600)//60, seconds%60
    return f"{h}h {m}m {s}s"

def get_menu():
    lt = datetime.now(pytz.timezone('Africa/Lagos')).strftime("%I:%M %p")
    return f"""─────〔 *ARIA {VERSION}* 〕─────
◆ *Owner*: Sir
◆ *Runtime*: {get_runtime()}
◆ *YT Mode*: youtube-mp3 API
◆ *Vision*: Llama 4 Scout
◆ *Time*: {lt}

『 *AI* 』
├─ ○ explain <topic>
├─ ○.describe *send image*
└─ ○.verify *send image*

『 *MEDIA* 』
├─ ○.pint <keyword>
└─ ○.play <song name>"""

@app.route("/webhook", methods=["POST"])
def webhook():
    global last_explain_topic, user_waiting_image
    data = request.get_json()
    try:
        msg = data["entry"][0]["changes"][0]["value"]["messages"][0]
        from_number = msg["from"]
        
        if msg.get("type") == "image":
            image_id = msg["image"]["id"]
            caption = msg.get("caption", "").lower()
            media_info = requests.get(f"https://graph.facebook.com/v20.0/{image_id}", headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}).json()
            image_url = media_info.get("url")
            user_waiting_image[from_number] = {"url": image_url}
            
            if "describe" in caption or "verify" in caption:
                send_text(from_number, "Analyzing image...")
                prompt = "Describe image and verify facts. Max 4 sentences." if "verify" in caption else "Describe this image. What is it? Max 3 sentences."
                result = groq_vision(image_url, prompt)
                send_text(from_number, f"〔 *IMAGE ANALYSIS* 〕\n{result}")
            else:
                send_text(from_number, "Image saved. Send `.describe`")
            return "OK", 200
        
        text = msg["text"]["body"].strip()
        tl = text.lower()
        
        if tl in [".describe", ".verify"]:
            if user_waiting_image.get(from_number):
                img_data = user_waiting_image.pop(from_number)
                send_text(from_number, "Analyzing image...")
                prompt = "Describe image and verify facts. Max 4 sentences." if tl == ".verify" else "Describe this image. What logo is this? Max 3 sentences."
                result = groq_vision(img_data["url"], prompt)
                send_text(from_number, f"〔 *IMAGE ANALYSIS* 〕\n{result}")
            else:
                send_text(from_number, "Send image first Sir")
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
            audio_url, title = download_mp3_rapid(query)
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
        else:
            send_text(from_number, groq_call(text))
    except Exception as e:
        print("Error:", e)
    return "OK", 200

@app.route("/")
def home():
    return f"ARIA {VERSION} Running"

if __name__ == "__main__":
    app.run(port=5000)
