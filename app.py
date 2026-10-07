from flask import Flask, request
import requests
import os
import base64
import json
import re
import hashlib
import hmac
import atexit
import threading
from collections import OrderedDict
from datetime import datetime
import pytz
import time
from collections import defaultdict
from groq import Groq


# ============================================================
# ARIA - Advanced Responsive Intelligent Assistant
# VERSION 14.2.5
# ============================================================

app = Flask(__name__)

VERSION = "v14.2.5"
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
last_image_context = {}
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
# Meta App Secret (App settings > Basic). Used to verify webhook signatures.
APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "").strip()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
VOICE_MODE = os.getenv("VOICE_MODE", "text").strip().lower()
STT_MODEL = os.getenv("STT_MODEL", "whisper-large-v3-turbo")
TTS_MODEL = os.getenv("TTS_MODEL", "canopylabs/orpheus-v1-english")
TTS_VOICE = os.getenv("TTS_VOICE", "autumn")
TTS_LANGUAGE = os.getenv("TTS_LANGUAGE", "en")

UNSPLASH_KEY = os.getenv("UNSPLASH_KEY")
PIXABAY_KEY = os.getenv("PIXABAY_KEY")
COMICVINE_KEY = os.getenv("COMICVINE_KEY")
PINTEREST_ACCESS_TOKEN = (os.getenv("PINTEREST_ACCESS_TOKEN") or os.getenv("PINTEREST_API_KEY") or os.getenv("PINTEREST_TOKEN"))
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "flux").strip() or "flux"
IMAGE_WIDTH = int(os.getenv("IMAGE_WIDTH", "1024"))
IMAGE_HEIGHT = int(os.getenv("IMAGE_HEIGHT", "1024"))
IMAGE_ENHANCE = os.getenv("IMAGE_ENHANCE", "true").strip().lower() == "true"

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

OWNER_NUMBER = os.getenv("OWNER_NUMBER", "").strip()
if not OWNER_NUMBER:
    print("[WARNING] OWNER_NUMBER is not set. Owner commands are disabled.")
OWNER_NAME = "Philimon Dean"

ADMIN_NUMBERS = {
    n.strip()
    for n in os.getenv("ADMIN_NUMBERS", "").split(",")
    if n.strip()
}

ALLOWED_USERS = [
    n.strip()
    for n in os.getenv("ALLOWED_USERS", "").split(",")
    if n.strip()
]

# Password login is only enabled when ARIA_PASSWORD is set in the environment.
# There is no guessable fallback. Without it, only the owner, admins and
# ALLOWED_USERS can use ARIA.
ARIA_PASSWORD = os.getenv("ARIA_PASSWORD", "").strip()
PASSWORD = ARIA_PASSWORD or None
if not PASSWORD:
    print("[WARNING] ARIA_PASSWORD is not set. Password login is disabled.")

MAX_TRIES = 4

auth_tries = {}
voice_enabled_users = set()

authenticated_users = set()

BANNED_USERS = set()

# ============================================================
# RATE LIMITS
# ============================================================

api_requests = defaultdict(list)
_rate_lock = threading.Lock()

LIMITS = {
    "pint1": 20,
    "pint2": 100,
    "pint4": 20,
    "pint5": 50,
    "pinterest": 20,
    # Max AI chat calls per user per hour (owner and admins exempt).
    "ai": int(os.getenv("AI_LIMIT_PER_HOUR", "40")),
}

# ============================================================
# MEMORY
# ============================================================

# Optional free persistent store (Upstash Redis REST). If these env vars
# are missing or Upstash is unreachable, ARIA falls back to the local file.
UPSTASH_URL = os.getenv("UPSTASH_REDIS_REST_URL", "").strip().rstrip("/")
UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "").strip()
REMOTE_ENABLED = bool(UPSTASH_URL and UPSTASH_TOKEN)
KEY_DATA = "aria:data"
KEY_BANNED = "aria:banned"
REMOTE_FLUSH_SECONDS = int(os.getenv("REMOTE_FLUSH_SECONDS", "30"))

_memory_lock = threading.Lock()
_remote_lock = threading.Lock()
_dirty = False
_last_banned = None


def remote_cmd(*args):

    r = requests.post(
        UPSTASH_URL,
        headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
        json=list(args),
        timeout=5
    )

    r.raise_for_status()

    return r.json().get("result")


