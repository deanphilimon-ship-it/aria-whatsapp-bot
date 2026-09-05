    from flask import Flask, request
    import requests
    import os

    app = Flask(__name__)

    WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
    PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")
    VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")

    @app.route("/webhook", methods=["GET"])
    def verify():
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        return "Verification failed", 403

    @app.route("/webhook", methods=["POST"])
    def webhook():
        data = request.get_json()
        print(data)
        return "ok", 200

    @app.route("/", methods=["GET"])
    def home():
        return "ARIA Bot is Live", 200

    if __name__ == "__main__":
        app.run(host="0.0.0.0", port=10000)
