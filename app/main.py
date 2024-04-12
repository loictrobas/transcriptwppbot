from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from dotenv import load_dotenv
import os
from app.whatsapp_utils import transcribe_audio_and_send, enviar, modify_sender_number
from fastapi.responses import PlainTextResponse
import logging
import asyncio
from typing import Tuple, Dict, List



logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI()

# Load the verification token from .env
VERIFICATION_TOKEN = os.getenv('VERIFICATION_TOKEN')
# Load other required environment variables
WHATSAPP_ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
ID_NUMERO_TELEFONO = os.getenv("ID_TELEFONO")

# Define a set of allowed phone numbers
ALLOWED_NUMBERS = {
    '5491155613212',
    '541155613212',
    '541160415012',
    '541155168045',
    '541157553398',
    # Continue adding numbers as needed
}

# Set processed IDs to remember which messages have been handled
processed_ids = set()

# Semaphores for GPU control
gpu_semaphores = {
    "cuda:0": asyncio.Semaphore(2),
    "cuda:1": asyncio.Semaphore(2),
}

# Queue for managing transcription tasks
transcription_queue = asyncio.Queue()


# Background task function to consume the transcription queue
async def consume_transcription_queue(gpu_id):
    while True:
        task = await transcription_queue.get()
        audio_id, telefonoCliente, semaphore = task
        async with semaphore:  # Limit the number of concurrent tasks per GPU
            await transcribe_audio_and_send(audio_id, telefonoCliente, gpu_id)  # This is your existing function
        transcription_queue.task_done()
        logger.info(f"Task completed on {gpu_id}: {audio_id}")
        logger.info(f"Queue size is: {transcription_queue.qsize()} task(s) pending")

# Start the consumer tasks for each GPU
for _ in range(2):  # Two workers for "cuda:0"
    asyncio.create_task(consume_transcription_queue("cuda:0"), name="cuda:0_worker")
for _ in range(2):  # Two workers for "cuda:1"
    asyncio.create_task(consume_transcription_queue("cuda:1"), name="cuda:1_worker")

@app.get("/webhook/")
async def verify_webhook(request: Request):
    hub_mode = request.query_params.get('hub.mode')
    hub_challenge = request.query_params.get('hub.challenge')
    hub_verify_token = request.query_params.get('hub.verify_token')    
    if hub_mode == 'subscribe' and hub_verify_token == "otro":
        return PlainTextResponse(content=hub_challenge)
    else:
        logger.warning(f"Webhook verification failed: mode={hub_mode}, token={hub_verify_token}")
        raise HTTPException(status_code=403, detail="Verification token mismatch")

@app.post("/webhook/")
async def handle_messages(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    for entry in data.get('entry', []):
        for change in entry.get('changes', []):
            if 'messages' in change.get('value', {}):
                messages = change['value']['messages']
                for message in messages:
                    message_type = message.get('type')
                    message_from = message.get('from')
                    telefonoCliente = modify_sender_number(message_from)
                    logger.info(f"Mensa de {telefonoCliente} recibido")
                    # Check if the sender's number is allowed
                    if telefonoCliente not in ALLOWED_NUMBERS:
                        # If the number is not allowed, send a response and continue to the next message
                        non_allowed_response = "Service not available for this number, please message loic@1stave.ba"
                        background_tasks.add_task(enviar, telefonoCliente, non_allowed_response)
                        continue

                    if message_type == 'audio':
                        audio_id = message.get('audio', {}).get('id')
                        if audio_id and audio_id not in processed_ids:
                            processed_ids.add(audio_id)
                            # Determine which GPU semaphore to use based on the current load
                            gpu_id = "cuda:0" if gpu_semaphores["cuda:0"]._value > gpu_semaphores["cuda:1"]._value else "cuda:1"
                            semaphore = gpu_semaphores[gpu_id]
                            # Queue the transcription task
                            await transcription_queue.put((audio_id, telefonoCliente, semaphore))
                            logger.info(f"Task enqueued for {gpu_id}: {audio_id}")
                            logger.info(f"Queue size is: {transcription_queue.qsize()} task(s) pending")
                    else:
                        # Respond to non-audio messages
                        non_audio_response = "Sorry, this service is only to transcribe audio messages. Please try sending a voice note."
                        background_tasks.add_task(enviar, telefonoCliente, non_audio_response)
    return {"status": "success"}