def _snapshot():

    # Another thread may change the dicts mid-dump; retry a few times.
    for _ in range(3):
        try:
            return json.dumps(
                {
                    "convo": conversation_memory,
                    "profile": user_profile
                },
                ensure_ascii=False
            )
        except RuntimeError:
            time.sleep(0.05)

    return None


def flush_remote(bans_only=False):

    global _dirty
    global _last_banned

    if not REMOTE_ENABLED:
        return

    with _remote_lock:

        try:

            banned_now = sorted(BANNED_USERS)

            if banned_now != _last_banned:
                remote_cmd(
                    "SET",
                    KEY_BANNED,
                    json.dumps(banned_now)
                )
                _last_banned = banned_now

            if not bans_only:

                snap = _snapshot()

                if snap:
                    remote_cmd("SET", KEY_DATA, snap)
                    _dirty = False

        except Exception as e:

            print("[REMOTE SAVE ERROR]", repr(e))


def _apply_memory(data, banned):

    global conversation_memory
    global user_profile
    global BANNED_USERS

    conversation_memory = data.get("convo", {})
    user_profile = data.get("profile", {})
    BANNED_USERS = set(banned)


def load_memory():

    global _last_banned

    data = None
    banned = None

    # 1. Try the remote store.
    if REMOTE_ENABLED:

        try:

            raw = remote_cmd("GET", KEY_DATA)
            raw_b = remote_cmd("GET", KEY_BANNED)

            if raw:
                data = json.loads(raw)

            if raw_b:
                banned = json.loads(raw_b)
                _last_banned = sorted(banned)

            print("[MEMORY] Loaded from Upstash")

        except Exception as e:

            print("[REMOTE LOAD ERROR]", repr(e))

    # 2. Fall back to the local file for anything missing.
    if (data is None or banned is None) and os.path.exists(MEMORY_FILE):

        try:

            with open(
                MEMORY_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                local = json.load(f)

            if data is None:
                data = {
                    "convo": local.get("convo", {}),
                    "profile": local.get("profile", {})
                }

            if banned is None:
                banned = local.get("banned", [])

            print("[MEMORY] Loaded from local file")

        except Exception as e:

            print("[MEMORY LOAD ERROR]", repr(e))

    _apply_memory(
        data or {},
        banned or []
    )


def save_memory():

    global _dirty

    try:

        with _memory_lock:

            with open(
                MEMORY_FILE + ".tmp",
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

            os.replace(MEMORY_FILE + ".tmp", MEMORY_FILE)

    except Exception as e:

        print("[MEMORY SAVE ERROR]", repr(e))

    if REMOTE_ENABLED:

        _dirty = True

        # Bans are saved to the remote store immediately.
        if sorted(BANNED_USERS) != _last_banned:
            flush_remote(bans_only=True)


def _remote_flusher():

    while True:

        time.sleep(REMOTE_FLUSH_SECONDS)

        if _dirty:
            flush_remote()


load_memory()

if REMOTE_ENABLED:

    threading.Thread(
        target=_remote_flusher,
        daemon=True
    ).start()

    atexit.register(
        lambda: flush_remote() if _dirty else None
    )

    # Push local-only data up on the first run.
    _dirty = True

else:

    print(
        "[WARNING] Upstash is not configured. Memory and bans "
        "only live in the local file and are lost on redeploy."
    )

# ============================================================
# RATE LIMITER
# ============================================================

def check_rate_limit(
    number,
    api_name
):

    now = time.time()

    key = f"{number}_{api_name}"

    with _rate_lock:

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
    if OWNER_NUMBER and from_number == OWNER_NUMBER:

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

    if PASSWORD and hmac.compare_digest(
        text.strip().upper().encode(),
        PASSWORD.upper().encode()
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

def _guess_image_mime(content_type, image_url):
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime.startswith("image/"):
        return mime
    lower = (image_url or "").lower().split("?", 1)[0]
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith(".gif"):
        return "image/gif"
    return "image/jpeg"


def _upload_whatsapp_media(image_bytes, mime_type):
    """Upload an image to WhatsApp and return its media ID."""
    upload_url = graph_url(f"{PHONE_NUMBER_ID}/media")
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    response = requests.post(
        upload_url,
        headers=headers,
        data={
            "messaging_product": "whatsapp",
            "type": mime_type,
        },
        files={"file": ("aria_image", image_bytes, mime_type)},
        timeout=45,
    )
    if not response.ok:
        raise RuntimeError(
            f"WhatsApp media upload HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )
    media_id = response.json().get("id")
    if not media_id:
        raise RuntimeError("WhatsApp media upload returned no media ID")
    return media_id


def send_image_url(to, image_url, caption=""):
    """Send a public image by downloading it first, then using a WhatsApp media ID.

    This is more reliable than asking WhatsApp to fetch third-party URLs directly,
    especially for Wikimedia, Pinterest and generated-image hosts.
    """
    if not image_url:
        send_text(to, "I couldn't find an image to send.")
        return False
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("[WHATSAPP IMAGE ERROR] WhatsApp credentials are missing.")
        return False

    message_url = graph_url(f"{PHONE_NUMBER_ID}/messages")
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        # Download the source ourselves so WhatsApp does not have to fetch it.
        image_response = requests.get(
            image_url,
            headers={"User-Agent": "ARIA-Bot/1.0"},
            timeout=45,
        )
        image_response.raise_for_status()
        image_bytes = image_response.content
        if not image_bytes:
            raise ValueError("Image source returned an empty file")
        if len(image_bytes) > 5 * 1024 * 1024:
            raise ValueError("Image is larger than WhatsApp's 5 MB image limit")

        mime_type = _guess_image_mime(
            image_response.headers.get("Content-Type"),
            image_url,
        )
        if mime_type not in {"image/jpeg", "image/png"}:
            # WhatsApp Cloud API image messages support JPEG/PNG.
            raise ValueError(f"Unsupported image type for WhatsApp: {mime_type}")

        media_id = _upload_whatsapp_media(image_bytes, mime_type)
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": {
                "id": media_id,
                "caption": caption[:1024],
            },
        }
        response = requests.post(
            message_url,
            headers=headers,
            json=payload,
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError(
                f"WhatsApp image send HTTP {response.status_code}: "
                f"{response.text[:1500]}"
            )
        return True

    except Exception as e:
        print("[WHATSAPP IMAGE MEDIA ERROR]", repr(e))

        # Last-resort fallback: let WhatsApp fetch the public URL itself.
        try:
            fallback_payload = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "image",
                "image": {
                    "link": image_url,
                    "caption": caption[:1024],
                },
            }
            fallback = requests.post(
                message_url,
                headers=headers,
                json=fallback_payload,
                timeout=30,
            )
            if fallback.ok:
                return True
            print("[WHATSAPP IMAGE LINK FALLBACK ERROR]", fallback.status_code, fallback.text[:1500])
        except Exception as fallback_error:
            print("[WHATSAPP IMAGE FALLBACK EXCEPTION]", repr(fallback_error))

        send_text(to, "The image could not be delivered.")
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
        f"?model={requests.utils.quote(IMAGE_MODEL)}"
        f"&width={IMAGE_WIDTH}"
        f"&height={max(IMAGE_HEIGHT, 1536)}"
        f"&enhance={str(IMAGE_ENHANCE).lower()}"
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

def _send_educational_result(sender, result):
    img_url = result.get("url") or result.get("thumbnail")
    if not img_url:
        return False
    caption = (
        f"🧪 Education: {(result.get('title') or 'Educational image')[:180]}\n"
        f"Source: {result.get('source', 'Openverse')}"
    )
    if result.get("creator"):
        caption += f"\nCreator: {str(result['creator'])[:120]}"
    if result.get("license"):
        caption += f"\nLicense: {str(result['license'])[:120]}"
    return send_image_url(sender, img_url, caption=caption)


def _search_wikimedia_education(query):
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": f"{query} diagram scientific educational apparatus",
        "gsrnamespace": "6",
        "gsrlimit": "8",
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": "1400",
        "format": "json",
        "formatversion": "2"
    }
    response = requests.get(
        "https://commons.wikimedia.org/w/api.php",
        params=params,
        headers={"User-Agent": "ARIA-Bot/1.0 (educational media search)"},
        timeout=15
    )
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", [])

    for page in pages:
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        if not (info.get("mime") or "").lower().startswith("image/"):
            continue
        ext = info.get("extmetadata") or {}

        def mv(key):
            value = ext.get(key, {}).get("value", "")
            return re.sub(r"<[^>]+>", "", value).strip() if isinstance(value, str) else ""

        return {
            "url": info.get("thumburl") or info.get("url"),
            "title": page.get("title", "Educational image").replace("File:", ""),
            "source": "Wikimedia Commons",
            "creator": mv("Artist"),
            "license": mv("LicenseShortName"),
        }
    return None


def _search_openverse_education(query):
    response = requests.get(
        "https://api.openverse.org/v1/images/",
        params={
            "q": f"{query} educational diagram scientific apparatus",
            "page_size": 8
        },
        headers={"User-Agent": "ARIA-Bot/1.0"},
        timeout=15
    )
    response.raise_for_status()
    for item in response.json().get("results", []):
        url = item.get("url") or item.get("thumbnail")
        if url:
            return {
                "url": url,
                "thumbnail": item.get("thumbnail"),
                "title": item.get("title") or "Educational image",
                "source": "Openverse",
                "creator": item.get("creator"),
                "license": item.get("license"),
            }
    return None


def pint5_education(sender, query):
    if not check_rate_limit(sender, "pint5"):
        send_text(sender, "Too many education searches. Try again later.")
        return

    send_text(sender, f"🧪 Education: *{query}*\nSearching educational diagrams...")

    try:
        result = _search_wikimedia_education(query)
        if result and _send_educational_result(sender, result):
            return
    except Exception as e:
        print("[PINT5 WIKIMEDIA ERROR]", repr(e))

    try:
        result = _search_openverse_education(query)
        if result and _send_educational_result(sender, result):
            return
    except Exception as e:
        print("[PINT5 OPENVERSE ERROR]", repr(e))

    send_text(
        sender,
        f"I couldn't find a suitable educational diagram for *{query}*.\n\n"
        "I did not fall back to Unsplash because `.edu` is reserved for "
        "educational material."
    )


# ============================================================
# PINTEREST
# ============================================================

def pint_pinterest(sender, query):
    if not PINTEREST_ACCESS_TOKEN:
        send_text(sender, "Pinterest is not configured.\n\nAdd `PINTEREST_ACCESS_TOKEN` to Render.")
        return

    if not check_rate_limit(sender, "pinterest"):
        send_text(sender, "Too many Pinterest searches. Try again later.")
        return

    send_text(sender, f"📌 Pinterest: *{query}*...")

    headers = {
        "Authorization": f"Bearer {PINTEREST_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "ARIA-Bot/1.0",
    }

    try:
        # /pins lists the authenticated account's Pins. For a keyword command,
        # Pinterest provides /search/pins, which searches that user's Pins.
        response = requests.get(
            "https://api.pinterest.com/v5/search/pins",
            headers=headers,
            params={"query": query, "page_size": 25},
            timeout=20,
        )

        if response.status_code == 401:
            print("[PINTEREST 401]", response.text[:1000])
            send_text(sender, "Pinterest rejected the access token (401). Generate a fresh production token with `pins:read` and update `PINTEREST_ACCESS_TOKEN` in Render.")
            return
        if response.status_code == 403:
            print("[PINTEREST 403]", response.text[:1000])
            send_text(sender, "Pinterest refused the search request (403). Your app/token may not have access to Pin search yet.")
            return
        response.raise_for_status()

        items = response.json().get("items", [])
        if not items:
            send_text(sender, f"No Pinterest Pins matched *{query}*.")
            return

        # Prefer a Pin with a usable image, then choose the first result.
        pin = next((item for item in items if (item.get("media") or {}).get("images")), items[0])
        media = pin.get("media") or {}
        images = media.get("images") or {}
        image_url = None
        for key in ("1200x", "600x", "400x300", "150x150", "orig", "originals"):
            candidate = images.get(key)
            if isinstance(candidate, dict):
                image_url = candidate.get("url")
            elif isinstance(candidate, str):
                image_url = candidate
            if image_url:
                break

        if not image_url:
            send_text(sender, "Pinterest returned a matching Pin without a usable image URL.")
            return

        caption = f"📌 Pinterest: {pin.get('title') or query}\nSource: Pinterest"
        if pin.get("link"):
            caption += f"\n{pin['link']}"
        send_image_url(sender, image_url, caption=caption)

    except Exception as e:
        print("[PINTEREST EXCEPTION]", repr(e))
        send_text(sender, "Pinterest search failed. Check the token/scopes and try again.")


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
        f"?model={requests.utils.quote(IMAGE_MODEL)}"
        f"&width={IMAGE_WIDTH}"
        f"&height={IMAGE_HEIGHT}"
        f"&enhance={str(IMAGE_ENHANCE).lower()}"
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
- The owner of this ARIA instance is Philimon Dean.
- Owner identity is enforced by the authenticated owner WhatsApp number.
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

    if (
        from_number != OWNER_NUMBER
        and from_number not in ADMIN_NUMBERS
        and not check_rate_limit(from_number, "ai")
    ):

        return (
            "You've reached the hourly AI limit. "
            "Please try again in a while."
        )

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

def download_whatsapp_image(image_ref, mime_type=None):
    """Download a WhatsApp image using a fresh media URL.

    WhatsApp media URLs are temporary. We therefore keep the media ID and
    retrieve a fresh URL immediately before vision processing.
    """
    if not image_ref:
        raise ValueError("WhatsApp returned no image reference.")
    if not WHATSAPP_TOKEN:
        raise RuntimeError("WHATSAPP_TOKEN is missing")

    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}

    # Incoming WhatsApp images are stored as media IDs in ARIA. For backwards
    # compatibility, a full URL is also accepted.
    if str(image_ref).startswith("http://") or str(image_ref).startswith("https://"):
        media_url = image_ref
        resolved_mime = mime_type
    else:
        media_response = requests.get(
            graph_url(str(image_ref)),
            headers=headers,
            timeout=20,
        )
        media_response.raise_for_status()
        media_info = media_response.json()
        media_url = media_info.get("url")
        resolved_mime = mime_type or media_info.get("mime_type")
        if not media_url:
            raise ValueError("Meta did not return a media URL.")

    # Media URLs expire quickly, so this request must happen right after the
    # URL is retrieved.
    response = requests.get(media_url, headers=headers, timeout=30)
    response.raise_for_status()
    if not response.content:
        raise ValueError("Downloaded image is empty.")

    detected_mime = (
        resolved_mime
        or response.headers.get("Content-Type", "image/jpeg")
    ).split(";", 1)[0].strip().lower()

    if not detected_mime.startswith("image/"):
        raise ValueError(f"Downloaded media is not an image: {detected_mime}")

    image_size_mb = len(response.content) / (1024 * 1024)
    if image_size_mb > 5:
        raise ValueError(
            f"Image is too large ({image_size_mb:.1f} MB). WhatsApp Cloud API supports images up to 5 MB."
        )

    encoded = base64.b64encode(response.content).decode("utf-8")
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
# VOICE / AUDIO
# ============================================================

