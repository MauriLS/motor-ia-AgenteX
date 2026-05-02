from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Literal
import httpx
import os
from dotenv import load_dotenv

# =========================
# CONFIGURACIÓN
# =========================
load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
# Usamos el endpoint estándar compatible con OpenAI de DeepSeek
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions" 

if not DEEPSEEK_API_KEY:
    print("ADVERTENCIA: DEEPSEEK_API_KEY no está definida en el archivo .env")

# Instancia de la aplicación (Esta es la variable 'app' que Uvicorn estaba buscando)
app = FastAPI(title="Agente X - Motor IA (Intermediario)")

# =========================
# MODELOS DE DATOS (Seguridad B2B)
# =========================
class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str

class ChatRequest(BaseModel):
    user_id: int
    pregunta: str
    history: Optional[List[Message]] = []

# =========================
# LÓGICA CENTRAL
# =========================
@app.post("/api/ia/process")
async def process_chat(req: ChatRequest):
    if not req.pregunta.strip():
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía")

    if not DEEPSEEK_API_KEY:
         raise HTTPException(status_code=500, detail="Error de servidor: API Key de DeepSeek no configurada.")

    # 1. Definir la identidad del Agente
    system_message = {
        "role": "system",
        "content": (
            "Eres el Agente X, un asesor corporativo y analista de datos de alto nivel. "
            "Responde de forma directa, racional y sin adornos. "
            "Si no sabes algo, dilo inmediatamente. No inventes información."
        )
    }

    # 2. Construir el historial de mensajes
    messages_payload = [system_message]
    
    if req.history:
        messages_payload.extend([msg.model_dump() for msg in req.history])
        
    messages_payload.append({"role": "user", "content": req.pregunta})

