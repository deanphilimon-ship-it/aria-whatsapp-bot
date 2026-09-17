from flask import Flask, request
import requests
import os
import base64
import json
import re
from datetime import datetime
import pytz
import time
import hashlib
from collections import defaultdict
from groq import Groq

app = Flask(__name__)
VERSION = "v12.9.8"
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
PEXELS_KEY = os.getenv("PEXELS_KEY") # Not used anymore
PIXABAY_KEY = os.getenv("PIXABAY_KEY")

client = Groq(api_key=GROQ_API_KEY)

CHAT_MODEL = "openai/gpt-oss-120b"
FAST_MODEL = "qwen/qwen3-32b"
VISION_MODEL = "meta-llama/llama-4-maverick-17b-128e-instruct"

OWNER_NUMBER = "2348026177804"
ALLOWED_USERS = ["2348XXXXXXXX", "2349XXXXXXX"]
PASSWORD = "ARIA" + datetime.now(pytz.timezone('Africa/Lagos')).strftime("%Y%W")
MAX_TRIES = 4
auth_tries = {}
authenticated_users = set()
BANNED_USERS = set()

COMICVINE_KEY = "bac15d29ffe11ced90b001b3827b2d20df130cfa"

api_requests = defaultdict(list)
LIMITS = {"pint4": 20, "pint1": 50, "pint2": 100, "pint5": 50}

def load_memory():
    global conversation_memory, user_profile, BANNED_USERS
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, 'r') as f:
            data = json.load(f)
            conversation_memory = data.get("convo", {})
            user_profile = data.get("profile", {})
            BANNED_USERS = set(data.get("banned", []))

def save_memory():
    with open(MEMORY_FILE, 'w') as f:
        json.dump({"convo": conversation_memory, "profile": user_profile, "banned": list(BANNED_USERS)}, f)

load_memory()

def check_rate_limit(number, api_name):
    now = time.time()
    key = f"{number}_{api_name}"
    api_requests[key] = [t for t in api_requests[key] if now - t < 3600]
    if len(api_requests[key]) >= LIMITS.get(api_name, 100):
        return False
    api_requests[key].append(now)
    return True

def check_auth(from_number, text):
    if from_number == OWNER_NUMBER or from_number in ALLOWED_USERS:
        authenticated_users.add(from_number)
        return True, ""
    if from_number in BANNED_USERS:
        return False, "⛔ *You are banned from using ARIA.*"
    if from_number in authenticated_users:
        return True, ""
    if text.strip().upper() == PASSWORD:
        authenticated_users.add(from_number)
        auth_tries[from_number] = 0
        return True, "✅ *Access Granted Sir*\n\nWelcome to ARIA."
    auth_tries[from_number] = auth_tries.get(from_number, 0) + 1
    if auth_tries[from_number] >= MAX_TRIES:
        BANNED_USERS.add(from_number)
        save_memory()
        return False, "⛔ *Locked*. Too many wrong attempts. You are banned."
    return False, f"🔒 *Private Bot*\n\nSend password to unlock.\nAttempts left: {MAX_TRIES - auth_tries[from_number]}"

def clean_ui(text):
    text = re.sub(r'\|.*\|', '', text)
    text = re.sub(r'---+', '', text)
    text = re.sub(r'###\s*', '〔 *', text)
    text = text.replace('###', '〕')
    text = re.sub(r'\*\*', '*', text)
    return text.strip()

def send_text(to, text):
    text = clean_ui(text)
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    chunks = [text[i:i+650] for i in range(0, len(text), 650)]
    for i, chunk in enumerate(chunks):
        if len(chunks) > 1:
            header = f"┌─────〔 *ARIA {VERSION}* 〕─────┐\n📄 *Part {i+1}/{len(chunks)}*\n└──────────────────────────────┘\n\n"
        else:
            header = f"┌─────〔 *ARIA {VERSION}* 〕─────┐\n└──────────────────────────────┘\n\n"
        body = header + chunk
        requests.post(url, headers=headers, json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body}})
        time.sleep(1.2)

