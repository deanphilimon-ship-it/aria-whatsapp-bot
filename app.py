from flask import Flask, request
import requests
import os
import base64
import json
import re
import hashlib
from datetime import datetime
import pytz
import time
from collections import defaultdict
from groq import Groq


# ============================================================
# ARIA - Advanced Responsive Intelligent Assistant
# VERSION 14.1.1
# ============================================================

app = Flask(__name__)

VERSION = "v14.2.0"
start_time = time.time()

GRAPH_API_VERSION = os.getenv(
    "GRAPH_API_VERSION",
    "v26.0"
)

# ============================================================
# GLOBAL STATE
# ============================================================

last_explain_topic = {}
last_explain_fields = {}
user_waiting_image = {}
IMAGE_WAIT_TIMEOUT = 30 * 60

conversation_memory = {}
user_profile = {}

MAX_HISTORY = 15
MEMORY_FILE = "aria_memory.json"

# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

UNSPLASH_KEY = os.getenv("UNSPLASH_KEY")
PIXABAY_KEY = os.getenv("PIXABAY_KEY")
COMICVINE_KEY = os.getenv("COMICVINE_KEY")

# ============================================================
# GROQ MODELS
# ============================================================

CHAT_MODEL = "openai/gpt-oss-120b"
VISION_MODEL = os.getenv("VISION_MODEL", "qwen/qwen3.8-27b")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "low")

# ============================================================
# GROQ CLIENT
# ============================================================

client = (
    Groq(api_key=GROQ_API_KEY)
    if GROQ_API_KEY
    else None
)

# ============================================================
# ACCESS CONTROL
# ============================================================

OWNER_NUMBER = os.getenv("OWNER_NUMBER", "2348026177804").strip()

ADMIN_NUMBERS = {
    n.strip()
    for n in os.getenv("ADMIN_NUMBERS", "").split(",")
    if n.strip()
}

ALLOWED_USERS = [
    n.strip()
    for n in os.getenv("ALLOWED_USERS", "2348XXXXXXXX,2349XXXXXXX").split(",")
    if n.strip()
]

# Prefer a secret Render environment variable. The weekly fallback is retained
# for backwards compatibility so an existing deployment does not suddenly lock
# everyone out before ARIA_PASSWORD is configured.
ARIA_PASSWORD = os.getenv("ARIA_PASSWORD", "").strip()
PASSWORD = ARIA_PASSWORD or (
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

        with open(
            MEMORY_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        conversation_memory = data.get(
            "convo",
            {}
        )

        user_profile = data.get(
            "profile",
            {}
        )

        BANNED_USERS = set(
            data.get(
                "banned",
                []
            )
        )

    except Exception as e:

        print(
            "[MEMORY LOAD ERROR]",
            repr(e)
        )


def save_memory():

    try:

        with open(
            MEMORY_FILE,
            "w",
            encoding="utf-8"
        ) as f:

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

        print(
            "[MEMORY SAVE ERROR]",
            repr(e)
        )


load_memory()

# ============================================================
# RATE LIMITER
# ============================================================

def check_rate_limit(
    number,
    api_name
):

    now = time.time()

    key = f"{number}_{api_name}"

    api_requests[key] = [
        t
        for t in api_requests[key]
        if now - t < 3600
    ]

    if len(
        api_requests[key]
    ) >= LIMITS.get(
        api_name,
        100
    ):

        return False

    api_requests[key].append(now)

    return True

# ============================================================
# AUTHENTICATION
# ============================================================

def check_auth(
    from_number,
    text
):

    # The owner is immutable: bans and ordinary authentication state can
    # never remove the owner's access.
    if from_number == OWNER_NUMBER:

        BANNED_USERS.discard(from_number)
        authenticated_users.add(from_number)

        return True, ""

    if from_number in BANNED_USERS:

        return (
            False,
            "You are banned from using ARIA."
        )

    if from_number in ADMIN_NUMBERS or from_number in ALLOWED_USERS:

        authenticated_users.add(from_number)

        return True, ""

    if from_number in authenticated_users:

        return True, ""

    if (
        text.strip().upper()
        == PASSWORD.upper()
    ):

        authenticated_users.add(
            from_number
        )

        auth_tries[from_number] = 0

        return (
            True,
            "Access Granted.\n\n"
            "Welcome to ARIA."
        )

    auth_tries[from_number] = (
        auth_tries.get(
            from_number,
            0
        ) + 1
    )

    if (
        auth_tries[from_number]
        >= MAX_TRIES
    ):

        BANNED_USERS.add(
            from_number
        )

        save_memory()

        return (
            False,
            "Locked. Too many incorrect attempts."
        )

    remaining = (
        MAX_TRIES
        - auth_tries[from_number]
    )

    return (
        False,
        "Private Bot\n\n"
        "Send password to unlock.\n"
        f"Attempts left: {remaining}"
    )

# ============================================================
# USER LIST
# ============================================================

def get_users_list():

    users = set()

    users.update(
        authenticated_users
    )

    users.update(
        conversation_memory.keys()
    )

    users.update(
        user_profile.keys()
    )

    users.update(
        ALLOWED_USERS
    )

    users.discard(
        OWNER_NUMBER
    )

    if not users:

        return (
            "〔 *ARIA USERS* 〕\n\n"
            "No users recorded."
        )

    lines = [
        "〔 *ARIA USERS* 〕",
        "",
        f"*Authenticated:* "
        f"{len(authenticated_users)}",
        f"*Recorded:* {len(users)}",
        f"*Banned:* {len(BANNED_USERS)}",
        ""
    ]

    for number in sorted(users):

        status = (
            "BANNED"
            if number in BANNED_USERS
            else "ACTIVE"
        )

        lines.append(
            f"• {number} — {status}"
        )

    return "\n".join(lines)

# ============================================================
# WHATSAPP FORMATTING
# ============================================================

def clean_ui(text):

    if not text:
        return ""

    text = str(text)

    lines = text.splitlines()

    cleaned_lines = []

    for line in lines:

        stripped = line.strip()

        if (
            stripped.startswith("|")
            and stripped.endswith("|")
        ):

            continue

        if re.match(
            r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?$",
            stripped
        ):

            continue

        cleaned_lines.append(line)

    text = "\n".join(
        cleaned_lines
    )

    text = re.sub(
        r"^#{1,6}\s*(.+)$",
        r"〔 *\1* 〕",
        text,
        flags=re.MULTILINE
    )

    text = text.replace(
        "**",
        "*"
    )

    text = re.sub(
        r"\n{4,}",
        "\n\n",
        text
    )

    return text.strip()

# ============================================================
# GRAPH API URL
# ============================================================

def graph_url(
    endpoint
):

    return (
        f"https://graph.facebook.com/"
        f"{GRAPH_API_VERSION}/"
        f"{endpoint}"
    )

# ============================================================
# SEND WHATSAPP TEXT
# ============================================================

def _split_whatsapp_text(text, max_len=3500):
    text = (text or "").strip()
    if len(text) <= max_len:
        return [text] if text else []
    parts = []
    remaining = text
    while len(remaining) > max_len:
        window = remaining[:max_len]
        cut = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(". "), window.rfind("! "), window.rfind("? "))
        if cut < max_len * 0.55:
            cut = max_len
        parts.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        parts.append(remaining)
    return [x for x in parts if x]


def send_text(to, text):
    text = clean_ui(text) or "I couldn't generate a response."
    if not WHATSAPP_TOKEN:
        print("[WHATSAPP ERROR] WHATSAPP_TOKEN is missing.")
        return False
    if not PHONE_NUMBER_ID:
        print("[WHATSAPP ERROR] PHONE_NUMBER_ID is missing.")
        return False
    url = graph_url(f"{PHONE_NUMBER_ID}/messages")
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    chunks = _split_whatsapp_text(text)
    success = True
    for i, chunk in enumerate(chunks):
        header = f"〔 *ARIA · {i + 1}/{len(chunks)}* 〕\n\n" if len(chunks) > 1 else ""
        payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"preview_url": False, "body": header + chunk}}
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=20)
            if not response.ok:
                success = False
                print("[WHATSAPP SEND ERROR]", response.status_code, response.text[:1000])
        except Exception as e:
            success = False
            print("[WHATSAPP SEND EXCEPTION]", repr(e))
        time.sleep(0.3)
    return success

