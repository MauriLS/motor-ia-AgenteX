"""
Stub local de DeepSeek + ERP para la prueba de carga k6 del microservicio.

DEEPSEEK_API_URL es configurable por entorno (ver main.py). Este stub levanta
un servidor FastAPI/uvicorn separado que imita las dos únicas dependencias
externas reales del motor:

- POST /v1/chat/completions  -> misma forma de respuesta que la API de DeepSeek
- GET  /erp/articulos        -> mismo formato de lista plana que un ERP real

Así el k6 mide la capacidad real del worker FastAPI (validación, loop de
tools, manejo de errores, serialización) sin gastar tokens reales de DeepSeek
ni depender de la disponibilidad de un ERP de terceros.
"""
import json

from fastapi import FastAPI, Request

app = FastAPI(title="Stub DeepSeek + ERP (solo para carga k6)")

ARTICULOS = [
    {"id": str(i), "sku": f"SKU-{i}", "articulo": f"Producto de carga {i}",
     "precio_tienda": 1000 + i, "stock_min": 10, "categoria": "CargaK6"}
    for i in range(15)
]


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """
    Imita la decisión de DeepSeek de usar (o no) la tool:
    - Si el payload trae "tools" y aún no hay un mensaje "role: tool" en el
      historial, responde con un tool_call a consultar_inventario_erp
      (ejercita la llamada real al stub de ERP bajo carga).
    - Si ya hay un mensaje "role: tool", responde con la respuesta final.
    - Si no hay tools activas, responde directo.
    """
    body = await request.json()
    mensajes = body.get("messages", [])
    ya_uso_tool = any(m.get("role") == "tool" for m in mensajes)

    if body.get("tools") and not ya_uso_tool:
        message = {
            "role": "assistant",
            "tool_calls": [{
                "id": "call_k6",
                "type": "function",
                "function": {
                    "name": "consultar_inventario_erp",
                    "arguments": json.dumps({
                        "tipo_filtro": "stock_critico", "valor_busqueda": "ALL",
                    }),
                },
            }],
        }
        finish_reason = "tool_calls"
    else:
        message = {"role": "assistant", "content": "Respuesta simulada del stub de carga."}
        finish_reason = "stop"

    return {
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 20},
    }


@app.get("/erp/articulos")
async def erp_articulos():
    return ARTICULOS