def send_image_url(to, image_url, caption=""):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    requests.post(url, headers=headers, json={"messaging_product": "whatsapp", "to": to, "type": "image", "image": {"link": image_url, "caption": caption}})

def get_users_list():
    owner_text = f"👑 *OWNER*\n• {OWNER_NUMBER}\n\n"
    allowed_text = "🟢 *ALLOWED USERS - Skip Password*\n"
    for num in ALLOWED_USERS:
        if num!= OWNER_NUMBER:
            name = user_profile.get(num, {}).get("name", "Unknown")
            allowed_text += f"• {num} - *{name}*\n"
    if allowed_text == "🟢 *ALLOWED USERS - Skip Password*\n":
        allowed_text += "• None\n"
    auth_text = "\n🔓 *AUTHENTICATED USERS*\n"
    temp_list = [n for n in authenticated_users if n!= OWNER_NUMBER and n not in ALLOWED_USERS]
    if temp_list:
        for num in temp_list:
            name = user_profile.get(num, {}).get("name", "Unknown")
            auth_text += f"• {num} - *{name}*\n"
    else:
        auth_text += "• None yet\n"
    banned_text = "\n⛔ *BANNED USERS*\n"
    if BANNED_USERS:
        for num in BANNED_USERS:
            banned_text += f"• {num}\n"
    else:
        banned_text += "• None\n"
    total = len(set(ALLOWED_USERS + list(authenticated_users)))
    header = f"〔 *ARIA USERS PANEL* 〕\n*Total Active:* {total}\n\n"
    return header + owner_text + allowed_text + auth_text + banned_text

# PINT1 UNSPLASH
def pint1_unsplash(sender, query):
    if not check_rate_limit(sender, "pint1"):
        send_text(sender, "⛔ *Rate Limit*\n\nToo many searches. Try again later.")
        return
    send_text(sender, f"📌 Pint1 Unsplash: *{query}*...")
    url = f"https://api.unsplash.com/photos/random?query={requests.utils.quote(query)}&client_id={UNSPLASH_KEY}&orientation=portrait"
    try:
        res = requests.get(url, timeout=10).json()
        img_url = res["urls"]["regular"]
        photographer = res["user"]["name"]
        send_image_url(sender, img_url, caption=f"Pint1: {query}\nPhoto by {photographer} on Unsplash")
    except: send_text(sender, f"No results on Unsplash for: {query}")

# NEW PINT2 WALLHAVEN - NO KEY - FANTASY + AESTHETIC
def pint2_pexels(sender, query):
    if not check_rate_limit(sender, "pint2"):
        send_text(sender, "⛔ *Rate Limit*\n\nToo many searches. Try again later.")
        return
    send_text(sender, f"📌 Pint2 Wallhaven: *{query}*...")

    # Wallhaven - Best for fantasy wallpaper
    url = f"https://wallhaven.cc/api/v1/search?q={requests.utils.quote(query)}&sorting=random&atleast=1920x1080&ratios=16x9,9x16"
    try:
        res = requests.get(url, timeout=15).json()
        if res.get("data") and len(res["data"]) > 0:
            photo = res["data"][0]
            photo_url = photo["path"]
            resolution = photo.get("resolution", "4K")
            send_image_url(sender, photo_url, caption=f"🎨 Pint2: {query}\n{resolution} | Wallhaven | Aesthetic Wallpaper")
        else:
            raise Exception("No wallpapers")
    except Exception as e:
        print(f"Wallhaven error: {e}")
        # FALLBACK TO WIKIMEDIA + UNSPLASH
        try:
            url2 = f"https://api.unsplash.com/photos/random?query={requests.utils.quote(query)}&client_id={UNSPLASH_KEY}&orientation=portrait"
            res2 = requests.get(url2, timeout=10).json()
            img_url = res2["urls"]["regular"]
            send_image_url(sender, img_url, caption=f"Pint2 Fallback: {query}\nFrom Unsplash")
        except:
            # LAST FALLBACK - FLUX AI GENERATE
            ai_prompt = f"{query}, fantasy art, aesthetic wallpaper, ultra detailed, 4k"
            encoded = requests.utils.quote(ai_prompt)
            flux_url = f"https://image.pollinations.ai/prompt/{encoded}?model=flux&width=1024&height=1536&enhance=true&nologo=true"
            send_image_url(sender, flux_url, caption=f"Pint2 AI: {query}\nGenerated with FLUX - Fantasy Aesthetic")