# ============================================================
# SEND IMAGE
# ============================================================

def send_image_url(
    to,
    image_url,
    caption=""
):

    if not image_url:

        send_text(
            to,
            "I couldn't find an image to send."
        )

        return False

    if not WHATSAPP_TOKEN:

        print(
            "[WHATSAPP IMAGE ERROR] "
            "WHATSAPP_TOKEN missing."
        )

        return False

    if not PHONE_NUMBER_ID:

        print(
            "[WHATSAPP IMAGE ERROR] "
            "PHONE_NUMBER_ID missing."
        )

        return False

    url = graph_url(
        f"{PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization":
        f"Bearer {WHATSAPP_TOKEN}",

        "Content-Type":
        "application/json"
    }

    payload = {
        "messaging_product":
        "whatsapp",

        "to":
        to,

        "type":
        "image",

        "image": {
            "link":
            image_url,

            "caption":
            caption[:1024]
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
                response.text[:2000]
            )

            send_text(
                to,
                "WhatsApp couldn't send that image."
            )

            return False

        return True

    except Exception as e:

        print(
            "[WHATSAPP IMAGE EXCEPTION]",
            repr(e)
        )

        send_text(
            to,
            "The image could not be delivered."
        )

        return False

# ============================================================
# PINT1
# ============================================================

def pint1_unsplash(
    sender,
    query
):

    if not UNSPLASH_KEY:

        send_text(
            sender,
            "Unsplash is not configured."
        )

        return

    if not check_rate_limit(
        sender,
        "pint1"
    ):

        send_text(
            sender,
            "Too many Unsplash searches. "
            "Try again later."
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
            "[UNSPLASH ERROR]",
            repr(e)
        )

        send_text(
            sender,
            f"No results on Unsplash for: {query}"
        )

# ============================================================
# PINT2
# ============================================================

def pint2_pexels(
    sender,
    query
):

    if not check_rate_limit(
        sender,
        "pint2"
    ):

        send_text(
            sender,
            "Too many wallpaper searches. "
            "Try again later."
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

            photo_url = photo.get(
                "path"
            )

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

        raise Exception(
            "No wallpapers found"
        )

    except Exception as e:

        print(
            "[WALLHAVEN ERROR]",
            repr(e)
        )

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
                "[UNSPLASH FALLBACK ERROR]",
                repr(e)
            )

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
# PINT3
# ============================================================

def pint3_anime(
    sender,
    query
):

    q = query.lower().replace(
        " ",
        "_"
    )

    nsfw_tags = [
        "naked",
        "nude",
        "boobs",
        "pussy",
        "sex",
        "nsfw"
    ]

    if (
        any(
            tag in q
            for tag in nsfw_tags
        )
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
        "User-Agent":
        "ARIA-Bot/1.0"
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
            post.get(
                "large_file_url"
            )
            or post.get(
                "file_url"
            )
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
            "[DANBOORU ERROR]",
            repr(e)
        )

        send_text(
            sender,
            "Danbooru failed. "
            "Try a different character."
        )

# ============================================================
# PINT4
# ============================================================

def pint4_comics(
    sender,
    query
):

    if not COMICVINE_KEY:

        send_text(
            sender,
            "ComicVine is not configured. "
            "Add COMICVINE_KEY to Render."
        )

        return

    if not check_rate_limit(
        sender,
        "pint4"
    ):

        send_text(
            sender,
            "Too many comic searches. "
            "Try again later."
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
        "api_key":
        COMICVINE_KEY,

        "format":
        "json",

        "query":
        query,

        "resources":
        "character,issue,volume",

        "limit":
        1
    }

    headers = {
        "User-Agent":
        "ARIA-Bot/1.0"
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

        if res.get(
            "status_code"
        ) != 1:

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
            result.get(
                "name"
            )
            or result.get(
                "volume",
                {}
            ).get(
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
            "[COMICVINE ERROR]",
            repr(e)
        )

        send_text(
            sender,
            "ComicVine failed. "
            "Try again in a few seconds."
        )

# ============================================================
# PINT5
# ============================================================

def pint5_education(
    sender,
    query
):

    if not check_rate_limit(
        sender,
        "pint5"
    ):

        send_text(
            sender,
            "Too many education searches. "
            "Try again later."
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
                "[PINT5 UNSPLASH ERROR]",
                repr(e)
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
        caption=(
            f"Pint5 AI: {query}\n"
            "Educational Diagram"
        )
    )

# ============================================================
# IMAGE GENERATION
# ============================================================

def imagine_generate(
    sender,
    prompt
):

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

    seed = (
        int(
            hashlib.sha256(
                prompt.encode("utf-8")
            ).hexdigest()[:8],
            16
        )
        % 100000
    )

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
# SYSTEM PROMPT
# ============================================================

DEFAULT_SYSTEM_PROMPT = """
You are ARIA, an advanced WhatsApp AI assistant.

IDENTITY
- Your name is ARIA.
- ARIA stands for Advanced Response Intelligence Assistant.
- If asked what ARIA means, use that exact expansion for this bot.
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
- For simple questions, give simple answers.
- For complex questions, explain important reasoning clearly.
- Maximum normal response length: about 300 words unless the user asks for detail.

ACCURACY
- If uncertain, say so.
- Never invent sources, facts, API results, files, events, or personal memories.
- Distinguish facts from assumptions.
- When the user asks for current or recent information and no live tool/data is available, state that limitation instead of pretending the information is current.
- Never claim a specific training-data cutoff date unless the provider explicitly supplies that date.
- Never say that your knowledge "ends in June 2024" or invent another cutoff date.
- Do not turn uncertainty about current information into a claim about your training cutoff.
- If asked "what is your knowledge cutoff?", say that you do not have a reliable provider-supplied cutoff date available in this chat and that current information should be verified with live sources when available.

MEMORY
- Use supplied conversation memory when relevant.
- Do not claim to remember information that is not present in supplied memory.

PROBLEM SOLVING
- Solve the actual problem instead of giving generic advice.
- For calculations, show enough working to make the answer understandable.
- For technical problems, identify the likely cause before suggesting a fix.

SAFETY
- Do not generate, encourage, or provide explicit sexual content.
- Do not eroticize or provide sexualized descriptions of explicit images.
- Educational, medical, anatomical, safety, and non-explicit discussions are allowed when handled clinically.

WHATSAPP
- Keep formatting clean and readable.
- Use • for bullets when appropriate.
- Avoid excessive emojis.
"""

# ============================================================
# MEMORY CONTEXT
# ============================================================

def build_memory_context(
    from_number
):

    context = ""

    if from_number in user_profile:

        name = (
            user_profile[
                from_number
            ].get(
                "name",
                "User"
            )
        )

        context += (
            f"You are talking to {name}.\n"
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
                f"{content[:500]}\n"
            )

    return context

# ============================================================
# MEMORY WRITE
# ============================================================

def add_to_memory(
    from_number,
    role,
    content
):

    if from_number not in conversation_memory:

        conversation_memory[
            from_number
        ] = []

    conversation_memory[
        from_number
    ].append(
        {
            "role":
            role,

            "content":
            content
        }
    )

    conversation_memory[
        from_number
    ] = conversation_memory[
        from_number
    ][-MAX_HISTORY:]

    save_memory()

# ============================================================
# AI PROVIDER LAYER
# ============================================================

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
)


def _extract_groq_text(completion):

    if not completion or not getattr(completion, "choices", None):
        return ""

    message = getattr(
        completion.choices[0],
        "message",
        None
    )

    if not message:
        return ""

    content = getattr(message, "content", None)

    if isinstance(content, str):
        return content.strip()

    if content is None:
        return ""

    return str(content).strip()


def _extract_gemini_text(data):

    candidates = data.get("candidates") or []

    if not candidates:
        return ""

    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []

    texts = []

    for part in parts:
        text = part.get("text")
        if text:
            texts.append(str(text))

    return "\n".join(texts).strip()


def gemini_call(
    prompt,
    system=DEFAULT_SYSTEM_PROMPT,
    image_data=None,
    mime_type=None,
    timeout=45
):

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing")

    parts = []

    if image_data:
        if not mime_type or not mime_type.startswith("image/"):
            raise ValueError("Gemini vision requires an image MIME type")

        parts.append(
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": image_data
                }
            }
        )

    parts.append(
        {
            "text": prompt
        }
    )

    payload = {
        "system_instruction": {
            "parts": [
                {
                    "text": system
                }
            ]
        },
        "contents": [
            {
                "role": "user",
                "parts": parts
            }
        ],
        "generationConfig": {
            "maxOutputTokens": 1024,
            "thinkingConfig": {
                "thinkingLevel": GEMINI_THINKING_LEVEL
            }
        }
    }

    response = requests.post(
        f"{GEMINI_API_URL}{GEMINI_MODEL}:generateContent",
        params={"key": GEMINI_API_KEY},
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=timeout
    )

    if not response.ok:
        raise RuntimeError(
            f"Gemini HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )

    data = response.json()
    text = _extract_gemini_text(data)

    if not text:
        raise ValueError("Gemini returned an empty response")

    return text


def groq_chat_call(
    prompt,
    system=DEFAULT_SYSTEM_PROMPT
):

    if not client:
        raise RuntimeError("GROQ_API_KEY is missing")

    completion = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {
                "role": "system",
                "content": system
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.6,
        max_tokens=1024,
        top_p=0.95,
        stream=False
    )

    text = _extract_groq_text(completion)

    if not text:
        raise ValueError("Groq returned an empty response")

    return text


def ai_call(
    prompt,
    from_number,
    system=DEFAULT_SYSTEM_PROMPT
):

    memory_context = build_memory_context(
        from_number
    )

    full_prompt = (
        f"{memory_context}\n\n"
        f"User: {prompt}"
    )

    user_content = full_prompt[:12000]
    errors = []

    # Primary: Groq.
    if client:
        try:
            response = groq_chat_call(
                user_content,
                system=system
            )

            print(
                f"[AI SUCCESS] provider=groq model={CHAT_MODEL}"
            )

            return response

        except Exception as e:
            errors.append(
                f"Groq: {repr(e)}"
            )
            print(
                "[AI GROQ ERROR]",
                repr(e)
            )

    # Fallback: Gemini. Optional and only used if configured.
    if GEMINI_API_KEY:
        try:
            response = gemini_call(
                user_content,
                system=system
            )

            print(
                f"[AI SUCCESS] provider=gemini model={GEMINI_MODEL}"
            )

            return response

        except Exception as e:
            errors.append(
                f"Gemini: {repr(e)}"
            )
            print(
                "[AI GEMINI ERROR]",
                repr(e)
            )

    if not client and not GEMINI_API_KEY:
        return (
            "AI is not configured.\n\n"
            "Add GROQ_API_KEY or GEMINI_API_KEY to Render."
        )

    print(
        "[AI ERROR SUMMARY]",
        " | ".join(errors)
    )

    return (
        "AI request failed.\n\n"
        "Both configured AI providers failed. "
        "Use `.health` to see their status."
    )

# ============================================================
# WHATSAPP IMAGE DOWNLOAD
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
        "Authorization":
        f"Bearer {WHATSAPP_TOKEN}"
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

    detected_mime = (
        mime_type
        or response.headers.get(
            "Content-Type",
            "image/jpeg"
        )
    )

    detected_mime = (
        detected_mime
        .split(";")[0]
        .strip()
        .lower()
    )

    if not detected_mime.startswith("image/"):
        raise ValueError(
            "Downloaded media is not an image: "
            f"{detected_mime}"
        )

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


def groq_vision_call(
    base64_image,
    detected_mime,
    prompt
):

    if not client:
        raise RuntimeError("GROQ_API_KEY is missing")

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
        max_tokens=1024,
        top_p=0.9,
        stream=False
    )

    text = _extract_groq_text(completion)

    if not text:
        raise ValueError(
            "Groq vision returned an empty response"
        )

    return text


