from flask import Flask, request
import requests
import os

app = Flask(__name__)

WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
ACCESS_TOKEN = WHATSAPP_TOKEN

@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed", 403

@app.route("/", methods=["GET"])
def home():
    return "ARIA Bot is Live", 200

def send_message(to, text):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {"body": text}
    }
    requests.post(url, headers=headers, json=data)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print(data)

    if "messages" in data["entry"][0]["changes"][0]["value"]:
        message = data["entry"][0]["changes"][0]["value"]["messages"][0]
        phone_number = message["from"]
        message_text = message["text"]["body"]
        
        # COMMANDS START HERE
        if message_text.lower() == "hello aria":
            send_message(phone_number, "Hello Commander! ARIA is online and ready 🚀")
        elif message_text.lower() == "test":
            send_message(phone_number, "System check: All green ✅")
        elif message_text.lower() == "status":
            send_message(phone_number, "Available commands:\nhello aria\ntest\nhelp")
    
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
import datetime
import random
import requests # for search and downloads

# BOOT MESSAGE
ARIA_BOOT = """**A.R.I.A // SYSTEM BOOT COMPLETE** ✅
**COMMANDER_PROFILE.log  → LOADED**

[SYSTEM ONLINE]
> `Tactical Architect OS v2.4` initialized  
> `Palette Lock`: CYAN #00FFFF + SCARLET #FF2400 + GREY #808080  
> `Active Window`: 20:00 - 03:00 WAT → You’ve got 7 hours  
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
1.  **LORE BUILD** - 
2.  **RESEARCH** - track 
3.  **ENTERTAINMENT** - 
4.  **.logcheck** - 

Your call, Commander 🫡"""

def handle_message(message, sender):
    message = message.lower().strip()
    
    # BOOT COMMAND
    if "aria" == message:
        return ARIA_BOOT
    
    # BASIC COMMANDS
    elif "status" in message:
        return """ARIA COMMAND LIST:
`aria` - System Boot
`help` - Show commands
`search <query>` - Google search
`download <url>` - Download file
`time` - Lagos time
`joke` - Random joke"""
    
    # SEARCH MODULE
    elif message.startswith("search "):
        query = message.replace("search ", "")
        return f"🔍 [RESEARCH MODE] Searching for: {query}\n\nNote: Connect Google Search API or SerpAPI here for real results. For now ARIA logged it to GIDEON."
    
    # DOWNLOAD MODULE  
    elif message.startswith("download "):
        url = message.replace("download ", "")
        return f"⬇️ [DOWNLOAD PROTOCOL] Queued: {url}\n\nNote: Add file hosting logic here. ARIA will fetch and send the file."
    
    elif "time" in message:
        lagos_time = datetime.datetime.now().strftime("%I:%M %p")
        return f"Current time in Lagos is {lagos_time} ⏰"
    
    elif "joke" in message:
        jokes = [
            "Why don't robots get tired? Because they have backup! 😂",
            "I would tell you a UDP joke, but you might not get it.",
            "Why did the AI go to therapy? Too many bytes of trauma 🤖"
        ]
        return random.choice(jokes)
    
    else:
        return "Command not recognized. Type `help` or `aria` to boot system 👇"
