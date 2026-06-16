# from fastapi import FastAPI, Request
# import httpx
# import asyncio
# from fastapi.responses import PlainTextResponse

# app = FastAPI()

# VERIFY_TOKEN = "my_custom_verify_token"  # set same in Meta dev portal
# WHATSAPP_TOKEN = "EAAV2f979RF0BRgZCHfieCYyY7YuPuXdDj1Lc7k8LknTqu9V6qIQI5JERPctRiSZAUywKqZASKONBRAh3wEFZAuFwxoESlXguQAJII2v3yz6LOEgi9PaLj6sZB4v0w94KjqosR8hIEdLgOwIveOJioGhMZCIZAsSWjAZABthxGxqe0YcHZClo0ncC9y6thHAU2gAZDZD"  # your Meta access token
# # PHONE_NUMBER_ID = "1096629463540487" # 03334530105
# PHONE_NUMBER_ID = "1149603001567952" # 03204343279


# # GROQ_BACKEND_URL = "http://127.0.0.1:9000/chat"  # calls main.py

# # 🔥 Global HTTPX client (reused, avoids handshake delay)
# client = httpx.AsyncClient(timeout=20.0)

# def estimate_typing_time(text: str, wps: float = 2.0, max_wait: int = 10) -> float:
#     word_count = len(text.strip().split())
#     est_time = word_count / wps
#     return min(est_time, max_wait)


# # 🧠 Bypass ngrok warning
# @app.middleware("http")
# async def add_ngrok_header(request: Request, call_next):
#     response = await call_next(request)
#     response.headers["ngrok-skip-browser-warning"] = "true"
#     return response

# @app.get("/webhook")
# async def verify_webhook(request: Request):
#     params = request.query_params
#     mode = params.get("hub.mode")
#     token = params.get("hub.verify_token")
#     challenge = params.get("hub.challenge")

#     if mode == "subscribe" and token == VERIFY_TOKEN:
#         return PlainTextResponse(content=challenge)
#     return PlainTextResponse(content="Invalid token", status_code=403)


# # ✅ Helper to mark message as read (fire-and-forget)
# async def mark_as_read(message_id: str):
#     payload = {
#         "messaging_product": "whatsapp",
#         "status": "read",
#         "message_id": message_id,
#     }
#     try:
#         await client.post(
#             f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages",
#             headers={
#                 "Authorization": f"Bearer {WHATSAPP_TOKEN}",
#                 "Content-Type": "application/json"
#             },
#             json=payload
#         )
#     except Exception as e:
#         print("⚠️ mark_as_read failed:", e)



# @app.post("/webhook")
# async def receive_message(req: Request):
#     data = await req.json()
#     print("📩 Incoming WhatsApp Webhook:\n", data)

#     try:
#         value = data["entry"][0]["changes"][0]["value"]

#         if "messages" not in value:
#             return {"status": "ignored"}

#         message = value["messages"][0]["text"]["body"]
#         sender = value["messages"][0]["from"]
#         message_id = value["messages"][0]["id"]
#         print(f"📨 Message from {sender}: {message}")

#         # ✅ Fire read instantly (no wait)
#         asyncio.create_task(mark_as_read(message_id))

#         # ✅ Start LLM+RAG in background immediately
#         # async def call_llm():
#         #     resp = await client.post(
#         #         GROQ_BACKEND_URL,
#         #         json={"message": message, "user_id": sender}
#         #     )
#         #     return (await resp.aread()).decode()

#         # llm_task = asyncio.create_task(call_llm())

#         # ✅ Typing indicator (simulated)
#         typing_payload = {
#             "messaging_product": "whatsapp",
#             "status": "read",
#             "message_id": message_id,
#             "typing_indicator": {
#                 "type": "text"
#             }
#         }
#         await client.post(
#             f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages",
#             headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"},
#             json=typing_payload
#         )
#         await asyncio.sleep(1)  # simulate typing time

#         # ✅ Wait for AI reply
#         # ai_reply = await llm_task
#         ai_reply = "Test reply without LLM"

#         # Extract text from ai_reply
#         lines = ai_reply.strip().splitlines()
#         if lines and "Model Time" in lines[0]:
#             reply_text = "\n".join(lines[1:])
#         else:
#             reply_text = ai_reply.strip()

#         # ✅ Send reply
#         payload = {
#             "messaging_product": "whatsapp",
#             "to": sender,
#             "text": {"body": reply_text}
#         }
#         headers = {
#             "Authorization": f"Bearer {WHATSAPP_TOKEN}",
#             "Content-Type": "application/json"
#         }
#         await client.post(
#             f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages",
#             json=payload, headers=headers
#         )

#         return {"status": "sent"}

#     except Exception as e:
#         print("❌ Error handling webhook:", e)
#         return {"status": "error", "details": str(e)}


























from fastapi import FastAPI, Request
import httpx
import asyncio
from fastapi.responses import PlainTextResponse
import os
from datetime import datetime

app = FastAPI()