def vision_call(
    image_url,
    prompt,
    mime_type=None
):

    try:
        (
            base64_image,
            detected_mime
        ) = download_whatsapp_image(
            image_url,
            mime_type
        )
    except Exception as e:
        print(
            "[VISION DOWNLOAD ERROR]",
            repr(e)
        )
        return (
            "I couldn't retrieve that image from WhatsApp.\n\n"
            f"Reason: {str(e)[:500]}"
        )

    errors = []

    # Primary vision provider: Groq Qwen 3.8 27B.
    if client:
        try:
            result = groq_vision_call(
                base64_image,
                detected_mime,
                prompt
            )

            print(
                f"[VISION SUCCESS] provider=groq model={VISION_MODEL}"
            )

            return result.strip()

        except Exception as e:
            errors.append(
                f"Groq Vision: {repr(e)}"
            )
            print(
                "[VISION GROQ ERROR]",
                repr(e)
            )

    # Fallback vision provider: Gemini.
    if GEMINI_API_KEY:
        try:
            result = gemini_call(
                prompt + "\n\n"
                "Be accurate and concise. "
                "If something cannot be determined from the image, "
                "say that clearly instead of guessing.",
                system=DEFAULT_SYSTEM_PROMPT,
                image_data=base64_image,
                mime_type=detected_mime
            )

            print(
                f"[VISION SUCCESS] provider=gemini model={GEMINI_MODEL}"
            )

            return result.strip()

        except Exception as e:
            errors.append(
                f"Gemini Vision: {repr(e)}"
            )
            print(
                "[VISION GEMINI ERROR]",
                repr(e)
            )

    if not client and not GEMINI_API_KEY:
        return (
            "Vision is not configured.\n\n"
            "Add GROQ_API_KEY or GEMINI_API_KEY to Render."
        )

    print(
        "[VISION ERROR SUMMARY]",
        " | ".join(errors)
    )

    return (
        "I couldn't process that image.\n\n"
        "Both configured vision providers failed. "
        "Use `.health` to see their configuration/status."
    )

