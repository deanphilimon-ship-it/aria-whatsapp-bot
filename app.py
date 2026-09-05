from flask import Flask, request
import requests
import json
import os
import datetime
import random

app = Flask(__name__)

WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
PHONE_NUMBER_ID = os.environ.get('PHONE_NUMBER_ID')
OPENAI_KEY = os.environ.get('OPENAI_KEY') # ADD THIS TO RENDER ENV
SERPAPI_KEY = os.environ.get('SERPAPI_KEY') # ADD THIS TO RENDER ENV

# ============================================
# ARIA SYSTEM BOOT - JARVIS PERSONALITY
# ============================================
ARIA_BOOT = """**A.R.I.A // GIDEON CORE v3.0 ONLINE** ✅
**JARVIS Protocol Engaged**

[SYSTEM ONLINE]
> `Neural Net`: OpenAI GPT-4o Connected
> `Research Core`: SerpAPI + Google Live
> `Memory`: GIDEON Logging Active
> `Voice`: Conversational Mode: ON

**A.R.I.A**: "Good evening, Commander. All systems nominal. How may I assist you?" 🫡"""

# ============================================
# API FUNCTIONS
# ============================================
def ask_openai(prompt):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "system", "content": "You are ARIA, a JARVIS-style AI assistant for Commander. Be helpful, witty, tactical, and brief."},
                     {"role": "user", "content": prompt}],
        "max_tokens": 300
    }
    try:
        r = requests.post(url, headers=headers, json=data)
        return r.json()['choices'][0]['message']['content']
    except:
        return "Sir, my neural link to OpenAI is down. Please check OPENAI_KEY."

def google_search(query):
    url = f"https://serpapi.com/search.json?q={query}&api_key={SERPAPI_KEY}"
    try:
        r = requests.get(url).json()
        if 'organic_results' in r:
            top = r['organic_results'][0]
            return f"🔍 [GIDEON RESEARCH] {top['title']}\n{top['snippet']}\nLink: {top['link']}"
        return "No results found, Commander."
    except:
        return "Sir, SerpAPI connection failed. Check SERPAPI_KEY."

# ============================================
# MESSAGE HANDLER - CONVERSATIONAL
# ============================================
def handle_message(message, sender):
    message_lower = message.lower().strip()
    
    # COMMANDS
    if message_lower == "aria":
        return ARIA_BOOT
    
    elif "status" in message_lower:
        return """**ARIA SYSTEM STATUS:**
`aria` - Boot Jarvis
`status` - Show commands
`search <query>` - Real Google Search
`download mp3 <url>` - MP3 Protocol
`pinterest <query>` - Image Search
Or just talk to me naturally 😎"""
    
    elif message_lower.startswith("search "):
        query = message.replace("search ", "")
        return google_search(query)
    
    elif message_lower.startswith("download mp3 "):
        url = message.replace("download mp3 ", "")
        return f"⬇️ [MP3 PROTOCOL] Received: `{url}`\nNote: Add yt-dlp API to convert and send audio file."
    
    elif message_lower.startswith("pinterest "):
        query = message.replace("pinterest ", "")
        return f"📌 [PINTEREST SCAN] Searching: `{query}`\nNote: Add Pinterest API key to fetch real images."
    
    elif "time" in message_lower:
        lagos_time = datetime.datetime.now().strftime("%I:%M %p")
        return f"It's {lagos_time} in Lagos, Commander ⏰"
    
    elif "joke" in message_lower:
        jokes = ["Why don't robots get tired? Because they have backup! 😂"]
        return random.choice(jokes)
    
    # JARVIS CONVERSATIONAL MODE - DEFAULT
    else:
        return ask_openai(message)

# ============================================
# WHATSAPP WEBHOOK
# ============================================
def send_whatsapp_message(to, message):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": to, "text": {"body": message}}
    requests.post(url, headers=headers, json=data)

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        verify_token = os.environ.get('VERIFY_TOKEN')
        if request.args.get('hub.verify_token') == verify_token:
            return request.args.get('hub.challenge')
        return "Verification failed"
    
    if request.method == 'POST':
        data = request.get_json()
        try:
            message = data['entry'][0]['changes'][0]['value']['messages'][0]
            sender = message['from']
            text = message['text']['body']
            response = handle_message(text, sender)
            send_whatsapp_message(sender, response)
        except Exception as e:
            print(e)
        return "OK"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)What mode are we running tonight? 
1. **LORE BUILD** - 
2. **RESEARCH** - track 
3. **ENTERTAINMENT** - 
4. **.logcheck** - 

Your call, Commander """


# ============================================
# MESSAGE HANDLER
# ============================================
def handle_message(message, sender):
    message = message.lower().strip()
    
    # BOOT COMMAND
    if message == "aria":
        return ARIA_BOOT
    
    # STATUS COMMAND - was help
    elif "status" in message:
        return """**ARIA SYSTEM STATUS:**
`aria` - System Boot
`status` - Show commands
`search <query>` - Research Mode
`download <url>` - Download Protocol
`time` - Lagos time
`joke` - Random joke
`who are you` - About ARIA"""
    
    # SEARCH MODULE
    elif message.startswith("search "):
        query = message.replace("search ", "")
        return f"🔍 [RESEARCH MODE] GIDEON logged: `{query}`\n\nNote: Connect SerpAPI/Google to get real results. For now ARIA is tracking it."
    
    # DOWNLOAD MODULE 
    elif message.startswith("download "):
        url = message.replace("download ", "")
        return f"⬇️ [DOWNLOAD PROTOCOL] Queued: `{url}`\n\nNote: Add WhatsApp Media API logic here to fetch and send files."
    
    # TIME
    elif "time" in message:
        lagos_time = datetime.datetime.now().strftime("%I:%M %p")
        return f"Current time in Lagos is {lagos_time} ⏰"
    
    # JOKE
    elif "joke" in message:
        jokes = [
            "Why don't robots get tired? Because they have backup! 😂",
            "I would tell you a UDP joke, but you might not get it.",
            "Why did the AI go to therapy? Too many bytes of trauma 🤖"
        ]
        return random.choice(jokes)
    
    # ABOUT
    elif "who are you" in message:
        return "I am ARIA - Your Tactical AI Assistant. Built by you, running 24/7 🚀"
    
    else:
        return "Command not recognized. Type `status` or `aria` to boot system 👇"


# ============================================
# WHATSAPP WEBHOOK
# ============================================
def send_whatsapp_message(to, message):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {"body": message}
    }
    requests.post(url, headers=headers, json=data)


@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        verify_token = os.environ.get('VERIFY_TOKEN')
        if request.args.get('hub.verify_token') == verify_token:
            return request.args.get('hub.challenge')
        return "Verification failed"
    
    if request.method == 'POST':
        data = request.get_json()
        try:
            message = data['entry'][0]['changes'][0]['value']['messages'][0]
            sender = message['from']
            text = message['text']['body']
            
            response = handle_message(text, sender)
            send_whatsapp_message(sender, response)
            
        except Exception as e:
            print(e)
        return "OK"


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
