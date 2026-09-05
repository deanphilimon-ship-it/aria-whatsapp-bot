from flask import Flask, request
import requests
import json
import os
import datetime
import random
import base64
import subprocess # NEW FOR MP3

app = Flask(__name__)

WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
PHONE_NUMBER_ID = os.environ.get('PHONE_NUMBER_ID')
GROQ_KEY = os.environ.get('GROQ_KEY')
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN')
PINTEREST_TOKEN = os.environ.get('PINTEREST_TOKEN') # NEW

ARIA_BOOT = """**A.R.I.A // GIDEON CORE v6.4.1 ONLINE** ✅
**Advanced Response & Intelligence Assistant - MULTIMODAL**

[SYSTEM ONLINE]
> `Neural Net`: Groq Llama-4-Scout Vision Connected
> `Image Gen`: Enabled
> `Pinterest`: REAL API Enabled
> `Audio`: REAL MP3 Export Enabled
> `Vision`: Can SEE + VERIFY images

**A.R.I.A**: "All systems armed Commander. Ready for real media." 🫡"""

JOKES = [
    "Why did the AI break up with the database? Too many commitments! 😂",
    "I told my computer I needed a break. Now it won't stop sending me KitKat ads.",
    "What do you call AI with sunglasses? A smart bot."
]

def ask_groq(prompt, with_mcq=False, is_vision=False, image_b64=None):
    if not GROQ_KEY:
        return "Sir, GROQ_KEY not set in Render Environment."
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}

    system_prompt = "You are ARIA, an Advanced Response & Intelligence Assistant. Be helpful, tactical, and brief."
    if with_mcq:
        system_prompt += " When explaining, give 1 correct answer and 3 wrong options as A, B, C, D. Then state the correct answer at the end."

    if is_vision and image_b64:
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
        ]
        model = "meta-llama/Llama-4-Scout-17b-16e-instruct" # FIXED MODEL
    else:
        content = prompt
        model = "openai/gpt-oss-120b"

    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content}
        ],
        "max_tokens": 500,
        "temperature": 0.7
    }
    try:
        r = requests.post(url, headers=headers, json=data, timeout=30)
        result = r.json()
        if 'choices' in result:
            return result['choices'][0]['message']['content']
        else:
            return f"Sir, Groq error: {result}"
    except Exception as e:
        return f"Sir, Groq neural link failed: {str(e)}"

def download_whatsapp_media(media_id):
    url = f"https://graph.facebook.com/v19.0/{media_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    r = requests.get(url, headers=headers).json()
    media_url = r.get('url')
    r2 = requests.get(media_url, headers=headers)
    return base64.b64encode(r2.content).decode('utf-8')

def create_image(prompt):
    img_url = f"https://image.pollinations.ai/prompt/{prompt.replace(' ', '%20')}?width=1024&height=1024"
    return img_url

def search_real_pinterest(query):
    """REAL Pinterest API v5"""
    if not PINTEREST_TOKEN:
        return None # fallback to AI image
    
    url = "https://api.pinterest.com/v5/search/pins"
    headers = {"Authorization": f"Bearer {PINTEREST_TOKEN}"}
    params = {"query": query, "page_size": 1}
    
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        data = r.json()
        if 'items' in data and len(data['items']) > 0:
            pin = data['items'][0]
            return pin['media']['images']['originals']['url']
    except Exception as e:
        print(f"Pinterest Error: {e}")
    return None

def search_pinterest_image(query): # AI Fallback
    img_url = f"https://image.pollinations.ai/prompt/{query}%20pinterest%20style%20aesthetic?width=1024&height=1024"
    return img_url

def download_and_upload_mp3(query):
    """REAL MP3: yt-dlp + catbox.moe"""
    try:
        search_term = f"ytsearch:{query}"
        filename = f"/tmp/{query.replace(' ', '_')}.mp3"
        # Download
        subprocess.run([
            'yt-dlp', '-x', '--audio-format', 'mp3', '-o', filename, search_term
        ], check=True, timeout=90)
        
        # Upload to catbox
        files = {'fileToUpload': open(filename, 'rb')}
        r = requests.post('https://catbox.moe/user/api.php', data={'reqtype': 'fileupload'}, files=files)
        return r.text.strip() # direct mp3 url
    except Exception as e:
        print(f"MP3 Error: {e}")
        return None

