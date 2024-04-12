from fastapi import HTTPException
import httpx
import tempfile
import os
from heyoo import WhatsApp
import torch
import whisper
import logging


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def retrieve_media_url(media_id: str):
    access_token = os.getenv("ACCESS_TOKEN")
    whatsapp_api_url = 'https://graph.facebook.com/v19.0'
    headers = {'Authorization': f'Bearer {access_token}'}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{whatsapp_api_url}/{media_id}", headers=headers)
    if response.status_code == 200:
        return response.json().get("url")
    else:
        raise HTTPException(status_code=response.status_code, detail="Failed to retrieve media URL")


async def download_audio(media_url: str):
    access_token = os.getenv("ACCESS_TOKEN")
    headers = {'Authorization': f'Bearer {access_token}'}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(media_url, headers=headers)
    if response.status_code == 200:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".ogg")
        temp_file.write(response.content)
        temp_file.close()
        return temp_file.name
    else:
        # Improved error logging
        logger.error(f"Failed to download media. Status code: {response.status_code}, Response: {response.text}")
        raise HTTPException(status_code=response.status_code, detail="Failed to download media")


def modify_sender_number(sender: str):
    return sender[:2] + sender[3:] if sender.startswith("549") else sender

async def enviar(telefonoRecibe: str, respuesta: str):
    token = os.getenv("ACCESS_TOKEN")
    idNumeroTelefono = os.getenv("ID_TELEFONO")
    mensajeWa = WhatsApp(token, idNumeroTelefono)
    mensajeWa.send_message(respuesta, telefonoRecibe)

async def transcribe_audio_and_send(audio_id: str, telefonoCliente: str, gpu_id: str):
    media_url = await retrieve_media_url(audio_id)
    audio_file_path = await download_audio(media_url)
    if not audio_file_path:
        return
    #device = "cuda" if torch.cuda.is_available() else "cpu"
    model = whisper.load_model("medium", device=gpu_id)
    result = model.transcribe(audio_file_path)
    transcription = result['text']
    await enviar(telefonoCliente, transcription)
    os.remove(audio_file_path)
