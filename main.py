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

# =============================================================================
# CONFIGURACIÓN
# =============================================================================
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

# =============================================================================
# CONTRATO NODE <-> PYTHON
# =============================================================================
class ChatRequest(BaseModel):
    tenant_id:     int
    user_message:  str
    system_prompt: str
    temperature:   float = 0.3
    erp_url:       Optional[str]            = None
    erp_mapping:   Optional[Dict[str, str]] = None
    allowed_tools: Optional[List[str]]      = []
    history:       Optional[List[Dict[str, Any]]] = []

# =============================================================================
# LÓGICA CENTRAL
# =============================================================================
@app.post("/api/ia/process")
async def process_chat(req: ChatRequest):
    if not req.user_message.strip():
        raise HTTPException(status_code=400, detail="El mensaje del usuario está vacío.")

    # ── Construcción del payload inicial ─────────────────────────────────────
    messages_payload: List[Dict[str, Any]] = [
        {"role": "system", "content": req.system_prompt}
    ]

    if req.history:
        messages_payload.extend(req.history)

    messages_payload.append({"role": "user", "content": req.user_message})

    # ── Catálogo de herramientas activas para este tenant ────────────────────
    active_tools = [
        tool for tool in tools_manifest
        if tool["function"]["name"] in (req.allowed_tools or [])
    ]

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type":  "application/json",
    }

    MAX_ITERATIONS   = 3
    # Cuántos mensajes (sin contar system) preservar cuando el contexto crece.
    # system + historial ya llegan recortados desde Node, pero las tool_calls
    # internas del loop pueden inflar el array. Esto lo contiene.
    MAX_CONTEXT_MSGS = 12
    iteration        = 0
    used_tools       = False

    while iteration < MAX_ITERATIONS:

        # ── FIX: Temperatura dual ────────────────────────────────────────────
        # Cuando hay herramientas activas y el LLM está EXTRAYENDO parámetros
        # (decidiendo qué mandar al ERP), usamos temperatura 0.0 para eliminar
        # la creatividad en esa decisión mecánica.
        # Cuando ya no hay tool_calls pendientes (redacción final), usamos la
        # temperatura configurada por la empresa en BD.
        temperatura_turno = 0.0 if active_tools else req.temperature

        # ── FIX: Ventana de contexto interno ────────────────────────────────
        # El loop puede acumular rondas de tool_calls. Preservamos el system
        # prompt y cortamos el resto a MAX_CONTEXT_MSGS para evitar que el
        # LLM "vea" resultados de ERP de iteraciones anteriores como frescos.
        if len(messages_payload) > MAX_CONTEXT_MSGS + 1:
            system_msg      = messages_payload[0]
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

            # ── El LLM quiere usar una herramienta ──────────────────────────
            if finish_reason == "tool_calls":
                used_tools = True
                messages_payload.append(ia_message)

                for tool_call in ia_message.get("tool_calls", []):
                    function_name = tool_call["function"]["name"]
                    arguments     = json.loads(tool_call["function"]["arguments"])

                    tool_result = "SISTEMA: Herramienta no reconocida."

                    if function_name == "consultar_inventario_erp":
                        t_filtro  = arguments.get("tipo_filtro")
                        v_busqueda = arguments.get("valor_busqueda")
                        c_refinada = arguments.get("categoria_refinada")

                        print(
                            f"🔥 ERP Tenant {req.tenant_id} → "
                            f"Filtro: {t_filtro} | Valor: {v_busqueda} | "
                            f"Cat: {c_refinada} | Temp: {temperatura_turno}"
                        )

                        tool_result = await consultar_inventario_erp(
                            tipo_filtro=t_filtro,
                            valor_busqueda=v_busqueda,
                            erp_url=req.erp_url,
                            erp_mapping=req.erp_mapping,
                            categoria_refinada=c_refinada,
                        )

                    messages_payload.append({
                        "role":        "tool",
                        "tool_call_id": tool_call["id"],
                        "name":        function_name,
                        "content":     tool_result,
                    })

                iteration += 1
                continue

            # ── Respuesta final del LLM (sin tool_calls) ────────────────────
            else:
                usage = data.get("usage", {})
                return {
                    "success":           True,
                    "tenant_id":         req.tenant_id,
                    "reply":             ia_message.get("content", "").strip(),
                    "prompt_tokens":     usage.get("prompt_tokens",     0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    # Métricas de trazabilidad para el _debug del controller
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

    # Si llegamos aquí, el LLM no terminó en MAX_ITERATIONS rondas de tools
    raise HTTPException(
        status_code=500,
        detail="Límite de iteraciones de herramientas alcanzado. Abortando para evitar bucle infinito."
    )