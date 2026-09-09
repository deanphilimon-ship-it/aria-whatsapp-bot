from flask import Flask, request
import requests
import os
from datetime import datetime
import pytz
import time

app = Flask(__name__)
VERSION = "v11.1 PRESENTABLE"
last_explain_topic = {}
last_explain_fields = {}
user_waiting_image = {}
start_time = time.time()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
UNSPLASH_KEY = os.getenv("UNSPLASH_KEY")
GROQ_KEY = os.getenv("GROQ_KEY")
CHAT_MODEL = "openai/gpt-oss-120b"

def send_text(to, text):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    # SPLIT AT 700 CHARS - SAFER + ADD HEADER
    chunks = [text[i:i+700] for i in range(0, len(text), 700)] 
    for i, chunk in enumerate(chunks):
        if len(chunks) > 1: 
            chunk = f"─────〔 *ARIA {VERSION}* 〕─────\n📄 *Part {i+1}/{len(chunks)}*\n\n{chunk}"
        else:
            chunk = f"─────〔 *ARIA {VERSION}* 〕─────\n\n{chunk}"
        requests.post(url, headers=headers, json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": chunk}})
        time.sleep(1.5) # 1.5s delay stops cutoff

def send_image_url(to, image_url, caption=""):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    requests.post(url, headers=headers, json={"messaging_product": "whatsapp", "to": to, "type": "image", "image": {"link": image_url, "caption": caption}})

def groq_call(prompt, system="You are ARIA. Advanced Responsive Intelligent Assistant. Reply like a helpful friend. Use bold labels, emojis, clear sections. Be complete but concise. Max 350 words. Use bullet points.", model=CHAT_MODEL):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    data = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt[:1500]}], "temperature": 0.4, "max_tokens": 550}
    try:
        res = requests.post(url, headers=headers, json=data, timeout=30).json()
        if 'choices' in res: return res['choices'][0]['message']['content']
        return f"⚠️ *AI Error:* {res}"
    except: return "⚠️ *Connection error Sir*"

def groq_vision(image_url, prompt, retry=0):
    # POLLINATIONS ANONYMOUS VISION WITH RETRY + SHORT
    short_prompt = f"{prompt}. Be concise. Use bullet points. Max 150 words."
    full_query = f"{short_prompt}. Image URL: {image_url}"
    url = f"https://text.pollinations.ai/{requests.utils.quote(full_query)}"
    try:
        res = requests.get(url, timeout=60).text
        if "rate limited" in res.lower() and retry < 1:
            time.sleep(3) 
            return groq_vision(image_url, prompt, retry+1)
        if "error" in res.lower():
            return "⚠️ *Vision service busy.* Try again in 30s Sir"
        return res
    except Exception as e: 
        return f"⚠️ *Vision error:* {e}"

def ai_explain(topic, field_num, from_number):
    fields = ["Biology", "Chemistry", "Pharmacology", "Clinical", "Pathophysiology", "Exam Tips"]
    
    if field_num == "all":
        last_explain_topic[from_number] = topic
        last_explain_fields[from_number] = fields
        result = f"📚 *{topic.title()} - 6 Fields*\n\n"
        for i, f in enumerate(fields, 1):
            result += f"{i}. *{f}*\n"
        result += f"\n💡 Reply: `explain {topic} 3` for Pharmacology"
        return result
    else:
        try: idx = int(field_num) - 1
        except: return "⚠️ Usage: `explain psychology 2`"
        
        if from_number not in last_explain_fields: 
            return "⚠️ Ask `explain psychology` first to see fields"
            
        field = last_explain_fields[from_number][idx]
        system = "You are a professor. Reply like a helpful friend. Use bold labels, emojis, clear sections. 10 bullet points max. Be complete but concise."
        prompt = f"Deep dive into '{topic}' from {field} perspective. Use examples."
        return groq_call(prompt, system=system)

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

