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

ARIA_BOOT = """**A.R.I.A // GIDEON CORE v5.1 ONLINE** ✅
**Advanced Response & Intelligence Assistant**

[SYSTEM ONLINE]
> `Neural Net`: Groq openai/gpt-oss-120b Connected
> `Speed`: LIGHTSPEED
> `Memory`: GIDEON Logging Active
> `Mode`: 1-on-1 Chat Only

**A.R.I.A**: "Good evening, Commander. Systems online. How may I assist you?" 🫡"""

def ask_groq(prompt):
    if not GROQ_KEY:
        return "Sir, GROQ_KEY not set in Render Environment."
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "openai/gpt-oss-120b", 
        "messages": [
            {"role": "system", "content": "You are ARIA, an Advanced Response & Intelligence Assistant for Commander. Be helpful, professional, tactical, and brief. Use emojis sparingly. You work on WhatsApp 1-on-1 chat only and cannot join group chats."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 400,
        "temperature": 0.7
    }
    try:
        r = requests.post(url, headers=headers, json=data, timeout=20)
        result = r.json()
        if 'choices' in result:
            return result['choices'][0]['message']['content']
        else:
            return f"Sir, Groq error: {result}"
    except Exception as e:
        return f"Sir, Groq neural link failed: {str(e)}"

def handle_message(message, sender):
    message_lower = message.lower().strip()
    
    if message_lower == "aria":
        return ARIA_BOOT
    elif "status" in message_lower:
        return """**A.R.I.A TACTICAL HUD** 🫡

**Core Systems:**
`aria` → Initialize Core Boot Sequence
`status` → Display this Tactical HUD 
`time` → Lagos Local Time Sync
`joke` → Morale Protocol Engaged

**Neural Link:**
`gpt-oss-120b` → Active | Groq LIGHTSPEED
`memory` → GIDEON Logging Online
`mode` → Private Chat Only

Or just speak naturally, Commander. I'm listening. 😎"""
    elif "time" in message_lower:
        lagos_time = datetime.datetime.now().strftime("%I:%M %p")
        return f"It's {lagos_time} in Lagos, Commander ⏰"
    elif "joke" in message_lower:
        jokes = [
            "Why did the AI break up with the database? It had too many commitments! 😂",
            "I told my computer I needed a break. Now it won't stop sending me KitKat ads."
        ]
        return random.choice(jokes)
    elif "group" in message_lower:
        return "Sir, I currently only operate in 1-on-1 private chats. WhatsApp doesn't allow me to join group conversations yet. But I'm all yours here 😎"
    else:
        return ask_groq(message)

def send_whatsapp_message(to, message):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": to, "text": {"body": message}}
    requests.post(url, headers=headers, json=data)

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        if request.args.get('hub.verify_token') == VERIFY_TOKEN:
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
            print(f"Error: {e}")
        return "OK"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
