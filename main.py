# motor-ia-AgenteX/main.py
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
import json
from dotenv import load_dotenv

from tools import tools_manifest, consultar_inventario_erp

load_dotenv()

DEEPSEEK_API_KEY  = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL  = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
INTERNAL_SECRET   = os.getenv("INTERNAL_SECRET", "")

app = FastAPI(title="Agente X - Motor IA (Stateless Worker)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    tenant_id:     int
    user_message:  str
    system_prompt: str
    temperature:   float = 0.3
    erp_url:       Optional[str]            = None
    erp_mapping:   Optional[Dict[str, str]] = None
    allowed_tools: Optional[List[str]]      = []
    history:       Optional[List[Dict[str, Any]]] = []

@app.post("/api/ia/process")
async def process_chat(
    req: ChatRequest,
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret"),
):
    # ── Validación del secret compartido ─────────────────────────────────────
    # Solo Node.js debe poder llamar a este endpoint.
    # Si INTERNAL_SECRET está configurado, rechazamos cualquier request sin él.
    if INTERNAL_SECRET and x_internal_secret != INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Acceso no autorizado al motor IA.")

    if not req.user_message.strip():
        raise HTTPException(status_code=400, detail="El mensaje del usuario está vacío.")

    messages_payload: List[Dict[str, Any]] = [
        {"role": "system", "content": req.system_prompt}
    ]

    if req.history:
        messages_payload.extend(req.history)

    messages_payload.append({"role": "user", "content": req.user_message})

    active_tools = [
        tool for tool in tools_manifest
        if tool["function"]["name"] in (req.allowed_tools or [])
    ]

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type":  "application/json",
    }

    MAX_ITERATIONS   = 3
    MAX_CONTEXT_MSGS = 12
    iteration        = 0
    used_tools       = False

    while iteration < MAX_ITERATIONS:
        temperatura_turno = 0.0 if active_tools else req.temperature

        if len(messages_payload) > MAX_CONTEXT_MSGS + 1:
            system_msg       = messages_payload[0]
            messages_payload = [system_msg] + messages_payload[-MAX_CONTEXT_MSGS:]

        payload: Dict[str, Any] = {
            "model":       "deepseek-chat",
            "messages":    messages_payload,
            "temperature": temperatura_turno,
            "max_tokens":  1500,
        }

        if active_tools:
            payload["tools"] = active_tools

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(DEEPSEEK_API_URL, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()

            ia_message    = data["choices"][0]["message"]
            finish_reason = data["choices"][0]["finish_reason"]

            if finish_reason == "tool_calls":
                used_tools = True
                messages_payload.append(ia_message)

                for tool_call in ia_message.get("tool_calls", []):
                    function_name = tool_call["function"]["name"]
                    arguments     = json.loads(tool_call["function"]["arguments"])
                    tool_result   = "SISTEMA: Herramienta no reconocida."

                    if function_name == "consultar_inventario_erp":
                        tool_result = await consultar_inventario_erp(
                            tipo_filtro=arguments.get("tipo_filtro"),
                            valor_busqueda=arguments.get("valor_busqueda"),
                            erp_url=req.erp_url,
                            erp_mapping=req.erp_mapping,
                            categoria_refinada=arguments.get("categoria_refinada"),
                        )

                    messages_payload.append({
                        "role":         "tool",
                        "tool_call_id": tool_call["id"],
                        "name":         function_name,
                        "content":      tool_result,
                    })

                iteration += 1
                continue

            else:
                usage = data.get("usage", {})
                return {
                    "success":           True,
                    "tenant_id":         req.tenant_id,
                    "reply":             ia_message.get("content", "").strip(),
                    "prompt_tokens":     usage.get("prompt_tokens",     0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "tool_iterations":   iteration,
                    "used_tools":        used_tools,
                }

        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=502,
                detail=f"DeepSeek devolvió error {e.response.status_code}: {e.response.text}"
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Fallo del motor: {str(e)}")

    raise HTTPException(
        status_code=500,
        detail="Límite de iteraciones de herramientas alcanzado."
    )