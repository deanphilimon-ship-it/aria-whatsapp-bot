import os
import requests
import random
from flask import Flask, request
from dotenv import load_dotenv
import yt_dlp

load_dotenv()
app = Flask(__name__)

# ENV VARS
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
PINTEREST_TOKEN = os.getenv("PINTEREST_TOKEN")

# ========== WHATSAPP SENDERS ==========
def send_text(to, text):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {"body": text}
    }
    requests.post(url, headers=headers, json=data)

def send_image(to, image_url, caption=""):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"link": image_url, "caption": caption}
    }
    requests.post(url, headers=headers, json=data)

def send_audio(to, audio_url, filename="song.mp3"):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "audio",
        "audio": {"link": audio_url}
    }
    requests.post(url, headers=headers, json=data)

# ========== PINTEREST REAL ==========
def pinterest_search(query, token):
    url = "https://api.pinterest.com/v5/search/pins"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"query": query, "limit": 10}
    res = requests.get(url, headers=headers, params=params)
    
    if res.status_code!= 200:
        return None
    
    data = res.json()
    pins = data.get("items", [])
    if not pins:
        return None
    
    pin = random.choice(pins)
    image_url = pin["media"]["images"]["600x"]["url"]
    pin_link = f"https://pinterest.com/pin/{pin['id']}"
    return image_url, pin_link

# ========== YOUTUBE MP3 REAL ==========
def download_mp3(query):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'noplaylist': True,
        'quiet': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }
    
    os.makedirs("downloads", exist_ok=True)
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch:{query}", download=True)['entries'][0]
        title = info['title']
        filepath = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')
        return filepath, title

# ========== UPLOAD TO TEMP HOST ==========
# WhatsApp needs a public URL to send audio. Render Free can't host files.
# Use tmpfiles.org as free temp host
def upload_file(filepath):
    with open(filepath, 'rb') as f:
        res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
    return res.json()['data']['url'].replace('tmpfiles.org/', 'tmpfiles.org/dl/')

# ========== WEBHOOK ==========
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return request.args.get("hub.challenge")
    
    data = request.get_json()
    try:
        message = data["entry"][0]["changes"][0]["value"]["messages"][0]
        from_number = message["from"]
        text = message["text"]["body"]
        
        # COMMAND:.pint
        if text.startswith(".pint "):
            query = text.replace(".pint ", "")
            send_text(from_number, f"Searching Pinterest for: {query}...")
            
            result = pinterest_search(query, PINTEREST_TOKEN)
            if result:
                image_url, pin_link = result
                send_image(from_number, image_url, f"📌 {query}\nSource: {pin_link}")
            else:
                send_text(from_number, "No pins found. Try different keywords.")
        
        # COMMAND:.play
        elif text.startswith(".play "):
            query = text.replace(".play ", "")
            send_text(from_number, f"Downloading: {query}... This takes 20-30s on Render")
            
            try:
                filepath, title = download_mp3(query)
                audio_url = upload_file(filepath)
                send_audio(from_number, audio_url)
                send_text(from_number, f"🎵 {title}")
                os.remove(filepath) # cleanup
            except Exception as e:
                send_text(from_number, f"Download failed: {str(e)}")
        
        else:
            send_text(from_number, "Commands:\n.pint <keyword>\n.play <song name>")
            
    except Exception as e:
        print(e)
    
    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
