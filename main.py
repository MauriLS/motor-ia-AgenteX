# motor-ia-AgenteX/main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Literal
import httpx
import os
import json
from dotenv import load_dotenv

# 1. IMPORTAMOS TUS HERRAMIENTAS CORPORATIVAS
from tools import tools_manifest, consultar_producto_tienda

# =========================
# CONFIGURACIÓN
# =========================
load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions" 

if not DEEPSEEK_API_KEY:
    print("ADVERTENCIA: DEEPSEEK_API_KEY no está definida en el archivo .env")

app = FastAPI(title="Agente X - Motor IA (Intermediario)")

# =========================
# MODELOS DE DATOS
# =========================
class Message(BaseModel):
    role: Literal["user", "assistant", "system", "tool"]
    content: str

class ChatRequest(BaseModel):
    user_id: int
    pregunta: str
    history: Optional[List[Message]] = []

# =========================
# LÓGICA CENTRAL (El Orquestador)
# =========================
@app.post("/api/ia/process")
async def process_chat(req: ChatRequest):
    if not req.pregunta.strip():
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía")

    if not DEEPSEEK_API_KEY:
         raise HTTPException(status_code=500, detail="Error de servidor: API Key no configurada.")

    system_message = {
        "role": "system",
        "content": (
            "Eres el Agente X, encargado de la Bodega. Eres directo y analítico. "
            "Tienes acceso a consultar productos en tiempo real. SIEMPRE usa tus herramientas "
            "si el usuario pregunta por un producto específico, precio o detalle de catálogo."
        )
    }

    messages_payload = [system_message]
    
    if req.history:
        messages_payload.extend([msg.model_dump() for msg in req.history])
        
    messages_payload.append({"role": "user", "content": req.pregunta})

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    # 2. EL BUCLE DE RAZONAMIENTO (Tool Calling Loop)
    MAX_ITERATIONS = 3 # Cortafuegos B2B para evitar ciclos infinitos
    iteration = 0

    while iteration < MAX_ITERATIONS:
        payload = {
            "model": "deepseek-chat",
            "messages": messages_payload,
            "temperature": 0.3,
            "max_tokens": 1500,
            "tools": tools_manifest # Inyectamos el catálogo de herramientas
        }

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(DEEPSEEK_API_URL, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()

            ia_message = data["choices"][0]["message"]
            finish_reason = data["choices"][0]["finish_reason"]

            # CASO A: La IA decidió que NECESITA consultar la base de datos
            if finish_reason == "tool_calls":
                # 1. Guardamos el intento de la IA en la memoria local
                messages_payload.append(ia_message) 

                # 2. Ejecutamos cada herramienta que haya solicitado
                for tool_call in ia_message.get("tool_calls", []):
                    function_name = tool_call["function"]["name"]
                    arguments = json.loads(tool_call["function"]["arguments"])

                    if function_name == "consultar_producto_tienda":
                        product_id = arguments.get("product_id")
                        print(f"🔥 ORQUESTADOR: Ejecutando endpoint para el Producto {product_id}...")
                        
                        # Ejecutamos la función física (La Pala)
                        tool_result = await consultar_producto_tienda(product_id)

                        # Inyectamos los datos reales de vuelta a la memoria
                        messages_payload.append({
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "name": function_name,
                            "content": tool_result
                        })
                
                iteration += 1
                continue # Volvemos al inicio del 'while' para que la IA lea los datos

            # CASO B: La IA ya tiene los datos o no necesitó herramientas. Entrega texto final.
            else:
                return {
                    "success": True,
                    "user_id": req.user_id,
                    "respuesta": ia_message.get("content", "").strip()
                }

        except httpx.HTTPStatusError as e:
            print(f"Error HTTP: {e.response.text}")
            raise HTTPException(status_code=502, detail=f"Error API: {e.response.status_code}")
        except Exception as e:
            print(f"Error interno: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Fallo del motor: {str(e)}")

    # Si se rompe el bucle de iteraciones (Cortafuegos)
    raise HTTPException(status_code=500, detail="El agente entró en un bucle infinito de herramientas.")