def download_whatsapp_audio(media_id):
    if not WHATSAPP_TOKEN or not media_id:
        raise RuntimeError("WhatsApp audio credentials/media are missing")
    media_response = requests.get(graph_url(media_id), headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}, timeout=20)
    media_response.raise_for_status()
    info = media_response.json()
    media_url = info.get("url")
    mime_type = info.get("mime_type") or "audio/ogg"
    if not media_url:
        raise ValueError("Meta did not return an audio media URL")
    audio_response = requests.get(media_url, headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}, timeout=30)
    audio_response.raise_for_status()
    if not audio_response.content:
        raise ValueError("Downloaded audio is empty")
    if len(audio_response.content) > 25 * 1024 * 1024:
        raise ValueError("Audio exceeds the 25 MB transcription limit")
    return audio_response.content, mime_type

def transcribe_audio(audio_bytes, mime_type="audio/ogg"):
    if not client:
        raise RuntimeError("GROQ_API_KEY is missing")
    extension = ".ogg"
    if "mpeg" in mime_type or "mp3" in mime_type: extension = ".mp3"
    elif "wav" in mime_type: extension = ".wav"
    elif "mp4" in mime_type or "m4a" in mime_type: extension = ".m4a"
    elif "webm" in mime_type: extension = ".webm"
    transcription = client.audio.transcriptions.create(file=(f"aria_voice{extension}", audio_bytes), model=STT_MODEL, language=TTS_LANGUAGE or None, response_format="json", temperature=0.0)
    return (getattr(transcription, "text", "") or "").strip()