VERIFY_TOKEN = "my_custom_verify_token"  # set same in Meta dev portal
WHATSAPP_TOKEN = "EAAV2f979RF0BRgZCHfieCYyY7YuPuXdDj1Lc7k8LknTqu9V6qIQI5JERPctRiSZAUywKqZASKONBRAh3wEFZAuFwxoESlXguQAJII2v3yz6LOEgi9PaLj6sZB4v0w94KjqosR8hIEdLgOwIveOJioGhMZCIZAsSWjAZABthxGxqe0YcHZClo0ncC9y6thHAU2gAZDZD"  # your Meta access token
PHONE_NUMBER_ID = "1096629463540487" # 03334530105
# PHONE_NUMBER_ID = "1149603001567952" # 03204343279
GROQ_BACKEND_URL = "http://127.0.0.1:9000/chat"

# 🔥 HTTP client
client = httpx.AsyncClient(timeout=20.0)

# 📁 Folder to store images
IMAGE_DIR = "received_images"
os.makedirs(IMAGE_DIR, exist_ok=True)


# =========================
# HELPERS
# =========================

def estimate_typing_time(text: str, wps: float = 2.0, max_wait: int = 10) -> float:
    word_count = len(text.strip().split())
    return min(word_count / wps, max_wait)


async def get_media_url(media_id: str):
    url = f"https://graph.facebook.com/v23.0/{media_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}

    resp = await client.get(url, headers=headers)
    data = resp.json()
    return data["url"]


async def download_media(media_url: str):
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    resp = await client.get(media_url, headers=headers)
    return await resp.aread()


def save_image(image_bytes: bytes, sender: str):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{sender}_{timestamp}.jpg"
    path = os.path.join(IMAGE_DIR, filename)

    with open(path, "wb") as f:
        f.write(image_bytes)

    return path


async def process_image(media_id: str, sender: str):
    try:
        # 1. Get URL
        media_url = await get_media_url(media_id)

        # 2. Download
        image_bytes = await download_media(media_url)

        # 3. Save
        path = save_image(image_bytes, sender)

        print(f"🖼️ Image saved in background: {path}")

    except Exception as e:
        print("❌ Background image processing failed:", e)


# =========================
# MIDDLEWARE
# =========================
@app.middleware("http")
async def add_ngrok_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["ngrok-skip-browser-warning"] = "true"
    return response


# =========================
# WEBHOOK VERIFY
# =========================
@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(content=challenge)

    return PlainTextResponse(content="Invalid token", status_code=403)


# =========================
# MARK AS READ
# =========================
async def mark_as_read(message_id: str):
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }

    try:
        await client.post(
            f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages",
            headers={
                "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                "Content-Type": "application/json"
            },
            json=payload
        )
    except Exception as e:
        print("⚠️ mark_as_read failed:", e)


# =========================
# MAIN WEBHOOK
# =========================
@app.post("/webhook")
async def receive_message(req: Request):
    data = await req.json()
    print("📩 Incoming WhatsApp Webhook:\n", data)

    try:
        value = data["entry"][0]["changes"][0]["value"]

        if "messages" not in value:
            return {"status": "ignored"}

        msg = value["messages"][0]
        msg_type = msg["type"]

        sender = msg["from"]
        message_id = msg["id"]

        text = None
        saved_image_path = None

        print(f"📨 Message type: {msg_type} from {sender}")

        # =====================
        # TEXT MESSAGE
        # =====================
        if msg_type == "text":
            text = msg["text"]["body"]

        # =====================
        # IMAGE MESSAGE
        # =====================
        elif msg_type == "image":
            media_id = msg["image"]["id"]

            # 🚀 Run in background (NON-BLOCKING)
            asyncio.create_task(process_image(media_id, sender))

            saved_image_path = None  # we don't wait anymore

            # optional caption
            text = msg["image"].get("caption", "")

        # =====================
        # MARK AS READ
        # =====================
        asyncio.create_task(mark_as_read(message_id))
        
        # =====================
        # INITIALIZE LLM HERE
        # =====================

        # ✅ Start LLM+RAG in background immediately
        async def call_llm():
            resp = await client.post(
                GROQ_BACKEND_URL,
                json={"message": text, "user_id": sender}
            )
            return (await resp.aread()).decode()

        llm_task = asyncio.create_task(call_llm())

        # =====================
        # SIMULATE TYPING
        # =====================
        typing_payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
            "typing_indicator": {
                "type": "text"
            }
        }

        await client.post(
            f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages",
            headers={
                "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                "Content-Type": "application/json"
            },
            json=typing_payload
        )

        await asyncio.sleep(1)

        # =====================
        # AI RESPONSE (PLACEHOLDER)
        # =====================
        
        # ai_reply = "Test reply without LLM"
        ai_reply = await llm_task
        reply_text = ai_reply.strip()

        # =====================
        # SEND RESPONSE
        # =====================
        payload = {
            "messaging_product": "whatsapp",
            "to": sender,
            "text": {"body": reply_text}
        }

        await client.post(
            f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages",
            json=payload,
            headers={
                "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                "Content-Type": "application/json"
            }
        )

        return {
            "status": "sent",
            "saved_image": saved_image_path
        }

    except Exception as e:
        print("❌ Error handling webhook:", e)
        return {"status": "error", "details": str(e)}