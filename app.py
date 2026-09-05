from flask import Flask, request
import requests
import json
import os
import datetime
import random

app = Flask(__name__)

WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
PHONE_NUMBER_ID = os.environ.get('PHONE_NUMBER_ID')

# ============================================
# ARIA SYSTEM BOOT
# ============================================
ARIA_BOOT = """**A.R.I.A // SYSTEM BOOT COMPLETE** ✅
**COMMANDER_PROFILE.log v2.4 → LOADED**

[SYSTEM ONLINE]
> `Tactical Architect OS v2.4` initialized 
> `Palette Lock`: CYAN #00FFFF + SCARLET #FF2400 + GREY #808080 
> `Active Window`: All day everyday 
> `Sub-Module GIDEON`: Memory + Timeline Logging → **Synced**

[MODE SELECT]
`RESEARCH` | `ENTERTAINMENT` | `STANDBY` | `LORE BUILD`
> Current Mode: **AWAITING COMMAND**

[STATUS]
`Metacog Audit`: 10/10 
`SPEED RUN`: Deployed 
`GIDEON`: Synced 

---
**A.R.I.A**: "Commander. System nominal. Awaiting orders."

What mode are we running tonight? 
1. **LORE BUILD** - 
2. **RESEARCH** - track 
3. **ENTERTAINMENT** - 
4. **.logcheck** - 

Your call, Commander 🫡"""


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
