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
# EL CONTRATO ESTRICTO NODE <-> PYTHON
# =========================
class ChatRequest(BaseModel):
    tenant_id: int
    user_message: str
    system_prompt: str 
    temperature: float = 0.3
    erp_url: Optional[str] = None
    erp_mapping: Optional[Dict[str, str]] = None # 🚩 Aceptamos el diccionario
    allowed_tools: Optional[List[str]] = []
    history: Optional[List[Dict[str, Any]]] = []

# =========================
# LÓGICA CENTRAL
# =========================
@app.post("/api/ia/process")
async def process_chat(req: ChatRequest):
    if not req.user_message.strip():
        raise HTTPException(status_code=400, detail="El mensaje del usuario está vacío.")

    # 1. Inyectamos el cerebro del Agente B2B
    messages_payload = [{"role": "system", "content": req.system_prompt}]
    
    if req.history:
        messages_payload.extend(req.history)
        
    messages_payload.append({"role": "user", "content": req.user_message})

    # 2. Filtrado de Catálogo de Herramientas
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
            "temperature": req.temperature,
            "max_tokens": 1500,
        }
        
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
                        # Extraemos los NUEVOS parámetros que generó la IA
                        t_filtro = arguments.get("tipo_filtro")
                        v_busqueda = arguments.get("valor_busqueda")
                        c_refinada = arguments.get("categoria_refinada")
                        
                        print(f"🔥 ERP Tenant -> URL: {req.erp_url} | Filtro: {t_filtro} | Valor: {v_busqueda} | Cat: {c_refinada}")
                        
                        # Ejecutamos la función inyectando el mapeo de este cliente específico
                        tool_result = await consultar_inventario_erp(
                            tipo_filtro=t_filtro, 
                            valor_busqueda=v_busqueda, 
                            erp_url=req.erp_url, 
                            erp_mapping=req.erp_mapping, 
                            categoria_refinada=c_refinada
                        )
                        
                        messages_payload.append({
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "name": function_name,
                            "content": tool_result
                        })
                
                iteration += 1
                continue 

            else:
                usage = data.get("usage", {})
                return {
                    "success": True,
                    "tenant_id": req.tenant_id,
                    "reply": ia_message.get("content", "").strip(),
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0)
                }

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Fallo del motor: {str(e)}")

    raise HTTPException(status_code=500, detail="Bucle infinito de herramientas detectado. Abortando.")