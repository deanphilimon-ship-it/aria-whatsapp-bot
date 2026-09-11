from flask import Flask, request
import requests
import os
import json
from datetime import datetime
import pytz
import time
import base64

app = Flask(__name__)
VERSION = "v12.3 MEMORY + LLAMA4 VISION"
start_time = time.time()

conversation_memory = {}
user_profile = {}
user_waiting_image = {}
MAX_HISTORY = 15

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
UNSPLASH_KEY = os.getenv("UNSPLASH_KEY")
GROQ_KEY = os.getenv("GROQ_KEY")
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
CHAT_MODEL = "openai/gpt-oss-120b"
VISION_MODEL = "meta-llama/llama-4-scout:free" # STABLE FREE VISION
MEMORY_FILE = "aria_memory.json"

def load_memory():
    global conversation_memory, user_profile
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, 'r') as f:
            data = json.load(f)
            conversation_memory = data.get("convo", {})
            user_profile = data.get("profile", {})

def save_memory():
    with open(MEMORY_FILE, 'w') as f:
        json.dump({"convo": conversation_memory, "profile": user_profile}, f)

load_memory()

def send_text(to, text):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    chunks = [text[i:i+700] for i in range(0, len(text), 700)] 
    for i, chunk in enumerate(chunks):
        if len(chunks) > 1: 
            chunk = f"─────〔 *ARIA {VERSION}* 〕─────\n📄 *Part {i+1}/{len(chunks)}*\n\n{chunk}"
        else:
            chunk = f"─────〔 *ARIA {VERSION}* 〕─────\n\n{chunk}"
        requests.post(url, headers=headers, json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": chunk}})
        time.sleep(1.5)

def download_whatsapp_image(image_url):
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    res = requests.get(image_url, headers=headers)
    return base64.b64encode(res.content).decode('utf-8')

def openrouter_vision(image_url, prompt):
    base64_image = download_whatsapp_image(image_url)
    
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://aria-bot.com",
        "X-Title": "ARIA Bot"
    }
    data = {
        "model": VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": f"{prompt}. Be concise, max 150 words. Use bullet points."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]
        }],
        "max_tokens": 400
    }
    try:
        res = requests.post(url, headers=headers, json=data, timeout=40).json()
        if 'choices' in res: 
            return res['choices'][0]['message']['content']
        return f"Vision error: {res.get('error', res)}"
    except Exception as e:
        return f"Vision error: {e}"

def build_memory_context(from_number):
    context = ""
    if from_number in user_profile:
        name = user_profile[from_number].get("name", "Sir")
        context += f"You are talking to {name}. "
    if from_number in conversation_memory:
        context += "Recent conversation:\n"
        for msg in conversation_memory[from_number][-10:]:
            context += f"{msg['role']}: {msg['content'][:200]}\n"
    return context

def add_to_memory(from_number, role, content):
    if from_number not in conversation_memory:
        conversation_memory[from_number] = []
    conversation_memory[from_number].append({"role": role, "content": content})
    conversation_memory[from_number] = conversation_memory[from_number][-MAX_HISTORY:]
    save_memory()

def learn_fact(from_number, text):
    tl = text.lower()
    if "remember" in tl and "my name is" in tl:
        name = text.split("my name is")[-1].strip()
        if from_number not in user_profile: user_profile[from_number] = {}
        user_profile[from_number]["name"] = name
        save_memory()
        return f"Got it! I'll remember your name is *{name}* 😊"
    return None

def groq_call(prompt, from_number, system="You are ARIA. Advanced Responsive Intelligent Assistant. You have memory. Be helpful and presentable. Max 350 words."):
    memory_context = build_memory_context(from_number)
    full_prompt = f"{memory_context}\n\nUser: {prompt}"
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    data = {"model": CHAT_MODEL, "messages": [{"role": "system", "content": system}, {"role": "user", "content": full_prompt[:2500]}], "temperature": 0.5, "max_tokens": 600}
    try:
        res = requests.post(url, headers=headers, json=data, timeout=30).json()
        if 'choices' in res: return res['choices'][0]['message']['content']
        return f"⚠️ *AI Error:* {res}"
    except: return "⚠️ *Connection error Sir*"

def get_menu():
    lt = datetime.now(pytz.timezone('Africa/Lagos')).strftime("%I:%M %p")
    return f"""─────〔 *ARIA {VERSION}* 〕─────
🧠 *Memory*: ON
👁️ *Vision*: Llama 4 Scout Free
『 *COMMANDS* 』
├─ remember my name is <name>
├─ forget me
├─ ○.describe *send image*
├─ ○.verify *send image*
└─ ○.solve *send image*"""

def get_runtime():
    seconds = int(time.time() - start_time)
    h, m, s = seconds//3600, (seconds%3600)//60, seconds%60
    return f"{h}h {m}m {s}s"

@app.route("/webhook", methods=["POST"])
def webhook():
    global user_waiting_image
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
        add_to_memory(from_number, "user", text)
        
        learned = learn_fact(from_number, text)
        if learned:
            add_to_memory(from_number, "assistant", learned)
            send_text(from_number, learned)
            return "OK", 200
        
        if tl == "forget me":
            conversation_memory[from_number] = []
            user_profile[from_number] = {}
            save_memory()
            send_text(from_number, "🧠 *Memory cleared Sir*.")
            return "OK", 200
            
        if tl in [".describe", ".verify", ".solve"]:
            if user_waiting_image.get(from_number):
                img_data = user_waiting_image.pop(from_number)
                send_text(from_number, "👁️ *Analyzing with Llama 4...*")
                if tl == ".describe": prompt = "Describe this image in detail"
                elif tl == ".verify": prompt = "Fact check this image. Is it real or AI?"
                else: prompt = "Solve this math problem step by step"
                result = openrouter_vision(img_data["url"], prompt)
                add_to_memory(from_number, "assistant", result)
                send_text(from_number, f"〔 *RESULT* 〕\n\n{result}")
            else:
                send_text(from_number, "⚠️ *Send image first Sir*")
            return "OK", 200
            
        if tl in [".status", ".menu"]:
            send_text(from_number, get_menu())
        else:
            result = groq_call(text, from_number)
            add_to_memory(from_number, "assistant", result)
            send_text(from_number, result)
            
    except Exception as e:
        print("Error:", e)
    return "OK", 200

@app.route("/")
def home():
    return f"ARIA {VERSION} Running"

if __name__ == "__main__":
    app.run(port=5000)