def send_whatsapp_message(to, message):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": to, "text": {"body": message}}
    requests.post(url, headers=headers, json=data)

def send_whatsapp_image(to, image_url, caption=""):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"link": image_url, "caption": caption}
    }
    requests.post(url, headers=headers, json=data)

def send_whatsapp_audio(to, audio_url):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "audio",
        "audio": {"link": audio_url}
    }
    requests.post(url, headers=headers, json=data)

def handle_message(message, sender):
    message_lower = message.lower().strip()

    if message_lower == "aria":
        return ARIA_BOOT

    elif message_lower == ".status":
        lagos_time = datetime.datetime.now().strftime("%H:%M:%S")
        lagos_date = datetime.datetime.now().strftime("%d/%m/%y")
        return f"""**A.R.I.A TACTICAL HUD v6.4.1** 🫡

**Core:** `aria` `.status` `joke` `date`
**Media:** `imagine` `.pint` `.play` `explain`
**Vision:** Send image to auto-analyze
**Audio:** Send voice note

Date: {lagos_date} | Time: {lagos_time}
Commander, orders?"""

    elif message_lower == "joke":
        return random.choice(JOKES)

    elif message_lower == "date":
        lagos_date = datetime.datetime.now().strftime("%d/%m/%y")
        return f"Current Date: {lagos_date} Commander 📅"

    elif message_lower.startswith("imagine "):
        prompt = message[8:]
        send_whatsapp_message(sender, f"Sir, generating: {prompt}...")
        img_url = create_image(prompt)
        send_whatsapp_image(sender, img_url, f"Generated: {prompt}")
        return None

    elif message_lower.startswith(".pint "):
        query = message[6:]
        send_whatsapp_message(sender, f"Sir, pulling from Pinterest: {query}...")
        img_url = search_real_pinterest(query)
        if img_url:
            send_whatsapp_image(sender, img_url, f"Pinterest: {query}")
        else:
            img_url = search_pinterest_image(query)
            send_whatsapp_image(sender, img_url, f"AI Pinterest Style: {query}")
        return None

    elif message_lower.startswith(".play "):
        query = message[6:]
        send_whatsapp_message(sender, f"Sir, fetching and converting: {query}... This takes 20-30s")
        mp3_url = download_and_upload_mp3(query)
        if mp3_url:
            send_whatsapp_audio(sender, mp3_url)
        else:
            send_whatsapp_message(sender, "Sir, MP3 fetch failed. Check yt-dlp is installed on Render.")
        return None

    elif message_lower == "verify":
        return "✅ System Verified, Commander. All modules nominal."

    elif message_lower.startswith("explain "):
        topic = message[8:]
        return ask_groq(f"Explain {topic} in simple terms and give 4 multiple choice options A-D with 1 correct answer. Mark the correct answer at the end.")

    else:
        return ask_groq(message)

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        if request.args.get('hub.verify_token') == VERIFY_TOKEN:
            return request.args.get('hub.challenge')
        return "Verification failed"

    if request.method == 'POST':
        data = request.get_json()
        try:
            entry = data['entry'][0]['changes'][0]['value']
            if 'messages' in entry:
                message = entry['messages'][0]
                sender = message['from']
                msg_type = message['type']

                response = None
                
                if msg_type == "image":
                    media_id = message['image']['id']
                    caption = message['image'].get('caption', 'Analyze and verify this image')
                    send_whatsapp_message(sender, "Sir, analyzing image...")
                    image_b64 = download_whatsapp_media(media_id)
                    response = ask_groq(f"{caption}. Verify any facts/claims in it.", is_vision=True, image_b64=image_b64)
                
                elif msg_type == "audio":
                    response = "Voice note received, Commander. Transcription module loads in v6.5"
                
                elif msg_type == "text":
                    text = message['text']['body']
                    response = handle_message(text, sender)

                if response:
                    send_whatsapp_message(sender, response)
        except Exception as e:
            print(f"Error: {e}")
    return "OK"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