def generate_tts_audio(text):
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is missing")
    clean_text = re.sub(r"[*_`#]", "", text or "").strip()
    clean_text = re.sub(r"\s+", " ", clean_text)[:3500]
    if not clean_text:
        raise ValueError("Nothing to synthesize")
    response = requests.post("https://api.groq.com/openai/v1/audio/speech", headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}, json={"model": TTS_MODEL, "voice": TTS_VOICE, "input": clean_text, "response_format": "ogg", "speed": 1.0}, timeout=60)
    if not response.ok:
        raise RuntimeError(f"Groq TTS HTTP {response.status_code}: {response.text[:1000]}")
    return response.content

def send_audio_bytes(to, audio_bytes, mime_type="audio/ogg"):
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        return False
    upload = requests.post(graph_url(f"{PHONE_NUMBER_ID}/media"), headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}, data={"messaging_product": "whatsapp", "type": mime_type}, files={"file": ("aria_voice.ogg", audio_bytes, mime_type)}, timeout=45)
    if not upload.ok:
        print("[WHATSAPP AUDIO UPLOAD ERROR]", upload.status_code, upload.text[:1500])
        return False
    media_id = upload.json().get("id")
    if not media_id:
        return False
    sent = requests.post(graph_url(f"{PHONE_NUMBER_ID}/messages"), headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}, json={"messaging_product": "whatsapp", "to": to, "type": "audio", "audio": {"id": media_id}}, timeout=30)
    if not sent.ok:
        print("[WHATSAPP AUDIO SEND ERROR]", sent.status_code, sent.text[:1500])
        return False
    return True