# ============================================================
# PROVIDER HEALTH
# ============================================================

def check_groq_chat_health():

    if not client:
        return "NOT CONFIGURED"

    try:
        completion = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": "Reply only with OK."
                }
            ],
            max_tokens=8,
            stream=False
        )

        return (
            "ONLINE"
            if _extract_groq_text(completion)
            else "EMPTY RESPONSE"
        )

    except Exception as e:
        print(
            "[HEALTH GROQ ERROR]",
            repr(e)
        )
        return "FAILED"


def check_gemini_health():

    if not GEMINI_API_KEY:
        return "NOT CONFIGURED"

    try:
        result = gemini_call(
            "Reply only with OK.",
            system="You are a health check."
        )

        return "ONLINE" if result else "EMPTY RESPONSE"

    except Exception as e:
        print(
            "[HEALTH GEMINI ERROR]",
            repr(e)
        )
        return "FAILED"


def check_groq_models():

    if not client:
        return "NOT CONFIGURED"

    try:
        models = client.models.list()
        ids = {
            getattr(model, "id", "")
            for model in models.data
        }

        chat_ok = CHAT_MODEL in ids
        vision_ok = VISION_MODEL in ids

        if chat_ok and vision_ok:
            return "AVAILABLE"

        missing = []
        if not chat_ok:
            missing.append("chat")
        if not vision_ok:
            missing.append("vision")

        return "MISSING " + ", ".join(missing)

    except Exception as e:
        print(
            "[HEALTH MODEL LIST ERROR]",
            repr(e)
        )
        return "UNKNOWN"

