from flask import Flask, request
import requests
import os
import base64
import json
import re
from datetime import datetime
import pytz
import time
from collections import defaultdict
from groq import Groq


# ============================================================
# ARIA - Advanced Responsive Intelligent Assistant
# Patched Version
# ============================================================

app = Flask(__name__)

VERSION = "v13.0.0"

last_explain_topic = {}
last_explain_fields = {}
user_waiting_image = {}

start_time = time.time()

conversation_memory = {}
user_profile = {}

MAX_HISTORY = 15
MEMORY_FILE = "aria_memory.json"


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

UNSPLASH_KEY = os.getenv("UNSPLASH_KEY")
PIXABAY_KEY = os.getenv("PIXABAY_KEY")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ComicVine key should be stored in Render Environment Variables.
# If you have not created COMICVINE_KEY there yet, the bot will
# still run, but Pint4 will report that the key is missing.
COMICVINE_KEY = os.getenv("COMICVINE_KEY")


# ============================================================
# GROQ MODELS
# ============================================================

# Main text/reasoning model
CHAT_MODEL = "openai/gpt-oss-120b"

# Current Groq multimodal vision model
VISION_MODEL = "qwen/qwen3.8-27b"


# ============================================================
# GROQ CLIENT
# ============================================================

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


# ============================================================
# ACCESS CONTROL
# ============================================================

OWNER_NUMBER = "2348026177804"

ALLOWED_USERS = [
    "2348XXXXXXXX",
    "2349XXXXXXX"
]

PASSWORD = (
    "ARIA"
    + datetime.now(
        pytz.timezone("Africa/Lagos")
    ).strftime("%Y%W")
)

MAX_TRIES = 4

auth_tries = {}
authenticated_users = set()
BANNED_USERS = set()


# ============================================================
# RATE LIMITS
# ============================================================

api_requests = defaultdict(list)

LIMITS = {
    "pint1": 20,
    "pint2": 100,
    "pint4": 20,
    "pint5": 50,
}


# ============================================================
# MEMORY
# ============================================================

def load_memory():
    global conversation_memory
    global user_profile
    global BANNED_USERS

    if not os.path.exists(MEMORY_FILE):
        return

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        conversation_memory = data.get("convo", {})
        user_profile = data.get("profile", {})
        BANNED_USERS = set(data.get("banned", []))

    except Exception as e:
        print(f"[MEMORY LOAD ERROR] {repr(e)}")


def save_memory():
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "convo": conversation_memory,
                    "profile": user_profile,
                    "banned": list(BANNED_USERS)
                },
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:
        print(f"[MEMORY SAVE ERROR] {repr(e)}")


load_memory()


# ============================================================
# RATE LIMITER
# ============================================================

def check_rate_limit(number, api_name):
    now = time.time()
    key = f"{number}_{api_name}"

    api_requests[key] = [
        t
        for t in api_requests[key]
        if now - t < 3600
    ]

    if len(api_requests[key]) >= LIMITS.get(api_name, 100):
        return False

    api_requests[key].append(now)
    return True


# ============================================================
# AUTHENTICATION
# ============================================================

def check_auth(from_number, text):

    if from_number == OWNER_NUMBER or from_number in ALLOWED_USERS:
        authenticated_users.add(from_number)
        return True, ""

    if from_number in BANNED_USERS:
        return False, "You are banned from using ARIA."

    if from_number in authenticated_users:
        return True, ""

    if text.strip().upper() == PASSWORD:
        authenticated_users.add(from_number)
        auth_tries[from_number] = 0

        return (
            True,
            "Access Granted.\n\nWelcome to ARIA."
        )

    auth_tries[from_number] = (
        auth_tries.get(from_number, 0) + 1
    )

    if auth_tries[from_number] >= MAX_TRIES:

        BANNED_USERS.add(from_number)
        save_memory()

        return (
            False,
            "Locked. Too many incorrect attempts."
        )

    remaining = MAX_TRIES - auth_tries[from_number]

    return (
        False,
        "Private Bot\n\n"
        "Send password to unlock.\n"
        f"Attempts left: {remaining}"
    )


# ============================================================
# WHATSAPP TEXT CLEANUP
# ============================================================

def clean_ui(text):

    if not text:
        return ""

    text = str(text)

    # Remove accidental pipe tables
    text = re.sub(r"\|.*\|", "", text)

    # Remove horizontal markdown rules
    text = re.sub(r"---+", "", text)

    # Convert markdown headings into ARIA sections
    text = re.sub(
        r"###\s*",
        "〔 *",
        text
    )

    text = text.replace(
        "###",
        "〕"
    )

    # WhatsApp already supports *bold*
    # Convert markdown **bold** to WhatsApp *bold*
    text = re.sub(
        r"\*\*",
        "*",
        text
    )

    # Prevent excessive whitespace
    text = re.sub(
        r"\n{4,}",
        "\n\n",
        text
    )

    return text.strip()


# ============================================================
# SEND WHATSAPP TEXT
# ============================================================

