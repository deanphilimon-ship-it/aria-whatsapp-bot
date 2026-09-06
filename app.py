from flask import Flask, request
import requests
import os
from datetime import datetime
import pytz
import time

app = Flask(__name__)
last_explain_topic = {}
user_waiting_image = {}
start_time = time.time()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
UNSPLASH_KEY = os.getenv("UNSPLASH_KEY")
GROQ_KEY = os.getenv("GROQ_KEY")
CHAT_MODEL = "openai/gpt-oss-120b"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

def send_text(to, text):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    # FORCE SPLIT: 3000 chars max to be safe
    chunks = [text[i:i+3000] for i in range(0, len(text), 3000)]
    for i, chunk in enumerate(chunks):
        if len(chunks) > 1: chunk = f"[{i+1}/{len(chunks)}]\n{chunk}"
        requests.post(url, headers=headers, json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": chunk}})

def groq_call(prompt, system="You are ARIA. Be extremely concise. Max 150 words. No tables. Use simple bullets. No markdown tables.", model=CHAT_MODEL):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    data = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt[:800]}], "temperature": 0.5, "max_tokens": 200} # CUT TOKENS
    try:
        res = requests.post(url, headers=headers, json=data, timeout=30).json()
        if 'choices' in res: return res['choices'][0]['message']['content']
        return f"AI error"
    except: return "Connection error."

def groq_vision(image_url, prompt):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    data = {"model": VISION_MODEL,"messages": [{"role": "user","content": [{"type": "text", "text": prompt},{"type": "image_url", "image_url": {"url": image_url}}]}
        ],"max_tokens": 250} # CUT TOKENS
    try:
        res = requests.post(url, headers=headers, json=data, timeout=40).json()
        if 'choices' in res: return res['choices'][0]['message']['content']
        return f"Vision error"
    except: return "Vision connection error."

def ai_explain(topic, field, from_number):
    last_explain_topic[from_number] = topic
    if field == "all":
        system = "You are a professor. MAX 5 BULLETS. 1 line each. NO TABLES. Be brief."
        prompt = f"Explain '{topic}' in 5 fields only: Biology, Chemistry, Pharmacology, Clinical, Exam tips. 1 short sentence each."
        result = groq_call(prompt, system=system)
        result += "\n\nReply `explain Pharmacology` for details."
    else:
        system = "You are an expert. 3 bullets max. 1 line each. No tables."
        prompt = f"Explain '{topic}' from {field}. 3 short bullet points."
        result = groq_call(prompt, system=system)
    return result

def download_mp3_final(query):
    youtube_url = f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}"
    try:
        search = requests.get(f"https://api.ssstik.io/yt/search?q={requests.utils.quote(query)}", timeout=10).json()
        video_url = search['data'][0]['url']
        title = search['data'][0]['title']
        convert = requests.post("https://api.ssstik.io/yt/convert", json={"url": video_url, "format": "mp3"}, timeout=20).json()
        if convert.get("data", {}).get("url"):
            return convert["data"]["url"], title
    except: pass
    return None, f"Blocked. Watch: {youtube_url}"

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
            
        if tl.startswith("explain"):
            parts = text.split(" ", 2)
            if len(parts) == 1: send_text(from_number, "Usage: explain <topic>")
            elif len(parts) == 2: send_text(from_number, ai_explain(parts[1], "all", from_number))
            else: send_text(from_number, ai_explain(parts[1], parts[2], from_number))
        elif tl.startswith(".play"):
            query = text[5:].strip()
            send_text(from_number, f"Fetching: {query}...")
            audio_url, title = download_mp3_final(query)
            if audio_url: 
                send_text(from_number, f"Found: *{title}*")
                requests.post(f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages", headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}, json={"messaging_product": "whatsapp", "to": from_number, "type": "audio", "audio": {"link": audio_url}})
            else: send_text(from_number, title)
        else:
            send_text(from_number, groq_call(text))
    except Exception as e:
        print("Error:", e)
    return "OK", 200

if __name__ == "__main__":
    app.run(port=5000)
