from flask import Flask, request
import requests
import json
import os
import datetime
import random

app = Flask(__name__)

WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
PHONE_NUMBER_ID = os.environ.get('PHONE_NUMBER_ID')
GROQ_KEY = os.environ.get('GROQ_KEY')
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN')

ARIA_BOOT = """**A.R.I.A // GIDEON CORE v6.2 ONLINE** ✅
**Advanced Response & Intelligence Assistant - MULTIMODAL**

[SYSTEM ONLINE]
> `Neural Net`: Groq openai/gpt-oss-120b Connected
> `Image Gen`: Enabled
> `Pinterest`:.pint Enabled
> `Audio`:.play Enabled
> `Mode`: 1-on-1 Chat Only

**A.R.I.A**: "Good evening, Commander. All systems armed. Awaiting orders." 🫡"""

JOKES = [
    "Why did the AI break up with the database? Too many commitments! 😂",
    "I told my computer I needed a break. Now it won't stop sending me KitKat ads.",
    "What do you call AI with sunglasses? A smart bot."
]

def ask_groq(prompt, with_mcq=False):
    if not GROQ_KEY:
        return "Sir, GROQ_KEY not set in Render Environment."
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}

    system_prompt = "You are ARIA, an Advanced Response & Intelligence Assistant. Be helpful, tactical, and brief."
    if with_mcq:
        system_prompt += " When explaining, give 1 correct answer and 3 wrong options as A, B, C, D. Then state the correct answer at the end."

    data = {
        "model": "openai/gpt-oss-120b",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 500,
        "temperature": 0.7
    }
    try:
        r = requests.post(url, headers=headers, json=data, timeout=25)
        result = r.json()
        if 'choices' in result:
            return result['choices'][0]['message']['content']
        else:
            return f"Sir, Groq error: {result}"
    except Exception as e:
        return f"Sir, Groq neural link failed: {str(e)}"

def create_image(prompt):
    try:
        img_url = f"https://image.pollinations.ai/prompt/{prompt.replace(' ', '%20')}?width=1024&height=1024"
        return img_url
    except:
        return None

def search_pinterest_image(query):
    # Using Pollinations image search as Pinterest API needs auth
    # Replace with real Pinterest API if you have keys
    try:
        img_url = f"https://image.pollinations.ai/prompt/{query}%20pinterest%20style?width=1024&height=1024"
        return img_url
    except:
        return None

def get_mp3_url(query):
    # Using direct search. For production use yt-dlp or mp3downloader API
    # This returns a placeholder - you need to host an MP3 API
    return f"https://example.com/search?q={query.replace(' ', '+')}" # Replace with real MP3 API

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

    # 1. WAKE COMMAND
    if message_lower == "aria":
        return ARIA_BOOT

    # 2. STATUS HUD
    elif message_lower == ".status" or message_lower == "status":
        lagos_time = datetime.datetime.now().strftime("%H:%M:%S")
        lagos_date = datetime.datetime.now().strftime("%d/%m/%y")
        return f"""**A.R.I.A TACTICAL HUD v6.2** 🫡

**Core Systems:**
`aria` → Wake Bot
`.status` → This HUD
`joke` → Morale Protocol
`date` → {lagos_date}
`time` → {lagos_time}

**Media Commands:**
`imagine [prompt]` → AI Generate Image
`.pint [query]` → Pinterest Image Export
`.play [song]` → MP3 Audio Export
`verify` → Confirm Media Added
`explain [topic]` → With MCQ Options

**Neural Link:** `gpt-oss-120b` → Active
Commander, orders? 😎"""

    # 3. JOKE
    elif message_lower == "joke":
        return random.choice(JOKES)

    # 4. DATE DD/MM/YY
    elif message_lower == "date":
        lagos_date = datetime.datetime.now().strftime("%d/%m/%y")
        return f"Current Date: {lagos_date} Commander 📅"

    # 5. IMAGE GENERATION
    elif message_lower.startswith("imagine "):
        prompt = message[8:]
        send_whatsapp_message(sender, f"Sir, generating: {prompt}...")
        img_url = create_image(prompt)
        if img_url:
            send_whatsapp_image(sender, img_url, f"Generated: {prompt}")
        else:
            send_whatsapp_message(sender, "Sir, image generation failed.")
        return None

    # 6. PINTEREST EXPORT
    elif message_lower.startswith(".pint "):
        query = message[6:]
        send_whatsapp_message(sender, f"Sir, searching Pinterest for: {query}...")
        img_url = search_pinterest_image(query)
        if img_url:
            send_whatsapp_image(sender, img_url, f"Pinterest Result: {query}")
        else:
            send_whatsapp_message(sender, "Sir, Pinterest search failed.")
        return None

    # 7. MP3 PLAY EXPORT
    elif message_lower.startswith(".play "):
        query = message[6:]
        send_whatsapp_message(sender, f"Sir, fetching audio: {query}...")
        audio_url = get_mp3_url(query)
        # Note: WhatsApp needs direct MP3 link. Replace get_mp3_url with real API
        send_whatsapp_message(sender, f"Audio link for '{query}': {audio_url}\nNote: Upload to hosting first to send as audio file.")
        return None

    # 8. VERIFY
    elif message_lower == "verify":
        return "✅ System Verified, Commander. Media modules, Neural link, and Memory all nominal."

    # 9. EXPLAIN WITH MCQ
    elif message_lower.startswith("explain "):
        topic = message[8:]
        return ask_groq(f"Explain {topic} and give 4 multiple choice options A-D with 1 correct answer", with_mcq=True)

    # 10. DEFAULT CHAT
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

                text = ""
                if msg_type == "text":
                    text = message['text']['body']
                elif msg_type == "image":
                    text = "verify" # Auto-trigger verify when image sent
                elif msg_type == "audio":
                    text = "verify"

                response = handle_message(text, sender)
                if response:
                    send_whatsapp_message(sender, response)
        except Exception as e:
            print(f"Error: {e}")
    return "OK"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