def send_voice_reply(to, text):
    try:
        return send_audio_bytes(to, generate_tts_audio(text))
    except Exception as e:
        print("[VOICE REPLY ERROR]", repr(e))
        return False


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
*Owner:* Philimon Dean
*Owner protection:* ENABLED
*Content safety:* ENABLED
*Voice:* CONFIGURABLE
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
• `.pinterest <query>` (Pinterest keyword search)
• `imagine <prompt>`
• `.play <song name>`

*SYSTEM*
• `.about`
• `.health`
• `.voice on/off`
• `.status`
• Live web search: disabled until a working provider is configured
• `.menu`
• `.help <command>`

*OWNER*
• `.users`
• `.ban <number>`
• `.unban <number>`

Legacy `.pint1`–`.pint6` still work.
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

    pinterest_status = (
        "CONFIGURED"
        if PINTEREST_ACCESS_TOKEN
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
*Pinterest:* {pinterest_status}
*Live Search:* DISABLED
*Voice Mode:* {VOICE_MODE}
*STT:* {STT_MODEL}
*TTS:* {TTS_MODEL} / {TTS_VOICE}

〔 *SYSTEMS* 〕
*WhatsApp:* {whatsapp}
*Memory:* OK
*Pending Images:* {pending_images}
*Image Fallback:* {"ENABLED" if GEMINI_API_KEY else "DISABLED"}
"""

# ============================================================
# WEBHOOK
# ============================================================

# ============================================================
# WEBHOOK SECURITY + DUPLICATE PROTECTION
# ============================================================

_seen_ids = OrderedDict()
_seen_lock = threading.Lock()
SEEN_MAX = 2000


def verify_signature(raw_body, header):
    """Verify Meta's X-Hub-Signature-256 header."""
    if not APP_SECRET:
        # Not configured: allow, but this is insecure (warned at startup).
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(
        APP_SECRET.encode(),
        raw_body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header[7:])


def is_duplicate(msg_id):
    """True if this WhatsApp message id was already handled."""
    if not msg_id:
        return False
    with _seen_lock:
        if msg_id in _seen_ids:
            return True
        _seen_ids[msg_id] = time.time()
        while len(_seen_ids) > SEEN_MAX:
            _seen_ids.popitem(last=False)
    return False


if not APP_SECRET:
    print("[WARNING] WHATSAPP_APP_SECRET is not set. Webhook signatures are NOT verified.")

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
    global last_image_context
    global VOICE_MODE
    global voice_enabled_users

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

    raw_body = request.get_data()

    if not verify_signature(
        raw_body,
        request.headers.get("X-Hub-Signature-256")
    ):

        print("[WEBHOOK] Invalid signature rejected")

        return (
            "Forbidden",
            403
        )

    data = request.get_json(
        silent=True
    )

    # Reply to Meta immediately; do the slow work (AI, images, voice)
    # in a background thread so Meta never times out and retries.
    threading.Thread(
        target=process_webhook,
        args=(data,),
        daemon=True
    ).start()

    return (
        "OK",
        200
    )


def process_webhook(data):

    global last_explain_topic
    global user_waiting_image
    global last_image_context
    global VOICE_MODE
    global voice_enabled_users

    try:

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

        if is_duplicate(msg.get("id")):

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

            # Fresh password authentication starts at the menu.
            send_text(
                from_number,
                get_menu()
            )

            return (
                "OK",
                200
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

                media_mime_type = (
                    media_info.get(
                        "mime_type"
                    )
                    or incoming_mime_type
                )

                # Keep the durable media ID instead of Meta's temporary
                # lookaside URL. A fresh URL is resolved when vision runs.
                user_waiting_image[
                    from_number
                ] = {
                    "media_id": image_id,
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
        # AUDIO / VOICE MESSAGE
        # ====================================================
        if msg.get("type") == "audio":
            audio_data = msg.get("audio") or {}
            media_id = audio_data.get("id")
            if not media_id:
                send_text(from_number, "I couldn't retrieve that voice note.")
                return "OK", 200
            try:
                send_text(from_number, "🎤 Listening...")
                audio_bytes, audio_mime = download_whatsapp_audio(media_id)
                transcript = transcribe_audio(audio_bytes, audio_mime)
                if not transcript:
                    send_text(from_number, "I couldn't make out what you said. Try again.")
                    return "OK", 200
                add_to_memory(from_number, "user", f"[Voice] {transcript}")
                result = ai_call(transcript, from_number)
                add_to_memory(from_number, "assistant", result)
                if VOICE_MODE in {"voice", "audio", "on"} or from_number in voice_enabled_users:
                    if not send_voice_reply(from_number, result):
                        send_text(from_number, result)
                else:
                    send_text(from_number, f"🎤 {transcript}\n\n{result}")
            except Exception as e:
                print("[VOICE INPUT ERROR]", repr(e))
                send_text(from_number, "I couldn't process that voice note. Check `.health` or try again.")
            return "OK", 200

        if tl in {".voice", ".voice status"}:
            send_text(from_number, f"Voice mode: *{VOICE_MODE}*\n\nUse `.voice on` or `.voice off`.")
            return "OK", 200

        if tl == ".voice on":
            voice_enabled_users.add(from_number)
            send_text(from_number, "Voice replies enabled for you.")
            return "OK", 200

        if tl == ".voice off":
            voice_enabled_users.discard(from_number)
            send_text(from_number, "Voice replies disabled for you.")
            return "OK", 200

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
                f"〔 *VOICE* 〕\n"
                f"*Mode:* {VOICE_MODE}\n"
                f"*STT:* {STT_MODEL}\n"
                f"*TTS:* {TTS_MODEL} / {TTS_VOICE}\n\n"
                f"〔 *SECURITY* 〕\n"
                f"*Owner:* PROTECTED\n"
                f"*Password:* {'ENVIRONMENT' if ARIA_PASSWORD else 'DISABLED'}\n"
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

        if tl.startswith(".image "):
            question = text[len(".image "):].strip()
            saved_image = last_image_context.get(from_number)

            if not saved_image:
                send_text(from_number, "No recent image is available. Send an image first.")
                return "OK", 200

            if (
                saved_image.get("saved_at")
                and time.time() - saved_image["saved_at"] > IMAGE_WAIT_TIMEOUT
            ):
                last_image_context.pop(from_number, None)
                send_text(from_number, "That image context has expired. Send the image again.")
                return "OK", 200

            if not question:
                send_text(from_number, "Usage: `.image <question>`")
                return "OK", 200

            send_text(from_number, "Looking at the image again...")
            result = vision_call(
                saved_image.get("media_id") or saved_image.get("url"),
                (
                    "Answer the user's follow-up question about this same image. "
                    "Use only information reasonably visible in the image. "
                    "If something is unclear or not visible, say so instead of guessing.\n\n"
                    f"Question: {question}"
                ),
                saved_image.get("mime_type", "image/jpeg")
            )
            result = result or "I couldn't answer that from the image."
            add_to_memory(from_number, "assistant", result)
            send_text(from_number, result)
            return "OK", 200

        if tl.startswith(".describe ask "):
            question = text[len(".describe ask "):].strip()
            saved_image = last_image_context.get(from_number)

            if not saved_image:
                send_text(from_number, "No recent image is available. Send an image first.")
                return "OK", 200

            if not question:
                send_text(from_number, "Usage: `.describe ask <question>`")
                return "OK", 200

            send_text(from_number, "Looking at the image again...")
            result = vision_call(
                saved_image.get("media_id") or saved_image.get("url"),
                (
                    "Answer this follow-up question about the image. "
                    "Do not invent details that are not visible.\n\n"
                    f"Question: {question}"
                ),
                saved_image.get("mime_type", "image/jpeg")
            )
            result = result or "I couldn't answer that from the image."
            add_to_memory(from_number, "assistant", result)
            send_text(from_number, result)
            return "OK", 200

        vision_commands = {
            ".describe", ".describe detailed", ".verify",
            ".solve", ".math", ".read"
        }

        if tl in vision_commands:
            saved_image = user_waiting_image.get(from_number)

            if saved_image and (
                saved_image.get("saved_at")
                and time.time() - saved_image["saved_at"] > IMAGE_WAIT_TIMEOUT
            ):
                user_waiting_image.pop(from_number, None)
                saved_image = None

            if not saved_image:
                send_text(from_number, "No recent image is waiting. Send an image first.")
                return "OK", 200

            # Keep the image available for explicit follow-up questions.
            last_image_context[from_number] = saved_image

            image_url = saved_image.get("media_id") or saved_image.get("url")
            mime_type = saved_image.get("mime_type", "image/jpeg")

            if tl == ".solve":
                send_text(from_number, "Reading the problem and solving it...")
                result = solve_image_problem(image_url, mime_type, "universal")
            elif tl == ".math":
                send_text(from_number, "Reading the mathematics...")
                result = solve_image_problem(image_url, mime_type, "math")
            elif tl == ".read":
                send_text(from_number, "Reading the text...")
                result = vision_call(
                    image_url,
                    "Extract the readable text from this image. Return only text you can actually read, preserving useful line breaks. If some text is unclear, mark it [unclear] instead of inventing it.",
                    mime_type
                )
            elif tl == ".verify":
                send_text(from_number, "Analyzing the image...")
                result = vision_call(
                    image_url,
                    "Analyze this image for visible indicators of AI generation, manipulation, editing, or misleading presentation. Give visible evidence, possible indicators, and what cannot be determined from the image alone. Do not claim certainty from visual inspection alone.",
                    mime_type
                )
            else:
                detailed = tl == ".describe detailed"
                send_text(from_number, "Analyzing image...")
                prompt = (
                    "Describe this image naturally for WhatsApp. Start with one concise "
                    "sentence, then useful bullet points. Mention readable text only when "
                    "actually legible. Do not guess identities or unreadable details."
                )
                prompt += (
                    " Include composition, setting, colors, notable objects, actions, "
                    "visual style, and readable text."
                    if detailed else
                    " Keep it to roughly 100-180 words."
                )
                result = vision_call(image_url, prompt, mime_type)

            result = result or "I couldn't process that image."
            add_to_memory(from_number, "assistant", result)
            send_text(from_number, result)
            return "OK", 200

        # ====================================================
        # MEDIA ALIASES
        # ====================================================
        media_aliases = [(".photo", pint1_unsplash), (".wallpaper", pint2_pexels), (".anime", pint3_anime), (".comic", pint4_comics), (".edu", pint5_education), (".pinterest", pint_pinterest)]
        for command, handler in media_aliases:
            if tl.startswith(command + " "):
                query = text[len(command):].strip()
                if not query:
                    send_text(from_number, f"Usage: `{command} <query>`")
                else:
                    handler(from_number, query)
                return "OK", 200
        if tl == ".pint":
            send_text(from_number, "〔 PINT 〕\n\nChoose:\n• `.photo <query>`\n• `.wallpaper <query>`\n• `.anime <character>`\n• `.comic <query>`\n• `.edu <subject>`\n• `.pinterest <query>` (Pinterest keyword search)")
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

        if tl.startswith(
            ".pint6 "
        ):

            pint_pinterest(
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
                ".describe": "Send an image, then `.describe`. Use `.describe detailed` for more detail. Follow up with `.image <question>`.",
                ".verify": "Send an image, then `.verify`. ARIA reports visible indicators without claiming forensic certainty.",
                ".pint": "Use `.photo`, `.wallpaper`, `.anime`, `.comic`, `.edu`, or `.pinterest`.",
                ".pinterest": "Uses the Pinterest account connected to ARIA. Requires PINTEREST_ACCESS_TOKEN with pins:read.",
                ".about": "Shows ARIA's identity and core protections.",
                ".status": "Shows ARIA's runtime and provider configuration.",
                ".health": "Checks the main dependencies and AI providers.",
                ".voice": "Voice notes are transcribed with Groq Whisper. Use `.voice on` for spoken replies and `.voice off` for text replies.",
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





























