from flask import Flask, request
import requests
import json
import os
import datetime
import random

app = Flask(__name__)

WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
PHONE_NUMBER_ID = os.environ.get('PHONE_NUMBER_ID')
OPENAI_KEY = os.environ.get('OPENAI_KEY')
SERPAPI_KEY = os.environ.get('SERPAPI_KEY')

ARIA_BOOT = """**A.R.I.A // GIDEON CORE v3.0 ONLINE** ✅
**JARVIS Protocol Engaged**

[SYSTEM ONLINE]
> `Neural Net`: OpenAI GPT-4o Connected
> `Research Core`: SerpAPI + Google Live
> `Memory`: GIDEON Logging Active
> `Voice`: Conversational Mode: ON

**A.R.I.A**: "Good evening, Commander. All systems nominal. How may I assist you?" 🫡"""

def ask_openai(prompt):
    if not OPENAI_KEY:
        return "Sir, OPENAI_KEY not set in Render Environment."
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
        return "Sir, my neural link to OpenAI is down."

def google_search(query):
    if not SERPAPI_KEY:
        return "Sir, SERPAPI_KEY not set in Render Environment."
    url = f"https://serpapi.com/search.json?q={query}&api_key={SERPAPI_KEY}"
    try:
        r = requests.get(url).json()
        if 'organic_results' in r:
            top = r['organic_results'][0]
            return f"🔍 [GIDEON RESEARCH] {top['title']}\n{top['snippet']}\nLink: {top['link']}"
        return "No results found, Commander."
    except:
        return "Sir, SerpAPI connection failed."

def handle_message(message, sender):
    message_lower = message.lower().strip()
    
    if message_lower == "aria":
        return ARIA_BOOT
    elif "status" in message_lower:
        return "**ARIA SYSTEM STATUS:**\n`aria` - Boot Jarvis\n`status` - Show commands\n`search <query>` - Real Google Search\nOr just talk to me naturally 😎"
    elif message_lower.startswith("search "):
        query = message.replace("search ", "")
        return google_search(query)
    elif "time" in message_lower:
        lagos_time = datetime.datetime.now().strftime("%I:%M %p")
        return f"It's {lagos_time} in Lagos, Commander ⏰"
    elif "joke" in message_lower:
        return "Why don't robots get tired? Because they have backup! 😂"
    else:
        return ask_openai(message)

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
    app.run(host='0.0.0.0', port=10000)