# PINT3 DANBOORU - NO KEY
def pint3_anime(sender, query):
    send_text(sender, f"🎌 Pint3 Danbooru: *{query}*...")
    q = query.lower().replace(" ", "_")
    nsfw_tags = ["naked", "nude", "boobs", "pussy", "sex", "nsfw"]
    if any(tag in q for tag in nsfw_tags) and sender!= OWNER_NUMBER:
        send_text(sender, "⛔ *SFW Only*\n\nOwner can use NSFW tags. Try: Goku, Naruto, Luffy")
        return
    url = f"https://danbooru.donmai.us/posts.json?tags={q}&limit=1&random=true"
    headers = {"User-Agent": "ARIA-Bot/1.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        if res and len(res) > 0:
            post = res[0]
            file_url = post.get("large_file_url") or post.get("file_url")
            img_url = "https://danbooru.donmai.us" + file_url if file_url.startswith("/") else file_url
            tags = post["tag_string"].split()[:5]
            send_image_url(sender, img_url, caption=f"Pint3: {query}\nTags: {', '.join(tags)}\nSource: Danbooru")
        else:
            send_text(sender, f"No results for: *{query}*\n\nTry: Goku, Naruto, Luffy, Mikasa, Rem")
    except Exception as e:
        send_text(sender, f"Pint3 Error: {str(e)[:80]}\nTry different character")

def pint4_comics(sender, query):
    if not check_rate_limit(sender, "pint4"):
        send_text(sender, "⛔ *Rate Limit*\n\nToo many searches. Try again later.")
        return
    send_text(sender, f"📚 Pint4 Comics: *{query}*...")
    url = f"https://comicvine.gamespot.com/api/search/"
    params = {"api_key": COMICVINE_KEY, "format": "json", "query": query, "resources": "character,issue,volume", "limit": 1}
    headers = {"User-Agent": "ARIA-Bot/1.0"}
    try:
        res = requests.get(url, params=params, headers=headers, timeout=10).json()
        if res.get("status_code") == 1:
            if res["results"]:
                result = res["results"][0]
                name = result.get("name") or result.get("volume", {}).get("name", query)
                desc = result.get("deck", "No description")[:200]
                img_url = result.get("image", {}).get("super_url")
                if img_url:
                    send_image_url(sender, img_url, caption=f"Pint4: {name}\n{desc}...\nType: {result['resource_type']}")
                else:
                    send_text(sender, f"Pint4: {name}\n{desc}...")
            else: send_text(sender, f"No comics found for: *{query}*. Try 'Batman', 'Spider-Man'")
        else:
            send_text(sender, f"⚠️ ComicVine Error: {res.get('error', 'Unknown')}")
    except: send_text(sender, f"⚠️ ComicVine is slow. Try again in 10s")

def pint5_education(sender, query):
    if not check_rate_limit(sender, "pint5"):
        send_text(sender, "⛔ *Rate Limit*\n\nToo many searches. Try again later.")
        return
    send_text(sender, f"🧪 Pint5 Education: *{query}*... Searching diagrams")
    edu_query = f"{query} diagram laboratory apparatus scientific chart"
    url = f"https://api.unsplash.com/photos/random?query={requests.utils.quote(edu_query)}&client_id={UNSPLASH_KEY}&orientation=landscape"
    try:
        res = requests.get(url, timeout=10).json()
        img_url = res["urls"]["regular"]
        photographer = res["user"]["name"]
        send_image_url(sender, img_url, caption=f"🧪 Pint5: {query}\nEducational Diagram + Apparatus\nPhoto by {photographer} on Unsplash")
    except:
        ai_prompt = f"detailed educational diagram of {query}, labeled apparatus, scientific illustration, clean white background"
        send_text(sender, f"Using AI to generate diagram for: {query}")
        send_image_url(sender, f"https://image.pollinations.ai/prompt/{requests.utils.quote(ai_prompt)}?model=flux&width=1024&height=768&enhance=true&nologo=true", f"Pint5 AI: {query}\nEducational Diagram")

# NEW FLUX IMAGINE - BETTER QUALITY
def imagine_generate(sender, prompt):
    send_text(sender, f"🎨 *FLUX AI Generating:* {prompt}...")
    encoded = requests.utils.quote(prompt + ", ultra detailed, 8k, cinematic lighting, sharp focus, fantasy art")
    flux_url = f"https://image.pollinations.ai/prompt/{encoded}?model=flux&width=1024&height=1024&enhance=true&nologo=true&seed={hash(prompt) % 10000}"
    try:
        send_image_url(sender, flux_url, caption=f"FLUX: {prompt}\nModel: FLUX.1-dev | Enhanced")
    except:
        turbo_url = f"https://image.pollinations.ai/prompt/{encoded}?model=turbo&width=1024&height=1024&nologo=true"
        send_image_url(sender, turbo_url, caption=f"AI: {prompt}\nModel: Turbo Fallback")

def ai_call(prompt, from_number, system="You are ARIA. Advanced Responsive Intelligent Assistant. Reply with clean WhatsApp UI. Use emojis, bold *text*, and bullet points. NO markdown tables, NO ###. Use '〔 *TITLE* 〕' for sections. Use '•' for bullets. Be presentable like Meta AI. Max 300 words."):
    memory_context = build_memory_context(from_number)
    full_prompt = f"{memory_context}\n\nUser: {prompt}"
    model = FAST_MODEL if len(full_prompt) > 1500 else CHAT_MODEL
    full_response = ""
    try:
        stream = client.chat.completions.create(model=model, messages=[{"role": "system", "content": system},{"role": "user", "content": full_prompt[:4000]}], temperature=0.6, max_tokens=1024, top_p=0.95, stream=True)
        for chunk in stream:
            if chunk.choices[0].delta.content: full_response += chunk.choices[0].delta.content
        return full_response
    except Exception as e: return f"⚠️ *AI Error:* {e}"

# VISION WITH 4-MODEL FALLBACK
def vision_call(image_url, prompt):
    base64_image = download_whatsapp_image(image_url)
    short_prompt = f"{prompt}. Think step by step. Be concise. Use bullet points. Max 150 words."
    models_to_try = [
        "meta-llama/llama-4-maverick-17b-128e-instruct",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "meta-llama/llama-3.2-90b-vision-preview",
        "meta-llama/llama-3.2-11b-vision-preview"
    ]
    for model_name in models_to_try:
        try:
            full_response = ""
            stream = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user","content": [{"type": "text", "text": short_prompt},{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}],
                temperature=0.3, max_tokens=500, stream=True)
            for chunk in stream:
                if chunk.choices[0].delta.content: full_response += chunk.choices[0].delta.content
            if full_response:
                print(f"Vision success: {model_name}")
                return full_response
        except Exception as e:
            print(f"Vision failed {model_name}: {e}")
            continue
    return f"⚠️ *All Vision models failed.* Try again in 30s."

