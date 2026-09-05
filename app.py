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
        elif message_text.lower() == "help":
            send_message(phone_number, "Available commands:\nhello aria\ntest\nhelp")
    
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
