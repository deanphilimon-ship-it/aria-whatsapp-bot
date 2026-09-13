from flask import Flask, request
import requests
import os
import base64
import json
import re
from datetime import datetime
import pytz
import time
from groq import Groq

app = Flask(__name__)
VERSION = "v12.3 PREMIUM UI"
last_explain_topic = {}
last_explain_fields = {}
user_waiting_image = {}
start_time = time.time()

conversation_memory = {}
user_profile = {}
MAX_HISTORY = 15
MEMORY_FILE = "aria_memory.json"

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
UNSPLASH_KEY = os.getenv("UNSPLASH_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = Groq(api_key=GROQ_API_KEY)

CHAT_MODEL = "openai/gpt-oss-120b" 
FAST_MODEL = "qwen/qwen3.8-27b"
VISION_MODEL = "qwen/qwen3.6-27b"

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

def clean_ui(text):
    # Remove markdown tables and ### headers
    text = re.sub(r'\|.*\|', '', text) # remove table rows
    text = re.sub(r'---+', '', text) # remove ---
    text = re.sub(r'###\s*', '〔 *', text) # ### -> box
    text = text.replace('###', '〕')
    text = re.sub(r'\*\*', '*', text) # keep single * for bold
    return text.strip()

def send_text(to, text):
    text = clean_ui(text)
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    chunks = [text[i:i+650] for i in range(0, len(text), 650)] # smaller chunks
    for i, chunk in enumerate(chunks):
        if len(chunks) > 1: 
            header = f"┌─────〔 *ARIA {VERSION}* 〕─────┐\n📄 *Part {i+1}/{len(chunks)}*\n└──────────────────────────────┘\n\n"
        else:
            header = f"┌─────〔 *ARIA {VERSION}* 〕─────┐\n└──────────────────────────────┘\n\n"
        body = header + chunk
        requests.post(url, headers=headers, json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body}})
        time.sleep(1.2)

def ai_call(prompt, from_number, system="You are ARIA. Advanced Responsive Intelligent Assistant. Reply with clean WhatsApp UI. Use emojis, bold *text*, and bullet points. NO markdown tables, NO ###. Use '〔 *TITLE* 〕' for sections. Use '•' for bullets. Be presentable like Meta AI. Max 300 words."):
    memory_context = build_memory_context(from_number)
    full_prompt = f"{memory_context}\n\nUser: {prompt}"
    model = FAST_MODEL if len(full_prompt) > 1500 else CHAT_MODEL
    
    full_response = ""
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": full_prompt[:4000]}
            ],
            temperature=0.6,
            max_tokens=1024,
            top_p=0.95,
            stream=True
        )
        for chunk in stream:
            if chunk.choices[0].delta.content:
                full_response += chunk.choices[0].delta.content
        return full_response
    except Exception as e: 
        return f"⚠️ *AI Error:* {e}"

#... KEEP ALL YOUR OTHER FUNCTIONS THE SAME: vision_call, download_whatsapp_image, build_memory_context, add_to_memory, learn_fact...

def ai_explain(topic, field_num, from_number):
    fields = ["🧬 Biology", "🧪 Chemistry", "💊 Pharmacology", "🏥 Clinical", "🫀 Pathophysiology", "📝 Exam Tips"]
    if field_num == "all":
        last_explain_topic[from_number] = topic
        last_explain_fields[from_number] = fields
        result = f"〔 *{topic.title()} - 6 FIELDS* 〕\n\n"
        for i, f in enumerate(fields, 1): 
            result += f"{i}. {f}\n"
        result += f"\n💡 *Tip*: Reply `explain {topic} 3` for Pharmacology"
        return result
    else:
        try: idx = int(field_num) - 1
        except: return "⚠️ *Usage*: `explain psychology 2`"
        if from_number not in last_explain_fields: return "⚠️ Ask `explain psychology` first to see fields"
        field = last_explain_fields[from_number][idx]
        system = "You are a professor. Use clean UI. Start with '〔 *DEEP DIVE* 〕'. Use emojis and bullets. No tables. Max 10 points."
        prompt = f"Deep dive into '{topic}' from {field} perspective. Use examples."
        return ai_call(prompt, from_number, system=system)

def get_menu():
    lt = datetime.now(pytz.timezone('Africa/Lagos')).strftime("%I:%M %p")
    return f"""〔 *ARIA {VERSION}* 〕
👤 *Owner*: Sir
🧠 *Memory*: ON
⏱️ *Runtime*: {get_runtime()}
🤖 *Brain*: GPT-OSS 120B
👁️ *Vision*: Qwen3.6 27B
⚡ *Speed*: Qwen3.8 27B
🕒 *Time*: {lt}

〔 *AI COMMANDS* 〕
• `explain <topic>`
• `explain <topic> <1-6>`

〔 *VISION* 〕
• Send image → `.describe`
• Send image → `.verify` 
• Send image → `.solve`

〔 *MEMORY* 〕
• `remember my name is <name>`
• `forget me`

〔 *MEDIA* 〕
• `.pint <keyword>`
• `.play <song name>`
• `imagine <prompt>`"""

def get_runtime():
    seconds = int(time.time() - start_time)
    h, m, s = seconds//3600, (seconds%3600)//60, seconds%60
    return f"{h}h {m}m {s}s"

# KEEP webhook and all other functions from v12.2 EXACTLY THE SAME
# Just paste them below here...