def download_whatsapp_image(image_url):
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    res = requests.get(image_url, headers=headers)
    return base64.b64encode(res.content).decode('utf-8')

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
    if from_number not in conversation_memory: conversation_memory[from_number] = []
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

def ai_explain(topic, field_num, from_number):
    fields = ["🧬 Biology", "🧪 Chemistry", "💊 Pharmacology", "🏥 Clinical", "🫀 Pathophysiology", "📝 Exam Tips"]
    if field_num == "all":
        last_explain_topic[from_number] = topic
        last_explain_fields[from_number] = fields
        result = f"〔 *{topic.title()} - 6 FIELDS* 〕\n\n"
        for i, f in enumerate(fields, 1): result += f"{i}. {f}\n"
        result += f"\n💡 *Tip*: Reply `explain {topic} 3` for Pharmacology"
        return result
    else:
        try: idx = int(field_num) - 1
        except: return "*Usage:* `explain psychology 2`"
        if from_number not in last_explain_fields: return "⚠️ Ask `explain psychology` first to see fields"
        field = last_explain_fields[from_number][idx]
        system = "You are a professor. Use clean UI. Start with '〔 *DEEP DIVE* 〕'. Use emojis and bullets. No tables. Max 10 points."
        prompt = f"Deep dive into '{topic}' from {field} perspective. Use examples."
        return ai_call(prompt, from_number, system=system)