def send_text(to, text):

    text = clean_ui(text)

    if not text:
        text = "I couldn't generate a response."

    url = (
        f"https://graph.facebook.com/v20.0/"
        f"{PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    # WhatsApp has message size limitations.
    chunks = [
        text[i:i + 650]
        for i in range(0, len(text), 650)
    ]

    for i, chunk in enumerate(chunks):

        if len(chunks) > 1:

            header = (
                f"┌─────〔 *ARIA {VERSION}* 〕─────┐\n"
                f"*Part {i + 1}/{len(chunks)}*\n"
                f"└──────────────────────────────┘\n\n"
            )

        else:

            header = (
                f"┌─────〔 *ARIA {VERSION}* 〕─────┐\n"
                f"└──────────────────────────────┘\n\n"
            )

        body = header + chunk

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {
                "body": body
            }
        }

        try:

            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=20
            )

            if not response.ok:
                print(
                    "[WHATSAPP SEND ERROR]",
                    response.status_code,
                    response.text[:1000]
                )

        except Exception as e:

            print(
                f"[WHATSAPP SEND EXCEPTION] {repr(e)}"
            )

        time.sleep(0.8)


# ============================================================
# SEND IMAGE TO WHATSAPP
# ============================================================

def send_image_url(to, image_url, caption=""):

    if not image_url:
        send_text(
            to,
            "I couldn't find an image to send."
        )
        return False

    url = (
        f"https://graph.facebook.com/v20.0/"
        f"{PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {
            "link": image_url,
            "caption": caption[:1024]
        }
    }

    try:

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30
        )

        if not response.ok:

            print(
                "[WHATSAPP IMAGE ERROR]",
                response.status_code,
                response.text[:1000]
            )

            send_text(
                to,
                "WhatsApp couldn't send that image."
            )

            return False

        return True

    except Exception as e:

        print(
            f"[WHATSAPP IMAGE EXCEPTION] {repr(e)}"
        )

        send_text(
            to,
            "The image could not be delivered."
        )

        return False


# ============================================================
# USER PANEL
# ============================================================

def get_users_list():

    owner_text = (
        f"OWNER\n"
        f"• {OWNER_NUMBER}\n\n"
    )

    allowed_text = (
        "ALLOWED USERS - Skip Password\n"
    )

    for num in ALLOWED_USERS:

        if num != OWNER_NUMBER:

            name = (
                user_profile
                .get(num, {})
                .get("name", "Unknown")
            )

            allowed_text += (
                f"• {num} - *{name}*\n"
            )

    if allowed_text == (
        "ALLOWED USERS - Skip Password\n"
    ):

        allowed_text += "• None\n"

    auth_text = (
        "\nAUTHENTICATED USERS\n"
    )

    temp_list = [
        n
        for n in authenticated_users
        if n != OWNER_NUMBER
        and n not in ALLOWED_USERS
    ]

    if temp_list:

        for num in temp_list:

            name = (
                user_profile
                .get(num, {})
                .get("name", "Unknown")
            )

            auth_text += (
                f"• {num} - *{name}*\n"
            )

    else:

        auth_text += "• None yet\n"

    banned_text = (
        "\nBANNED USERS\n"
    )

    if BANNED_USERS:

        for num in BANNED_USERS:
            banned_text += f"• {num}\n"

    else:

        banned_text += "• None\n"

    total = len(
        set(
            ALLOWED_USERS
            + list(authenticated_users)
        )
    )

    header = (
        f"〔 *ARIA USERS PANEL* 〕\n"
        f"*Total Active:* {total}\n\n"
    )

    return (
        header
        + owner_text
        + allowed_text
        + auth_text
        + banned_text
    )


# ============================================================
# PINT1 - UNSPLASH
# ============================================================

def pint1_unsplash(sender, query):

    if not UNSPLASH_KEY:

        send_text(
            sender,
            "Unsplash is not configured."
        )

        return

    if not check_rate_limit(sender, "pint1"):

        send_text(
            sender,
            "Too many Unsplash searches. Try again later."
        )

        return

    send_text(
        sender,
        f"Pint1 Unsplash: *{query}*..."
    )

    url = (
        "https://api.unsplash.com/photos/random"
        f"?query={requests.utils.quote(query)}"
        f"&client_id={UNSPLASH_KEY}"
        "&orientation=portrait"
    )

    try:

        response = requests.get(
            url,
            timeout=15
        )

        response.raise_for_status()

        res = response.json()

        img_url = res["urls"]["regular"]
        photographer = res["user"]["name"]

        send_image_url(
            sender,
            img_url,
            caption=(
                f"Pint1: {query}\n"
                f"Photo by {photographer} on Unsplash"
            )
        )

    except Exception as e:

        print(
            f"[UNSPLASH ERROR] {repr(e)}"
        )

        send_text(
            sender,
            f"No results on Unsplash for: {query}"
        )


# ============================================================
# PINT2 - WALLHAVEN
# ============================================================