def get_youtube_link(query):
    youtube_url = f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}"
    return f"🎵 *{query.title()}*\n\n▶️ Tap to play: {youtube_url}"

def solve_image_math(image_url):
    prompt = "Solve this math problem step by step. Show formula, working, and final answer. Be concise."
    return groq_vision(image_url, prompt)

def get_runtime():
    seconds = int(time.time() - start_time)
    h, m, s = seconds//3600, (seconds%3600)//60, seconds%60
    return f"{h}h {m}m {s}s"

def get_menu():
    lt = datetime.now(pytz.timezone('Africa/Lagos')).strftime("%I:%M %p")
    return f"""─────〔 *ARIA {VERSION}* 〕─────
👤 *Owner*: Sir
⏱️ *Runtime*: {get_runtime()}
🎵 *YT Mode*: Link Only
👁️ *Vision*: Pollinations Anonymous
🎨 *Style*: Presentable + Concise
🕒 *Time*: {lt}

『 *AI* 』
├─ ○ explain <topic>
├─ ○ explain <topic> <1-6>
├─ ○.describe *send image*
├─ ○.verify *send image*
└─ ○.solve *send image*

『 *MEDIA* 』
├─ ○.pint <keyword>
└─ ○.play <song name>

『 *TOOLS* 』
└─ ○.solve *for math images*"""

@app.route("/webhook", methods=["POST"])
def webhook():
    global last_explain_topic, user_waiting_image
    data = request.get_json()
    try:
        msg = data["entry"][0]["changes"][0]["value"]["messages"][0]
        from_number = msg["from"]
        
        if msg.get("type") == "image":
            image_id = msg["image"]["id"]
            media_info = requests.get(f"https://graph.facebook.com/v20.0/{image_id}", headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}).json()
            image_url = media_info.get("url")
            user_waiting_image[from_number] = {"url": image_url}
            send_text(from_number, "📸 *Image saved Sir*\n\nSend `.describe` `.verify` or `.solve`")
            return "OK", 200
        
        text = msg["text"]["body"].strip()
        tl = text.lower()
        
        if tl in [".describe", ".verify", ".solve"]:
            if user_waiting_image.get(from_number):
                img_data = user_waiting_image.pop(from_number)
                if tl == ".solve":
                    send_text(from_number, "🧮 *Solving...*")
                    result = solve_image_math(img_data["url"])
                else:
                    send_text(from_number, "👁️ *Analyzing image...*")
                    prompt = "Describe image and fact check it. Use bullet points." if tl == ".verify" else "Describe this image in detail. Identify objects, colors, text, style. Use bullet points."
                    result = groq_vision(img_data["url"], prompt)
                send_text(from_number, f"〔 *RESULT* 〕\n\n{result}")
            else:
                send_text(from_number, "⚠️ *Send image first Sir*")
            return "OK", 200
            
        if tl in [".status", ".menu"]:
            send_text(from_number, get_menu())
        elif tl.startswith(".pint"):
            query = text[5:].strip()
            send_text(from_number, f"🔍 *Searching Unsplash for:* {query}...")
            img_url, page_url = get_unsplash_image(query)
            if img_url: send_image_url(from_number, img_url, f"📸 Unsplash: {query}")
            else: send_text(from_number, "⚠️ *No images found Sir. Try fewer words.*")
        elif tl.startswith(".play"):
            query = text[5:].strip()
            result = get_youtube_link(query)
            send_text(from_number, result)
        elif tl.startswith("imagine") or tl.startswith("create"):
            prompt = text.split(" ", 1)[1]
            send_text(from_number, f"🎨 *Generating image for:* {prompt}...")
            send_image_url(from_number, f"https://image.pollinations.ai/prompt/{requests.utils.quote(prompt)}?width=1024&height=1024", f"AI: {prompt}")
        elif tl.startswith("explain"):
            parts = text.split(" ", 2)
            if len(parts) == 1: send_text(from_number, "⚠️ Usage: `explain <topic>`")
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