def get_youtube_link(query):
    youtube_url = f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}"
    return f"🎵 *{query.title()}*\n\n▶️ Tap to play: {youtube_url}"

def solve_image_math(image_url):
    return vision_call(image_url, "Solve this math problem step by step. Show formula, working, and final answer.")

def get_runtime():
    seconds = int(time.time() - start_time)
    h, m, s = seconds//3600, (seconds%3600)//60, seconds%60
    return f"{h}h {m}m {s}s"

def get_menu():
    lt = datetime.now(pytz.timezone('Africa/Lagos')).strftime("%I:%M %p")
    return f"""〔 *ARIA {VERSION}* 〕
👤 *Owner*: Sir
🧠 *Memory*: ON
⏱️ *Runtime*: {get_runtime()}
🔒 *Security*: ADMIN LOCK
🤖 *Brain*: GPT-OSS 120B + Qwen3-32b
👁️ *Vision*: Llama-4 Maverick Fallback (4 models)
🎨 *Imagine*: FLUX.1-dev Enhanced
🕒 *Time*: {lt}

〔 *AI COMMANDS* 〕
- `explain <topic>`
- `explain <topic> <1-6>`

〔 *VISION* 〕
- Send image → `.describe`
- Send image → `.verify`
- Send image → `.solve`

〔 *OWNER ONLY* 〕
- `.users` = View all bot users
- `.ban <number>`
- `.unban <number>`

〔 *MEDIA - ALL FIXED* 〕
- `.pint1 <keyword>`
- `.pint2 <keyword>`
- `.pint3 <character>` 
- `.pint4 <keyword>`
- `.pint5 <subject>`
- `imagine <prompt>` 
- `.play <song name>`"""