# ============================================================
# SOLVE IMAGE
# ============================================================

def solve_image_problem(image_url, mime_type=None, mode="universal"):
    if mode == "math":
        prompt = """
You are ARIA's dedicated mathematics solver.
Read the image carefully and solve the visible mathematical problem.
Use: 〔 SOLUTION 〕, Given/question, Method or formula, Key working steps, Final answer.
Keep working clear but concise. Preserve readable numbers, symbols and units.
If something is unreadable, say exactly what needs to be clearer instead of guessing.
"""
    else:
        prompt = """
You are ARIA's universal image-problem solver. If the image contains explicit sexual content, do not describe or sexualize it; briefly state that explicit content cannot be processed. Otherwise first identify the problem type:
mathematics, physics, chemistry, biology, English/language, multiple choice, logic,
diagram, or another academic/practical task. Then solve the actual problem shown.

Use:
〔 SOLUTION 〕
• Problem type
• Question (short transcription)
• Method / formula / rule
• Important working

〔 ANSWER 〕
Final answer.

For multiple choice, identify the option and briefly explain why. Do not invent
text that cannot be read. If the image is unclear, say exactly what is unclear.
"""
    return vision_call(image_url, prompt, mime_type)


def solve_image_math(image_url, mime_type=None):
    return solve_image_problem(image_url, mime_type, mode="math")

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

        name = (
            match.group(1)
            .strip()
        )

        if not name:
            return None

        if from_number not in user_profile:

            user_profile[
                from_number
            ] = {}

        user_profile[
            from_number
        ]["name"] = name

        save_memory()

        return (
            f"Got it. I'll remember "
            f"your name is *{name}*."
        )

    return None