def pint2_pexels(sender, query):

    if not check_rate_limit(sender, "pint2"):

        send_text(
            sender,
            "Too many wallpaper searches. Try again later."
        )

        return

    send_text(
        sender,
        f"Pint2 Wallhaven: *{query}*..."
    )

    url = (
        "https://wallhaven.cc/api/v1/search"
        f"?q={requests.utils.quote(query)}"
        "&sorting=random"
        "&atleast=1920x1080"
        "&ratios=16x9,9x16"
    )

    try:

        response = requests.get(
            url,
            timeout=15
        )

        response.raise_for_status()

        res = response.json()

        if res.get("data"):

            photo = res["data"][0]

            photo_url = photo.get("path")

            resolution = photo.get(
                "resolution",
                "Unknown resolution"
            )

            if photo_url:

                send_image_url(
                    sender,
                    photo_url,
                    caption=(
                        f"Pint2: {query}\n"
                        f"{resolution} | Wallhaven"
                    )
                )

                return

        raise Exception("No wallpapers found")

    except Exception as e:

        print(
            f"[WALLHAVEN ERROR] {repr(e)}"
        )

    # Unsplash fallback

    if UNSPLASH_KEY:

        try:

            url2 = (
                "https://api.unsplash.com/photos/random"
                f"?query={requests.utils.quote(query)}"
                f"&client_id={UNSPLASH_KEY}"
                "&orientation=portrait"
            )

            response2 = requests.get(
                url2,
                timeout=15
            )

            response2.raise_for_status()

            res2 = response2.json()

            img_url = res2["urls"]["regular"]

            send_image_url(
                sender,
                img_url,
                caption=(
                    f"Pint2 Fallback: {query}\n"
                    "From Unsplash"
                )
            )

            return

        except Exception as e:

            print(
                f"[UNSPLASH FALLBACK ERROR] {repr(e)}"
            )

    # Final AI image fallback

    ai_prompt = (
        f"{query}, fantasy art, "
        "aesthetic wallpaper, ultra detailed, "
        "high quality"
    )

    encoded = requests.utils.quote(
        ai_prompt
    )

    flux_url = (
        "https://image.pollinations.ai/prompt/"
        f"{encoded}"
        "?model=flux"
        "&width=1024"
        "&height=1536"
        "&enhance=true"
        "&nologo=true"
    )

    send_image_url(
        sender,
        flux_url,
        caption=(
            f"Pint2 AI: {query}\n"
            "Generated with FLUX"
        )
    )


# ============================================================
# PINT3 - DANBOORU
# ============================================================

def pint3_anime(sender, query):

    q = query.lower().replace(" ", "_")

    nsfw_tags = [
        "naked",
        "nude",
        "boobs",
        "pussy",
        "sex",
        "nsfw"
    ]

    if (
        any(tag in q for tag in nsfw_tags)
        and sender != OWNER_NUMBER
    ):

        send_text(
            sender,
            "SFW only. Try Goku, Naruto, Luffy, etc."
        )

        return

    send_text(
        sender,
        f"Pint3 Danbooru: *{query}*..."
    )

    url = (
        "https://danbooru.donmai.us/posts.json"
        f"?tags={requests.utils.quote(q)}"
        "&limit=1"
        "&random=true"
    )

    headers = {
        "User-Agent": "ARIA-Bot/1.0"
    }

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=15
        )

        response.raise_for_status()

        res = response.json()

        if not res:

            send_text(
                sender,
                f"No results for: *{query}*\n\n"
                "Try: Goku, Naruto, Luffy, Mikasa, Rem"
            )

            return

        post = res[0]

        file_url = (
            post.get("large_file_url")
            or post.get("file_url")
        )

        if not file_url:

            send_text(
                sender,
                "Danbooru returned a result without an image."
            )

            return

        if file_url.startswith("/"):
            img_url = (
                "https://danbooru.donmai.us"
                + file_url
            )
        else:
            img_url = file_url

        tags = post.get(
            "tag_string",
            ""
        ).split()[:5]

        send_image_url(
            sender,
            img_url,
            caption=(
                f"Pint3: {query}\n"
                f"Tags: {', '.join(tags)}\n"
                "Source: Danbooru"
            )
        )

    except Exception as e:

        print(
            f"[DANBOORU ERROR] {repr(e)}"
        )

        send_text(
            sender,
            "Danbooru failed. Try a different character."
        )


# ============================================================
# PINT4 - COMICVINE
# ============================================================

def pint4_comics(sender, query):

    if not COMICVINE_KEY:

        send_text(
            sender,
            "ComicVine is not configured. "
            "Add COMICVINE_KEY to Render environment variables."
        )

        return

    if not check_rate_limit(sender, "pint4"):

        send_text(
            sender,
            "Too many comic searches. Try again later."
        )

        return

    send_text(
        sender,
        f"Pint4 Comics: *{query}*..."
    )

    url = (
        "https://comicvine.gamespot.com/api/search/"
    )

    params = {
        "api_key": COMICVINE_KEY,
        "format": "json",
        "query": query,
        "resources": "character,issue,volume",
        "limit": 1
    }

    headers = {
        "User-Agent": "ARIA-Bot/1.0"
    }

    try:

        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=15
        )

        response.raise_for_status()

        res = response.json()

        if res.get("status_code") != 1:

            send_text(
                sender,
                "ComicVine returned an API error."
            )

            return

        results = res.get(
            "results",
            []
        )

        if not results:

            send_text(
                sender,
                f"No comics found for: *{query}*"
            )

            return

        result = results[0]

        name = (
            result.get("name")
            or result.get("volume", {}).get(
                "name",
                query
            )
        )

        desc = (
            result.get(
                "deck",
                "No description"
            )[:200]
        )

        image_data = result.get(
            "image",
            {}
        )

        img_url = image_data.get(
            "super_url"
        )

        resource_type = result.get(
            "resource_type",
            "unknown"
        )

        if img_url:

            send_image_url(
                sender,
                img_url,
                caption=(
                    f"Pint4: {name}\n"
                    f"{desc}...\n"
                    f"Type: {resource_type}"
                )
            )

        else:

            send_text(
                sender,
                f"Pint4: {name}\n"
                f"{desc}..."
            )

    except Exception as e:

        print(
            f"[COMICVINE ERROR] {repr(e)}"
        )

        send_text(
            sender,
            "ComicVine failed. Try again in a few seconds."
        )