@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    global last_explain_topic, user_waiting_image
    if request.method == "GET": return request.args.get("hub.challenge")
    data = request.get_json()
    try:
        msg = data["entry"][0]["changes"][0]["value"]["messages"][0]
        from_number = msg["from"]
        text = msg.get("text", {}).get("body", "").strip()
        tl = text.lower()

        is_auth, auth_msg = check_auth(from_number, text)
        if not is_auth: send_text(from_number, auth_msg); return "OK", 200
        if auth_msg: send_text(from_number, auth_msg)

        if text.lower().startswith(".ban "):
            if from_number == OWNER_NUMBER:
                target = text.split(" ")[1]; BANNED_USERS.add(target); save_memory(); send_text(from_number, f"⛔ Banned: {target}")
            else: send_text(from_number, "⛔ *Owner only command*")
            return "OK", 200
        if text.lower().startswith(".unban "):
            if from_number == OWNER_NUMBER:
                target = text.split(" ")[1]; BANNED_USERS.discard(target); save_memory(); send_text(from_number, f"✅ Unbanned: {target}")
            else: send_text(from_number, "⛔ *Owner only command*")
            return "OK", 200
        if tl == ".users":
            if from_number == OWNER_NUMBER:
                users_list = get_users_list()
                send_text(from_number, users_list)
            else:
                send_text(from_number, "⛔ *Owner only command*")
            return "OK", 200

        if msg.get("type") == "image":
            image_id = msg["image"]["id"]
            media_info = requests.get(f"https://graph.facebook.com/v20.0/{image_id}", headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}).json()
            image_url = media_info.get("url")
            user_waiting_image[from_number] = {"url": image_url}
            send_text(from_number, "📸 *Image saved Sir*\n\nSend `.describe` `.verify` or `.solve`")
            return "OK", 200

        add_to_memory(from_number, "user", text)
        learned = learn_fact(from_number, text)
        if learned: add_to_memory(from_number, "assistant", learned); send_text(from_number, learned); return "OK", 200

        if tl == "forget me": conversation_memory[from_number] = []; user_profile[from_number] = {}; save_memory(); send_text(from_number, "🧠 *Memory cleared Sir*."); return "OK", 200
        if tl in [".describe", ".verify", ".solve"]:
            if user_waiting_image.get(from_number):
                img_data = user_waiting_image.pop(from_number)
                if tl == ".solve": send_text(from_number, "🧮 *Solving...*"); result = solve_image_math(img_data["url"])
                elif tl == ".verify": send_text(from_number, "👁️ *Verifying image...*"); result = vision_call(img_data["url"], "Fact check this image. Is it real or AI? Give 3 signs.")
                else: send_text(from_number, "👁️ *Analyzing image...*"); result = vision_call(img_data["url"], "Describe this image in detail. Identify objects, colors, text, style.")
                add_to_memory(from_number, "assistant", result); send_text(from_number, f"〔 *RESULT* 〕\n\n{result}")
            else: send_text(from_number, "⚠️ *Send image first Sir*")
            return "OK", 200

        if tl.startswith(".pint1 "): pint1_unsplash(from_number, text[7:]); return "OK", 200
        if tl.startswith(".pint2 "): pint2_pexels(from_number, text[7:]); return "OK", 200
        if tl.startswith(".pint3 "): pint3_anime(from_number, text[7:]); return "OK", 200
        if tl.startswith(".pint4 "): pint4_comics(from_number, text[7:]); return "OK", 200
        if tl.startswith(".pint5 "): pint5_education(from_number, text[7:]); return "OK", 200

        if tl == ".status" or tl == ".menu": send_text(from_number, get_menu())
        elif tl.startswith(".play"): query = text[5:].strip(); result = get_youtube_link(query); send_text(from_number, result)
        elif tl.startswith("imagine") or tl.startswith("create"):
            parts = text.split(" ", 1)
            if len(parts) < 2 or not parts[1].strip():
                send_text(from_number, "⚠️ *Usage:* `imagine <prompt>`\n\nExample: `imagine cyberpunk city at night`")
            else:
                imagine_generate(from_number, parts[1])
        elif tl.startswith("explain"):
            parts = text.split(" ", 2)
            if len(parts) == 1:
                result = "*Usage:* `explain <topic>`"
            elif len(parts) == 2:
                result = ai_explain(parts[1], "all", from_number)
            else:
                result = ai_explain(parts[1], parts[2], from_number)
            add_to_memory(from_number, "assistant", result)
            send_text(from_number, result)
        else: result = ai_call(text, from_number); add_to_memory(from_number, "assistant", result); send_text(from_number, result)

    except Exception as e: print("Error:", e)
    return "OK", 200

@app.route("/")
def home(): return f"ARIA {VERSION} Running"

if __name__ == "__main__": app.run(host="0.0.0.0", port=5000)
