# motor-ia-AgenteX/main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
import json
from dotenv import load_dotenv

from tools import tools_manifest, consultar_inventario_erp

# =========================
# CONFIGURACIÓN
# =========================
load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions" 

app = FastAPI(title="Agente X - Motor IA (Stateless Worker)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# EL NUEVO CONTRATO MULTI-TENANT (SaaS)
# =========================
class ChatRequest(BaseModel):
    user_id: int
    pregunta: str
    history: Optional[List[Dict[str, Any]]] = []
    system_prompt: str 
    allowed_tools: List[str] 
    tenant_config: Dict[str, Any] 
    temperature: float = 0.3 # 🚩 Inyectado: Control cognitivo dinámico

# =========================
# LÓGICA CENTRAL
# =========================
@app.post("/api/ia/process")
async def process_chat(req: ChatRequest):
    if not req.pregunta.strip():
        raise HTTPException(status_code=400, detail="Pregunta vacía")

    # 1. Inyectamos el prompt dinámico que viene de Node.js
    messages_payload = [{"role": "system", "content": req.system_prompt}]
    
    if req.history:
        messages_payload.extend(req.history)
        
    messages_payload.append({"role": "user", "content": req.pregunta})

    # 2. Filtramos el catálogo de herramientas según lo que Node.js permita para este cliente
    active_tools = [tool for tool in tools_manifest if tool["function"]["name"] in req.allowed_tools]

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    MAX_ITERATIONS = 3
    iteration = 0

    while iteration < MAX_ITERATIONS:
        payload = {
            "model": "deepseek-chat",
            "messages": messages_payload,
            "temperature": req.temperature, # 🚩 Inyectado: Usamos el valor de la BD, no hardcodeado
            "max_tokens": 1500,
        }
        
        # Solo inyectamos "tools" si la lista no está vacía
        if active_tools:
            payload["tools"] = active_tools

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(DEEPSEEK_API_URL, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()

            ia_message = data["choices"][0]["message"]
            finish_reason = data["choices"][0]["finish_reason"]

            if finish_reason == "tool_calls":
                messages_payload.append(ia_message) 

                for tool_call in ia_message.get("tool_calls", []):
                    function_name = tool_call["function"]["name"]
                    arguments = json.loads(tool_call["function"]["arguments"])

                    # 🚩 ENRUTADOR DINÁMICO DE HERRAMIENTAS
                    if function_name == "consultar_inventario_erp":
                        id_articulo = arguments.get("id_articulo")
                        erp_url = req.tenant_config.get("erp_url") 
                        
                        print(f"🔥 Ejecutando ERP Tenant -> URL: {erp_url} | Art: {id_articulo}")
                        
                        tool_result = await consultar_inventario_erp(id_articulo, erp_url)
                        
                        messages_payload.append({
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "name": function_name,
                            "content": tool_result
                        })
                
                iteration += 1
                continue 

            else:
                # 🚩 Inyectado: Captura de métricas financieras de la API de DeepSeek
                usage = data.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)

                return {
                    "success": True,
                    "user_id": req.user_id,
                    "respuesta": ia_message.get("content", "").strip(),
                    "prompt_tokens": prompt_tokens,         # Viaja a Node.js
                    "completion_tokens": completion_tokens  # Viaja a Node.js
                }

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Fallo del motor: {str(e)}")

    raise HTTPException(status_code=500, detail="Bucle infinito de herramientas.")