# ============================================================
# PINT5 - EDUCATION
# ============================================================

def pint5_education(sender, query):

    if not check_rate_limit(sender, "pint5"):

        send_text(
            sender,
            "Too many education searches. Try again later."
        )

        return

    send_text(
        sender,
        f"Pint5 Education: *{query}*...\n"
        "Searching diagrams."
    )

    edu_query = (
        f"{query} diagram laboratory apparatus "
        "scientific chart"
    )

    if UNSPLASH_KEY:

        url = (
            "https://api.unsplash.com/photos/random"
            f"?query={requests.utils.quote(edu_query)}"
            f"&client_id={UNSPLASH_KEY}"
            "&orientation=landscape"
        )

        try:

            response = requests.get(
                url,
                timeout=15
            )

            response.raise_for_status()

            res = response.json()

            img_url = res["urls"]["regular"]

            photographer = res["user"]["name"]

            send_image_url(
                sender,
                img_url,
                caption=(
                    f"Pint5: {query}\n"
                    "Educational Diagram / Apparatus\n"
                    f"Photo by {photographer} on Unsplash"
                )
            )

            return

        except Exception as e:

            print(
                f"[PINT5 UNSPLASH ERROR] {repr(e)}"
            )

    ai_prompt = (
        f"detailed educational diagram of {query}, "
        "labeled scientific apparatus, "
        "clean white background, "
        "clear educational illustration"
    )

    send_text(
        sender,
        f"Using AI to generate a diagram for: {query}"
    )

    encoded = requests.utils.quote(
        ai_prompt
    )

    image_url = (
        "https://image.pollinations.ai/prompt/"
        f"{encoded}"
        "?model=flux"
        "&width=1024"
        "&height=768"
        "&enhance=true"
        "&nologo=true"
    )

    send_image_url(
        sender,
        image_url,
        caption=f"Pint5 AI: {query}\nEducational Diagram"
    )


# ============================================================
# IMAGE GENERATION
# ============================================================

def imagine_generate(sender, prompt):

    send_text(
        sender,
        f"FLUX AI generating:\n*{prompt}*..."
    )

    enhanced_prompt = (
        prompt
        + ", ultra detailed, "
        "cinematic lighting, sharp focus, "
        "high quality, professional artwork"
    )

    encoded = requests.utils.quote(
        enhanced_prompt
    )

    # Use a deterministic seed that is stable across
    # the current process.
    seed = int(
        hashlib.sha256(
            prompt.encode("utf-8")
        ).hexdigest()[:8],
        16
    ) % 100000

    flux_url = (
        "https://image.pollinations.ai/prompt/"
        f"{encoded}"
        "?model=flux"
        "&width=1024"
        "&height=1024"
        "&enhance=true"
        "&nologo=true"
        f"&seed={seed}"
    )

    success = send_image_url(
        sender,
        flux_url,
        caption=(
            f"FLUX: {prompt}\n"
            "Model: FLUX"
        )
    )

    if not success:

        turbo_url = (
            "https://image.pollinations.ai/prompt/"
            f"{encoded}"
            "?model=turbo"
            "&width=1024"
            "&height=1024"
            "&nologo=true"
        )

        send_image_url(
            sender,
            turbo_url,
            caption=(
                f"AI: {prompt}\n"
                "Fallback: Turbo"
            )
        )


# ============================================================
# MAIN AI CALL
# ============================================================

DEFAULT_SYSTEM_PROMPT = """
You are ARIA, an advanced WhatsApp AI assistant.

IDENTITY
- Your name is ARIA.
- Be intelligent, practical, direct and conversational.
- Do not pretend to be human.
- Do not claim to have seen, checked or verified something you did not actually receive or access.

RESPONSE STYLE
- Respond naturally for WhatsApp.
- Keep normal answers concise.
- Use short paragraphs and bullet points when useful.
- Use WhatsApp formatting such as *bold* sparingly.
- Do not use markdown tables.
- Do not use ### headings.
- Do not unnecessarily repeat the user's question.
- Do not add filler.
- For simple questions, give a simple answer.
- For complex questions, explain the important reasoning clearly.
- Maximum normal response length: about 300 words unless the user asks for detail.

ACCURACY
- If you are uncertain, say so.
- Never invent sources, facts, API results, files, events, or personal memories.
- Distinguish facts from assumptions.
- When the user asks for current information and no live tool/data is available, state that limitation instead of pretending the information is current.

MEMORY
- Use supplied conversation memory when it is relevant.
- Do not claim to remember information that is not present in the supplied memory.
- If the user asks you to forget something, follow the application's memory behavior.

PROBLEM SOLVING
- Solve the actual problem instead of giving generic advice.
- For calculations, show enough working to make the answer understandable.
- For technical problems, identify the likely cause before suggesting a fix.

WHATSAPP
- Keep formatting clean and readable.
- Use • for bullet points when appropriate.
- Avoid excessive emojis.
"""


