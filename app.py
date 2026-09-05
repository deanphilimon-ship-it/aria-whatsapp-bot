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

def ask_groq(prompt):
    if not GROQ_KEY:
        return "Sir, GROQ_KEY not set in Render Environment."
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "llama-3.1-8b-instant", # ONLY MODEL THAT WORKS
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 400
    }
    try:
        r = requests.post(url, headers=headers, json=data, timeout=20)
        result = r.json()
        return result['choices'][0]['message']['content']
    except Exception as e:
        return f"Sir, Groq error: {result}"

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
            response = ask_groq(text)
            send_whatsapp_message(sender, response)
        except Exception as e:
            print(f"Error: {e}")
        return "OK"