# ============================================================
# EDUCATION EXPLANATION
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

        idx = (
            int(field_num)
            - 1
        )

    except ValueError:

        return (
            "Usage: `explain psychology 2`"
        )

    if (
        from_number
        not in last_explain_fields
    ):

        return (
            "Ask `explain psychology` first "
            "to see the fields."
        )

    if (
        idx < 0
        or idx >= len(
            last_explain_fields[
                from_number
            ]
        )
    ):

        return (
            "Choose a field from 1 to 6."
        )

    field = (
        last_explain_fields[
            from_number
        ][idx]
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
- Mention important exceptions.
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

def get_youtube_link(
    query
):

    youtube_url = (
        "https://www.youtube.com/results?search_query="
        + requests.utils.quote(query)
    )

    return (
        f"*{query.title()}*\n\n"
        f"▶️ Tap to search: {youtube_url}"
    )

# ============================================================
# RUNTIME
# ============================================================

def get_runtime():

    seconds = int(
        time.time()
        - start_time
    )

    h = seconds // 3600

    m = (
        seconds
        % 3600
    ) // 60

    s = seconds % 60

    return (
        f"{h}h {m}m {s}s"
    )

# ============================================================
# CONTENT SAFETY
# ============================================================

EXPLICIT_PATTERNS = [
    r"\bporn(?:ography)?\b",
    r"\bpornographic\b",
    r"\bnsfw\b",
    r"\bsex video\b",
    r"\bsex tape\b",
    r"\bexplicit sex\b",
    r"\bsexual intercourse\b",
    r"\bgenital(?:s)?\b.*\bphoto(?:s)?\b",
    r"\bnude(?:d)?\s+(?:photo|picture|image|pic)s?\b",
    r"\bnaked\s+(?:photo|picture|image|pic)s?\b",
    r"\b(?:boobs?|breasts?)\s+(?:photo|picture|image|pic)s?\b",
    r"\b(?:dick|penis|cock|pussy|vagina)\s+(?:photo|picture|image|pic)s?\b",
]


def is_explicit_request(text):
    if not text:
        return False

    normalized = re.sub(r"\s+", " ", str(text).lower()).strip()

    # Educational/medical questions containing a sensitive word alone are
    # not treated as explicit requests. The patterns above require explicit
    # sexual-media or sexual-act context.
    return any(
        re.search(pattern, normalized, flags=re.IGNORECASE)
        for pattern in EXPLICIT_PATTERNS
    )


def safety_block_message():
    return (
        "I can help with educational, medical, safety, or non-explicit topics, "
        "but I can't generate or provide explicit sexual content."
    )


def get_about():
    return f"""
〔 *ABOUT ARIA* 〕

*ARIA* stands for *Advanced Response Intelligence Assistant*.

ARIA is a WhatsApp AI assistant designed to handle conversation, vision,
problem solving, study help and media commands.

*Version:* {VERSION}
*Owner protection:* ENABLED
*Content safety:* ENABLED
"""

# ============================================================
# MENU / STATUS
# ============================================================

def get_menu():
    return f"""
〔 *ARIA {VERSION}* 〕

*AI*
• `.ask <question>`
• `.explain <topic>`
• `.summarize <text>`
• `.translate <language> <text>`
• `.define <word>`

*VISION*
• `.describe` / `.describe detailed`
• `.read`
• `.solve`
• `.math`
• `.verify`

*STUDY*
• `.study <topic>`
• `.quiz <topic>`

*MEDIA*
• `.pint`
• `.photo <query>`
• `.wallpaper <query>`
• `.anime <character>`
• `.comic <query>`
• `.edu <subject>`
• `imagine <prompt>`
• `.play <song name>`

*SYSTEM*
• `.about`
• `.health`
• `.status`
• `.menu`
• `.help <command>`

*OWNER*
• `.users`
• `.ban <number>`
• `.unban <number>`

Legacy `.pint1`–`.pint5` still work.
"""


def get_status():

    local_time = datetime.now(
        pytz.timezone("Africa/Lagos")
    ).strftime("%I:%M %p")

    whatsapp = (
        "CONFIGURED"
        if WHATSAPP_TOKEN and PHONE_NUMBER_ID
        else "NOT CONFIGURED"
    )

    groq = (
        "CONFIGURED"
        if client
        else "NOT CONFIGURED"
    )

    gemini = (
        "CONFIGURED"
        if GEMINI_API_KEY
        else "NOT CONFIGURED"
    )

    pending_images = len(user_waiting_image)

    return f"""
〔 *ARIA STATUS* 〕

*Version:* {VERSION}
*Runtime:* {get_runtime()}
*Lagos Time:* {local_time}
*Graph API:* {GRAPH_API_VERSION}

〔 *PROVIDERS* 〕
*Groq:* {groq}
*Groq Chat:* {CHAT_MODEL}
*Groq Vision:* {VISION_MODEL}
*Gemini:* {gemini}
*Gemini Model:* {GEMINI_MODEL}
*Gemini Thinking:* {GEMINI_THINKING_LEVEL}

〔 *SYSTEMS* 〕
*WhatsApp:* {whatsapp}
*Memory:* OK
*Pending Images:* {pending_images}
*Image Fallback:* {"ENABLED" if GEMINI_API_KEY else "DISABLED"}
"""

# ============================================================
# WEBHOOK
# ============================================================

@app.route(
    "/webhook",
    methods=[
        "GET",
        "POST"
    ]
)
def webhook():

    global last_explain_topic
    global user_waiting_image

    # ========================================================
    # META WEBHOOK VERIFICATION
    # ========================================================

    if request.method == "GET":

        challenge = request.args.get(
            "hub.challenge"
        )

        verify_token = request.args.get(
            "hub.verify_token"
        )

        if VERIFY_TOKEN:

            if verify_token != VERIFY_TOKEN:

                return (
                    "Forbidden",
                    403
                )

        return (
            challenge
            or "OK",
            200
        )

    # ========================================================
    # PARSE WEBHOOK
    # ========================================================

    try:

        data = request.get_json(
            silent=True
        )

        if not data:

            return (
                "OK",
                200
            )

        entries = data.get(
            "entry",
            []
        )

        if not entries:

            return (
                "OK",
                200
            )

        # Meta can send multiple entries/changes in one webhook.
        # Find the first actual inbound message and ignore delivery/status events.
        msg = None

        for entry in entries:

            for change in entry.get("changes", []):

                value = change.get("value") or {}

                for candidate in value.get("messages", []):

                    if candidate.get("from"):
                        msg = candidate
                        break

                if msg:
                    break

            if msg:
                break

        if not msg:

            return (
                "OK",
                200
            )

        from_number = msg.get(
            "from"
        )

        if not from_number:

            return (
                "OK",
                200
            )

        text = (
            msg.get(
                "text",
                {}
            )
            .get(
                "body",
                ""
            )
            .strip()
        )

        tl = text.lower()

        # ====================================================
        # AUTH
        # ====================================================

        is_auth, auth_msg = check_auth(
            from_number,
            text
        )

        if not is_auth:

            send_text(
                from_number,
                auth_msg
            )

            return (
                "OK",
                200
            )

        if auth_msg:

            send_text(
                from_number,
                auth_msg
            )

        # ====================================================
        # GLOBAL CONTENT SAFETY
        # ====================================================

        if is_explicit_request(text):
            send_text(
                from_number,
                safety_block_message()
            )
            return (
                "OK",
                200
            )

        # ====================================================
        # OWNER BAN
        # ====================================================

        if tl.startswith(
            ".ban "
        ):

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

                    return (
                        "OK",
                        200
                    )

                target = (
                    parts[1]
                    .strip()
                )

                if target == OWNER_NUMBER:
                    send_text(
                        from_number,
                        "Owner protection: that number cannot be banned."
                    )
                    return (
                        "OK",
                        200
                    )

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

            return (
                "OK",
                200
            )

        # ====================================================
        # OWNER UNBAN
        # ====================================================

        if tl.startswith(
            ".unban "
        ):

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

                    return (
                        "OK",
                        200
                    )

                target = (
                    parts[1]
                    .strip()
                )

                if target == OWNER_NUMBER:
                    send_text(
                        from_number,
                        "Owner is permanently protected and does not require unbanning."
                    )
                    return (
                        "OK",
                        200
                    )

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

            return (
                "OK",
                200
            )

        # ====================================================
        # OWNER USERS
        # ====================================================

        if tl == ".users":

            if from_number == OWNER_NUMBER:

                send_text(
                    from_number,
                    get_users_list()
                )

            else:

                send_text(
                    from_number,
                    "Owner only command."
                )

            return (
                "OK",
                200
            )

        # ====================================================
        # IMAGE MESSAGE
        # ====================================================

        if msg.get(
            "type"
        ) == "image":

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

                return (
                    "OK",
                    200
                )

            try:

                media_response = requests.get(
                    graph_url(
                        image_id
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

                image_url = (
                    media_info.get(
                        "url"
                    )
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
                    "mime_type": media_mime_type,
                    "saved_at": time.time()
                }

                send_text(
                    from_number,
                    "Image received.\n\n"
                    "Send `.describe`, `.verify` "
                    "or `.solve`."
                )

            except Exception as e:

                print(
                    "[WHATSAPP MEDIA ERROR]",
                    repr(e)
                )

                send_text(
                    from_number,
                    "I couldn't retrieve that image "
                    "from WhatsApp. Try sending it again."
                )

            return (
                "OK",
                200
            )

        # ====================================================
        # MEMORY
        # ====================================================

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

            return (
                "OK",
                200
            )

        # ====================================================
        # FORGET
        # ====================================================

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

            return (
                "OK",
                200
            )

        # ====================================================
        # HEALTH
        # ====================================================

        if tl == ".health":

            groq_chat_status = check_groq_chat_health()
            gemini_status = check_gemini_health()
            groq_models_status = check_groq_models()

            whatsapp_status = (
                "CONFIGURED"
                if WHATSAPP_TOKEN and PHONE_NUMBER_ID
                else "NOT CONFIGURED"
            )

            memory_status = (
                "OK"
                if conversation_memory is not None
                and user_profile is not None
                and BANNED_USERS is not None
                else "ERROR"
            )

            groq_vision_status = (
                "READY"
                if client and groq_models_status in {
                    "AVAILABLE",
                    "UNKNOWN"
                }
                else "NOT CONFIGURED"
                if not client
                else "CHECK FAILED"
            )

            gemini_vision_status = (
                "READY"
                if GEMINI_API_KEY
                else "NOT CONFIGURED"
            )

            health = (
                f"〔 *ARIA HEALTH* 〕\n\n"
                f"*Version:* {VERSION}\n"
                f"*Runtime:* {get_runtime()}\n"
                f"*Graph API:* {GRAPH_API_VERSION}\n\n"
                f"〔 *CORE* 〕\n"
                f"*WhatsApp:* {whatsapp_status}\n"
                f"*Memory:* {memory_status}\n\n"
                f"〔 *GROQ* 〕\n"
                f"*Chat:* {groq_chat_status}\n"
                f"*Models:* {groq_models_status}\n"
                f"*Vision:* {groq_vision_status}\n"
                f"*Chat Model:* {CHAT_MODEL}\n"
                f"*Vision Model:* {VISION_MODEL}\n\n"
                f"〔 *GEMINI FALLBACK* 〕\n"
                f"*API:* {gemini_status}\n"
                f"*Vision:* {gemini_vision_status}\n"
                f"*Model:* {GEMINI_MODEL}\n\n"
                f"〔 *SECURITY* 〕\n"
                f"*Owner:* PROTECTED\n"
                f"*Password:* {'ENVIRONMENT' if ARIA_PASSWORD else 'LEGACY FALLBACK'}\n"
                f"*Content Safety:* ENABLED\n"
            )

            send_text(
                from_number,
                health
            )

            return (
                "OK",
                200
            )

        # ====================================================
        # VISION COMMANDS
        # ====================================================

        vision_commands = {".describe", ".describe detailed", ".verify", ".solve", ".math", ".read"}
        if tl in vision_commands:
            saved_image = user_waiting_image.get(from_number)
            if saved_image:
                saved_at = saved_image.get("saved_at", 0)
                if saved_at and time.time() - saved_at > IMAGE_WAIT_TIMEOUT:
                    user_waiting_image.pop(from_number, None)
                    saved_image = None
            if not saved_image:
                send_text(from_number, "No recent image is waiting. Send an image first.")
                return "OK", 200
            img_data = user_waiting_image.pop(from_number)
            image_url = img_data["url"]
            mime_type = img_data.get("mime_type", "image/jpeg")
            if tl == ".solve":
                send_text(from_number, "Reading the problem and solving it...")
                result = solve_image_problem(image_url, mime_type, "universal")
            elif tl == ".math":
                send_text(from_number, "Reading the mathematics...")
                result = solve_image_problem(image_url, mime_type, "math")
            elif tl == ".read":
                send_text(from_number, "Reading the text...")
                result = vision_call(image_url, """Extract the readable text from this image. Return only text you can actually read, preserving useful line breaks. If some text is unclear, mark it [unclear] instead of inventing it.""", mime_type)
            elif tl == ".verify":
                send_text(from_number, "Analyzing the image...")
                result = vision_call(image_url, """Analyze this image for visible indicators of AI generation, manipulation, editing, or misleading presentation. Give: 〔 IMAGE CHECK 〕, visible evidence, possible indicators, and what cannot be determined from the image alone. Do not claim certainty from visual inspection alone.""", mime_type)
            else:
                detailed = tl == ".describe detailed"
                send_text(from_number, "Analyzing image...")
                prompt = """Describe this image naturally for WhatsApp. Start with one concise sentence, then useful bullet points. Mention readable text only when actually legible. Do not guess identities or unreadable details."""
                prompt += " Include composition, setting, colors, notable objects, and readable text." if detailed else " Keep it to roughly 100-180 words."
                result = vision_call(image_url, prompt, mime_type)
            result = result or "I couldn't process that image."
            add_to_memory(from_number, "assistant", result)
            send_text(from_number, result)
            return "OK", 200

        # ====================================================
        # MEDIA ALIASES
        # ====================================================
        media_aliases = [(".photo", pint1_unsplash), (".wallpaper", pint2_pexels), (".anime", pint3_anime), (".comic", pint4_comics), (".edu", pint5_education)]
        for command, handler in media_aliases:
            if tl.startswith(command + " "):
                query = text[len(command):].strip()
                if not query:
                    send_text(from_number, f"Usage: `{command} <query>`")
                else:
                    handler(from_number, query)
                return "OK", 200
        if tl == ".pint":
            send_text(from_number, "〔 PINT 〕\n\nChoose:\n• `.photo <query>`\n• `.wallpaper <query>`\n• `.anime <character>`\n• `.comic <query>`\n• `.edu <subject>`")
            return "OK", 200

        # ====================================================
        # PINT COMMANDS
        # ====================================================

        if tl.startswith(
            ".pint1 "
        ):

            pint1_unsplash(
                from_number,
                text[7:].strip()
            )

            return (
                "OK",
                200
            )

        if tl.startswith(
            ".pint2 "
        ):

            pint2_pexels(
                from_number,
                text[7:].strip()
            )

            return (
                "OK",
                200
            )

        if tl.startswith(
            ".pint3 "
        ):

            pint3_anime(
                from_number,
                text[7:].strip()
            )

            return (
                "OK",
                200
            )

        if tl.startswith(
            ".pint4 "
        ):

            pint4_comics(
                from_number,
                text[7:].strip()
            )

            return (
                "OK",
                200
            )

        if tl.startswith(
            ".pint5 "
        ):

            pint5_education(
                from_number,
                text[7:].strip()
            )

            return (
                "OK",
                200
            )

        # ====================================================
        # STATUS / MENU
        # ====================================================

        if tl == ".menu":

            send_text(
                from_number,
                get_menu()
            )

            return (
                "OK",
                200
            )

        if tl == ".about":
            send_text(
                from_number,
                get_about()
            )
            return (
                "OK",
                200
            )

        if tl == ".status":

            send_text(
                from_number,
                get_status()
            )

            return (
                "OK",
                200
            )

        # ====================================================
        # HELP
        # ====================================================
        if tl.startswith(".help"):
            command = text[5:].strip().lower()
            help_map = {
                ".solve": "Send an image, then `.solve`. ARIA identifies the problem type and solves it.",
                ".math": "Send an image, then `.math`. ARIA focuses on mathematics.",
                ".read": "Send an image, then `.read`. ARIA extracts readable text.",
                ".describe": "Send an image, then `.describe`. Use `.describe detailed` for more detail.",
                ".verify": "Send an image, then `.verify`. ARIA reports visible indicators without claiming forensic certainty.",
                ".pint": "Use `.photo`, `.wallpaper`, `.anime`, `.comic`, or `.edu`.",
                ".about": "Shows ARIA's identity and core protections.",
                ".status": "Shows ARIA's runtime and provider configuration.",
                ".health": "Checks the main dependencies and AI providers.",
                ".study": "`.study <topic>` creates concise study notes.",
                ".quiz": "`.quiz <topic>` creates practice questions.",
            }
            send_text(from_number, "Usage: `.help <command>`\n\n" + (help_map.get(command, "Try `.menu` to see the available commands.") if command else "Try `.help solve`, `.help pint`, or `.help status`."))
            return "OK", 200

        # ====================================================
        # PLAY
        # ====================================================

        if tl.startswith(
            ".play"
        ):

            query = (
                text[5:]
                .strip()
            )

            if not query:

                send_text(
                    from_number,
                    "Usage: `.play <song name>`"
                )

            else:

                send_text(
                    from_number,
                    get_youtube_link(
                        query
                    )
                )

            return (
                "OK",
                200
            )

        # ====================================================
        # IMAGE GENERATION
        # ====================================================

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

            return (
                "OK",
                200
            )

        # ====================================================
        # EXPLAIN
        # ====================================================

        if tl.startswith("explain") or tl.startswith(".explain"):

            command_text = text[1:] if text.startswith(".") else text
            parts = command_text.split(" ", 2)

            if len(parts) == 1:

                result = (
                    "Usage: `.explain <topic>`"
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

            return (
                "OK",
                200
            )

        # ====================================================
        # AI CONVENIENCE COMMANDS
        # ====================================================
        if tl.startswith(".ask "):
            result = ai_call(text[5:].strip(), from_number)
            add_to_memory(from_number, "assistant", result); send_text(from_number, result); return "OK", 200
        if tl == ".ask":
            send_text(from_number, "Usage: `.ask <question>`"); return "OK", 200
        if tl.startswith(".summarize "):
            result = ai_call(f"Summarize this clearly and briefly:\n\n{text[11:].strip()}", from_number)
            add_to_memory(from_number, "assistant", result); send_text(from_number, result); return "OK", 200
        if tl == ".summarize":
            send_text(from_number, "Usage: `.summarize <text>`"); return "OK", 200
        if tl.startswith(".translate "):
            parts = text.split(" ", 2)
            if len(parts) < 3: send_text(from_number, "Usage: `.translate <language> <text>`")
            else:
                result = ai_call(f"Translate into {parts[1]}. Return only the natural translation.\n\n{parts[2]}", from_number)
                add_to_memory(from_number, "assistant", result); send_text(from_number, result)
            return "OK", 200
        if tl.startswith(".define "):
            result = ai_call(f"Define '{text[8:].strip()}'. Give a concise definition and one short example.", from_number)
            add_to_memory(from_number, "assistant", result); send_text(from_number, result); return "OK", 200
        if tl.startswith(".study "):
            result = ai_call(f"Create concise study notes for '{text[7:].strip()}'. Include definition, key ideas, one example, common mistake, and 3 exam-focused points.", from_number)
            add_to_memory(from_number, "assistant", result); send_text(from_number, result); return "OK", 200
        if tl.startswith(".quiz "):
            result = ai_call(f"Create a 5-question quiz on '{text[6:].strip()}'. Do not reveal answers yet; ask the user to reply with their answers.", from_number)
            add_to_memory(from_number, "assistant", result); send_text(from_number, result); return "OK", 200

        # ====================================================
        # NORMAL AI CHAT
        # ====================================================

        if not text:

            send_text(
                from_number,
                "Send me a message."
            )

            return (
                "OK",
                200
            )

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
            "[WEBHOOK ERROR]",
            repr(e)
        )

        return (
            "OK",
            200
        )

    return (
        "OK",
        200
    )

# ============================================================
# ROOT
# ============================================================

@app.route("/")
def home():

    return (
        f"ARIA {VERSION} Running | "
        f"Graph API {GRAPH_API_VERSION} | "
        f"Chat {CHAT_MODEL} | "
        f"Vision {VISION_MODEL} | "
        f"Gemini {GEMINI_MODEL}"
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