def ai_call(
    prompt,
    from_number,
    system=DEFAULT_SYSTEM_PROMPT
):

    if not client:

        return (
            "AI is not configured. "
            "GROQ_API_KEY is missing."
        )

    memory_context = build_memory_context(
        from_number
    )

    full_prompt = (
        f"{memory_context}\n\n"
        f"User: {prompt}"
    )

    # Keep enough room for the response while preventing
    # enormous memory prompts from consuming the context.
    user_content = full_prompt[:12000]

    try:

        completion = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": system
                },
                {
                    "role": "user",
                    "content": user_content
                }
            ],
            temperature=0.6,
            max_completion_tokens=1024,
            top_p=0.95,
            stream=False,
            reasoning_effort="medium",
            reasoning_format="hidden"
        )

        response = (
            completion.choices[0]
            .message
            .content
        )

        if not response:

            return (
                "I received an empty response from the AI."
            )

        return response.strip()

    except Exception as e:

        print(
            f"[AI ERROR] {repr(e)}"
        )

        return (
            "AI request failed.\n\n"
            "Try again in a few seconds."
        )


# ============================================================
# WHATSAPP MEDIA DOWNLOAD
# ============================================================

def download_whatsapp_image(
    image_url,
    mime_type=None
):

    if not image_url:

        raise ValueError(
            "WhatsApp returned no image URL."
        )

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}"
    }

    response = requests.get(
        image_url,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    if not response.content:

        raise ValueError(
            "Downloaded image is empty."
        )

    # Prefer MIME type supplied by WhatsApp.
    # Fall back to HTTP response header.
    detected_mime = (
        mime_type
        or response.headers.get(
            "Content-Type",
            "image/jpeg"
        )
    )

    detected_mime = detected_mime.split(";")[0].strip()

    if not detected_mime.startswith("image/"):

        raise ValueError(
            f"Downloaded media is not an image: {detected_mime}"
        )

    # Groq's current vision endpoint has a 20 MB image limit.
    image_size_mb = (
        len(response.content)
        / (1024 * 1024)
    )

    if image_size_mb > 20:

        raise ValueError(
            f"Image is too large ({image_size_mb:.1f} MB). "
            "Maximum supported size is 20 MB."
        )

    encoded = base64.b64encode(
        response.content
    ).decode("utf-8")

    return encoded, detected_mime


# ============================================================
# VISION
# ============================================================

def vision_call(
    image_url,
    prompt,
    mime_type=None
):

    if not client:

        return (
            "Vision is not configured. "
            "GROQ_API_KEY is missing."
        )

    try:

        base64_image, detected_mime = (
            download_whatsapp_image(
                image_url,
                mime_type
            )
        )

        vision_prompt = (
            f"{prompt}\n\n"
            "Be accurate and concise. "
            "If something cannot be determined from the image, "
            "say that clearly instead of guessing."
        )

        completion = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": vision_prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": (
                                    f"data:{detected_mime};"
                                    f"base64,{base64_image}"
                                )
                            }
                        }
                    ]
                }
            ],
            temperature=0.3,
            max_completion_tokens=800,
            top_p=0.9,
            stream=False,
            reasoning_effort="none"
        )

        response = (
            completion.choices[0]
            .message
            .content
        )

        if not response:

            raise ValueError(
                "Vision model returned an empty response."
            )

        print(
            f"[VISION SUCCESS] {VISION_MODEL}"
        )

        return response.strip()

    except Exception as e:

        print(
            f"[VISION ERROR] {repr(e)}"
        )

        return (
            "I couldn't process that image.\n\n"
            "Try sending the image again."
        )


# ============================================================
# MEMORY CONTEXT
# ============================================================

def build_memory_context(from_number):

    context = ""

    if from_number in user_profile:

        name = (
            user_profile[from_number]
            .get("name", "Sir")
        )

        context += (
            f"You are talking to {name}. "
        )

    if from_number in conversation_memory:

        context += (
            "Recent conversation:\n"
        )

        for msg in conversation_memory[
            from_number
        ][-10:]:

            role = msg.get(
                "role",
                "unknown"
            )

            content = msg.get(
                "content",
                ""
            )

            context += (
                f"{role}: "
                f"{content[:300]}\n"
            )

    return context


def add_to_memory(
    from_number,
    role,
    content
):

    if from_number not in conversation_memory:

        conversation_memory[from_number] = []

    conversation_memory[from_number].append(
        {
            "role": role,
            "content": content
        }
    )

    conversation_memory[from_number] = (
        conversation_memory[from_number]
        [-MAX_HISTORY:]
    )

    save_memory()


# ============================================================
# LEARN USER FACTS
# ============================================================

def learn_fact(
    from_number,
    text
):

    lower_text = text.lower()

    if (
        "remember" in lower_text
        and "my name is" in lower_text
    ):

        match = re.search(
            r"my name is\s+(.+)",
            text,
            re.IGNORECASE
        )

        if not match:
            return None

        name = match.group(1).strip()

        if not name:
            return None

        if from_number not in user_profile:
            user_profile[from_number] = {}

        user_profile[from_number]["name"] = name

        save_memory()

        return (
            f"Got it. I'll remember your name is *{name}*."
        )

    return None


# ============================================================
# EDUCATIONAL EXPLANATIONS
# ============================================================

def ai_explain(
    topic,
    field_num,
    from_number
):

    fields = [
        "Biology",
        "Chemistry",
        "Pharmacology",
        "Clinical",
        "Pathophysiology",
        "Exam Tips"
    ]

    if field_num == "all":

        last_explain_topic[
            from_number
        ] = topic

        last_explain_fields[
            from_number
        ] = fields

        result = (
            f"〔 *{topic.title()} - 6 FIELDS* 〕\n\n"
        )

        for i, field in enumerate(
            fields,
            1
        ):

            result += (
                f"{i}. {field}\n"
            )

        result += (
            f"\nReply `explain {topic} 3` "
            "for Pharmacology."
        )

        return result

    try:

        idx = int(field_num) - 1

    except ValueError:

        return (
            "Usage: `explain psychology 2`"
        )

    if from_number not in last_explain_fields:

        return (
            "Ask `explain psychology` first "
            "to see the fields."
        )

    if idx < 0 or idx >= len(
        last_explain_fields[from_number]
    ):

        return (
            "Choose a field from 1 to 6."
        )

    field = (
        last_explain_fields[from_number][idx]
    )

    system = """
You are a knowledgeable professor helping a student.

Explain the requested topic from the specified field.

Requirements:
- Be accurate.
- Teach rather than merely define.
- Use clear examples.
- Use bullet points when useful.
- No markdown tables.
- No ### headings.
- Keep the explanation organized.
- Highlight exam-relevant points.
- If the topic has important exceptions, mention them.
"""

    prompt = (
        f"Deep dive into '{topic}' "
        f"from the {field} perspective. "
        "Use examples and exam-relevant details."
    )

    return ai_call(
        prompt,
        from_number,
        system=system
    )


# ============================================================
# YOUTUBE
# ============================================================

def get_youtube_link(query):

    youtube_url = (
        "https://www.youtube.com/results?search_query="
        + requests.utils.quote(query)
    )

    return (
        f"*{query.title()}*\n\n"
        f"▶️ Tap to search: {youtube_url}"
    )


# ============================================================
# IMAGE MATH
# ============================================================

def solve_image_math(
    image_url,
    mime_type=None
):

    return vision_call(
        image_url,
        """
Solve the math problem shown in the image.

Read the problem carefully.
Show the important formula or method.
Show the calculations.
Give the final answer clearly.
If the image is too unclear to read, say so.
""",
        mime_type
    )


# ============================================================
# RUNTIME
# ============================================================

def get_runtime():

    seconds = int(
        time.time() - start_time
    )

    h = seconds // 3600

    m = (
        seconds % 3600
    ) // 60

    s = seconds % 60

    return (
        f"{h}h {m}m {s}s"
    )


# ============================================================
# MENU
# ============================================================

def get_menu():

    local_time = datetime.now(
        pytz.timezone("Africa/Lagos")
    ).strftime("%I:%M %p")

    return f"""
〔 *ARIA {VERSION}* 〕

*Memory:* ON
*Runtime:* {get_runtime()}
*Security:* ADMIN LOCK

*Brain:* GPT-OSS 120B
*Vision:* Qwen 3.8 27B
*Imagine:* FLUX

*Time:* {local_time}

〔 *AI COMMANDS* 〕

• `explain <topic>`
• `explain <topic> <1-6>`

〔 *VISION* 〕

• Send image → `.describe`
• Send image → `.verify`
• Send image → `.solve`

〔 *OWNER* 〕

• `.users`
• `.ban <number>`
• `.unban <number>`

〔 *MEDIA* 〕

• `.pint1 <keyword>`
• `.pint2 <keyword>`
• `.pint3 <character>`
• `.pint4 <keyword>`
• `.pint5 <subject>`
• `imagine <prompt>`
• `.play <song name>`
"""


# ============================================================
# WEBHOOK
# ============================================================

@app.route(
    "/webhook",
    methods=["POST", "GET"]
)
def webhook():

    global last_explain_topic
    global user_waiting_image

    # --------------------------------------------------------
    # META VERIFICATION
    # --------------------------------------------------------

    if request.method == "GET":

        challenge = request.args.get(
            "hub.challenge"
        )

        verify_token = request.args.get(
            "hub.verify_token"
        )

        expected_verify_token = os.getenv(
            "VERIFY_TOKEN"
        )

        # If VERIFY_TOKEN is configured, validate it.
        if expected_verify_token:

            if verify_token != expected_verify_token:

                return "Forbidden", 403

        return challenge or "OK", 200

    # --------------------------------------------------------
    # PARSE WEBHOOK
    # --------------------------------------------------------

    try:

        data = request.get_json(
            silent=True
        )

        if not data:

            return "OK", 200

        entries = data.get(
            "entry",
            []
        )

        if not entries:

            return "OK", 200

        changes = entries[0].get(
            "changes",
            []
        )

        if not changes:

            return "OK", 200

        value = changes[0].get(
            "value",
            {}
        )

        messages = value.get(
            "messages",
            []
        )

        # Status updates and other webhook events
        # don't contain messages.
        if not messages:

            return "OK", 200

        msg = messages[0]

        from_number = msg.get(
            "from"
        )

        if not from_number:

            return "OK", 200

        text = (
            msg.get("text", {})
            .get("body", "")
            .strip()
        )

        tl = text.lower()

        # ----------------------------------------------------
        # AUTHENTICATION
        # ----------------------------------------------------

        is_auth, auth_msg = check_auth(
            from_number,
            text
        )

        if not is_auth:

            send_text(
                from_number,
                auth_msg
            )

            return "OK", 200

        if auth_msg:

            send_text(
                from_number,
                auth_msg
            )

        # ----------------------------------------------------
        # OWNER COMMANDS
        # ----------------------------------------------------

        if tl.startswith(".ban "):

            if from_number == OWNER_NUMBER:

                parts = text.split(
                    None,
                    1
                )

                if len(parts) < 2:

                    send_text(
                        from_number,
                        "Usage: `.ban <number>`"
                    )

                    return "OK", 200

                target = parts[1].strip()

                BANNED_USERS.add(
                    target
                )

                authenticated_users.discard(
                    target
                )

                save_memory()

                send_text(
                    from_number,
                    f"Banned: {target}"
                )

            else:

                send_text(
                    from_number,
                    "Owner only command."
                )

            return "OK", 200

        if tl.startswith(".unban "):

            if from_number == OWNER_NUMBER:

                parts = text.split(
                    None,
                    1
                )

                if len(parts) < 2:

                    send_text(
                        from_number,
                        "Usage: `.unban <number>`"
                    )

                    return "OK", 200

                target = parts[1].strip()

                BANNED_USERS.discard(
                    target
                )

                save_memory()

                send_text(
                    from_number,
                    f"Unbanned: {target}"
                )

            else:

                send_text(
                    from_number,
                    "Owner only command."
                )

            return "OK", 200

        if tl == ".users":

            if from_number == OWNER_NUMBER:

                users_list = get_users_list()

                send_text(
                    from_number,
                    users_list
                )

            else:

                send_text(
                    from_number,
                    "Owner only command."
                )

            return "OK", 200

        # ----------------------------------------------------
        # IMAGE MESSAGE
        # ----------------------------------------------------

        if msg.get("type") == "image":

            image_data = msg.get(
                "image",
                {}
            )

            image_id = image_data.get(
                "id"
            )

            incoming_mime_type = (
                image_data.get(
                    "mime_type"
                )
                or "image/jpeg"
            )

            if not image_id:

                send_text(
                    from_number,
                    "I couldn't retrieve that image."
                )

                return "OK", 200

            try:

                media_response = requests.get(
                    (
                        "https://graph.facebook.com/"
                        f"v20.0/{image_id}"
                    ),
                    headers={
                        "Authorization":
                        f"Bearer {WHATSAPP_TOKEN}"
                    },
                    timeout=15
                )

                media_response.raise_for_status()

                media_info = (
                    media_response.json()
                )

                image_url = media_info.get(
                    "url"
                )

                media_mime_type = (
                    media_info.get(
                        "mime_type"
                    )
                    or incoming_mime_type
                )

                if not image_url:

                    raise ValueError(
                        "Meta did not return a media URL."
                    )

                user_waiting_image[
                    from_number
                ] = {
                    "url": image_url,
                    "mime_type": media_mime_type
                }

                send_text(
                    from_number,
                    "Image received.\n\n"
                    "Send `.describe`, `.verify` "
                    "or `.solve`."
                )

            except Exception as e:

                print(
                    f"[WHATSAPP MEDIA ERROR] {repr(e)}"
                )

                send_text(
                    from_number,
                    "I couldn't retrieve that image "
                    "from WhatsApp. Try sending it again."
                )

            return "OK", 200

        # ----------------------------------------------------
        # MEMORY / USER FACTS
        # ----------------------------------------------------

        if text:

            add_to_memory(
                from_number,
                "user",
                text
            )

        learned = learn_fact(
            from_number,
            text
        )

        if learned:

            add_to_memory(
                from_number,
                "assistant",
                learned
            )

            send_text(
                from_number,
                learned
            )

            return "OK", 200

        # ----------------------------------------------------
        # FORGET MEMORY
        # ----------------------------------------------------

        if tl == "forget me":

            conversation_memory[
                from_number
            ] = []

            user_profile[
                from_number
            ] = {}

            save_memory()

            send_text(
                from_number,
                "Memory cleared."
            )

            return "OK", 200

        # ----------------------------------------------------
        # VISION COMMANDS
        # ----------------------------------------------------

        if tl in [
            ".describe",
            ".verify",
            ".solve"
        ]:

            saved_image = user_waiting_image.get(
                from_number
            )

            if not saved_image:

                send_text(
                    from_number,
                    "Send an image first."
                )

                return "OK", 200

            img_data = user_waiting_image.pop(
                from_number
            )

            image_url = img_data["url"]

            mime_type = img_data.get(
                "mime_type",
                "image/jpeg"
            )

            if tl == ".solve":

                send_text(
                    from_number,
                    "Solving..."
                )

                result = solve_image_math(
                    image_url,
                    mime_type
                )

            elif tl == ".verify":

                send_text(
                    from_number,
                    "Analyzing the image..."
                )

                result = vision_call(
                    image_url,
                    """
Analyze this image for signs that it may be
AI-generated, manipulated, edited, misleading,
or authentic-looking.

Do not claim certainty about authenticity from
visual inspection alone.

Give:
• What is visibly present
• Possible signs of editing or generation
• What cannot be determined from the image alone
""",
                    mime_type
                )

            else:

                send_text(
                    from_number,
                    "Analyzing image..."
                )

                result = vision_call(
                    image_url,
                    """
Describe this image clearly.

Identify:
• Main subjects
• Objects
• Colors
• Text that can be read
• Important visual details
• Style or setting

If text is unreadable, say so.
""",
                    mime_type
                )

            add_to_memory(
                from_number,
                "assistant",
                result
            )

            send_text(
                from_number,
                f"〔 *RESULT* 〕\n\n{result}"
            )

            return "OK", 200

        # ----------------------------------------------------
        # MEDIA COMMANDS
        # ----------------------------------------------------

        if tl.startswith(".pint1 "):

            pint1_unsplash(
                from_number,
                text[7:].strip()
            )

            return "OK", 200

        if tl.startswith(".pint2 "):

            pint2_pexels(
                from_number,
                text[7:].strip()
            )

            return "OK", 200

        if tl.startswith(".pint3 "):

            pint3_anime(
                from_number,
                text[7:].strip()
            )

            return "OK", 200

        if tl.startswith(".pint4 "):

            pint4_comics(
                from_number,
                text[7:].strip()
            )

            return "OK", 200

        if tl.startswith(".pint5 "):

            pint5_education(
                from_number,
                text[7:].strip()
            )

            return "OK", 200

        # ----------------------------------------------------
        # STATUS / MENU
        # ----------------------------------------------------

        if tl in [
            ".status",
            ".menu"
        ]:

            send_text(
                from_number,
                get_menu()
            )

            return "OK", 200

        # ----------------------------------------------------
        # PLAY
        # ----------------------------------------------------

        if tl.startswith(".play"):

            query = text[5:].strip()

            if not query:

                send_text(
                    from_number,
                    "Usage: `.play <song name>`"
                )

            else:

                result = get_youtube_link(
                    query
                )

                send_text(
                    from_number,
                    result
                )

            return "OK", 200

        # ----------------------------------------------------
        # IMAGE GENERATION
        # ----------------------------------------------------

        if (
            tl.startswith("imagine")
            or tl.startswith("create")
        ):

            parts = text.split(
                " ",
                1
            )

            if (
                len(parts) < 2
                or not parts[1].strip()
            ):

                send_text(
                    from_number,
                    "Usage:\n"
                    "`imagine <prompt>`\n\n"
                    "Example:\n"
                    "`imagine cyberpunk city at night`"
                )

            else:

                imagine_generate(
                    from_number,
                    parts[1].strip()
                )

            return "OK", 200

        # ----------------------------------------------------
        # EXPLAIN
        # ----------------------------------------------------

        if tl.startswith("explain"):

            parts = text.split(
                " ",
                2
            )

            if len(parts) == 1:

                result = (
                    "Usage: `explain <topic>`"
                )

            elif len(parts) == 2:

                result = ai_explain(
                    parts[1],
                    "all",
                    from_number
                )

            else:

                result = ai_explain(
                    parts[1],
                    parts[2],
                    from_number
                )

            add_to_memory(
                from_number,
                "assistant",
                result
            )

            send_text(
                from_number,
                result
            )

            return "OK", 200

        # ----------------------------------------------------
        # NORMAL AI CHAT
        # ----------------------------------------------------

        if not text:

            send_text(
                from_number,
                "Send me a message."
            )

            return "OK", 200

        result = ai_call(
            text,
            from_number
        )

        add_to_memory(
            from_number,
            "assistant",
            result
        )

        send_text(
            from_number,
            result
        )

    except Exception as e:

        print(
            f"[WEBHOOK ERROR] {repr(e)}"
        )

        # Return 200 to prevent Meta repeatedly retrying
        # malformed/non-critical events.
        return "OK", 200

    return "OK", 200


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/")
def home():

    return (
        f"ARIA {VERSION} Running"
    )


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "5000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )



















                             
