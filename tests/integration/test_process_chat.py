"""
Integration tests para POST /api/ia/process.

Se mockea con respx tanto la API de DeepSeek (DEEPSEEK_API_URL) como el ERP
(la URL que viaja en erp_url dentro del body), pero se ejercita la app FastAPI
real vía ASGITransport — la cadena completa request -> validación -> loop de
tools -> DeepSeek -> respuesta se prueba de punta a punta sin red real.
"""
import json

import httpx
import pytest
import respx

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
ERP_URL = "https://erp.example.com/articulos"

BASE_BODY = {
    "tenant_id": 1,
    "user_message": "hola, ¿qué tal?",
    "system_prompt": "Eres un agente de soporte B2B.",
}

HEADERS = {"X-Internal-Secret": "test-internal-secret"}


def deepseek_response(content=None, tool_calls=None, finish_reason="stop", usage=None):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return httpx.Response(
        200,
        json={
            "choices": [{"message": message, "finish_reason": finish_reason}],
            "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


def tool_call(call_id="call_1", name="consultar_inventario_erp", arguments=None):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments or {})},
    }


class TestRespuestaSimpleSinTools:
    @pytest.mark.asyncio
    @respx.mock
    async def test_respuesta_directa_sin_tool_calls(self, client):
        respx.post(DEEPSEEK_URL).mock(
            return_value=deepseek_response(content="¡Hola! ¿En qué te ayudo?")
        )
        resp = await client.post("/api/ia/process", json=BASE_BODY, headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["reply"] == "¡Hola! ¿En qué te ayudo?"
        assert data["used_tools"] is False
        assert data["tool_iterations"] == 0
        assert data["prompt_tokens"] == 10
        assert data["completion_tokens"] == 5

    @pytest.mark.asyncio
    @respx.mock
    async def test_temperature_se_envia_tal_cual_cuando_no_hay_tools_activas(self, client):
        route = respx.post(DEEPSEEK_URL).mock(
            return_value=deepseek_response(content="ok")
        )
        body = {**BASE_BODY, "temperature": 0.9}
        await client.post("/api/ia/process", json=body, headers=HEADERS)
        payload_enviado = json.loads(route.calls.last.request.content)
        assert payload_enviado["temperature"] == 0.9
        assert "tools" not in payload_enviado


class TestFlujoConToolCalls:
    @pytest.mark.asyncio
    @respx.mock
    async def test_tool_call_consulta_erp_y_responde_en_segundo_turno(self, client):
        respx.get(ERP_URL).mock(
            return_value=httpx.Response(200, json=[
                {"id": "1", "sku": "X1", "articulo": "Cadena reforzada",
                 "precio_tienda": 8000, "stock_min": 50, "categoria": "Transmisión"},
            ])
        )
        deepseek_route = respx.post(DEEPSEEK_URL).mock(
            side_effect=[
                deepseek_response(
                    tool_calls=[tool_call(arguments={
                        "tipo_filtro": "busqueda_general", "valor_busqueda": "cadena",
                    })],
                    finish_reason="tool_calls",
                ),
                deepseek_response(content="Tenemos Cadena reforzada disponible."),
            ]
        )
        body = {
            **BASE_BODY,
            "erp_url": ERP_URL,
            "erp_mapping": {"id": "id", "sku": "sku", "nombre": "articulo",
                             "precio": "precio_tienda", "stock": "stock_min",
                             "categoria": "categoria"},
            "allowed_tools": ["consultar_inventario_erp"],
        }
        resp = await client.post("/api/ia/process", json=body, headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["used_tools"] is True
        assert data["tool_iterations"] == 1
        assert "Cadena reforzada" in data["reply"]
        assert deepseek_route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_temperatura_se_fuerza_a_cero_cuando_hay_tools_activas(self, client):
        respx.get(ERP_URL).mock(return_value=httpx.Response(200, json=[]))
        route = respx.post(DEEPSEEK_URL).mock(
            side_effect=[
                deepseek_response(content="sin resultados"),
            ]
        )
        body = {
            **BASE_BODY,
            "temperature": 0.9,
            "erp_url": ERP_URL,
            "erp_mapping": {"id": "id"},
            "allowed_tools": ["consultar_inventario_erp"],
        }
        await client.post("/api/ia/process", json=body, headers=HEADERS)
        payload_enviado = json.loads(route.calls.last.request.content)
        assert payload_enviado["temperature"] == 0.0
        assert payload_enviado["tools"][0]["function"]["name"] == "consultar_inventario_erp"

    @pytest.mark.asyncio
    @respx.mock
    async def test_tool_call_con_nombre_no_reconocido(self, client):
        deepseek_route = respx.post(DEEPSEEK_URL).mock(
            side_effect=[
                deepseek_response(
                    tool_calls=[tool_call(name="tool_inexistente", arguments={})],
                    finish_reason="tool_calls",
                ),
                deepseek_response(content="No pude usar esa herramienta."),
            ]
        )
        body = {**BASE_BODY, "allowed_tools": ["tool_inexistente"]}
        resp = await client.post("/api/ia/process", json=body, headers=HEADERS)
        assert resp.status_code == 200
        # El segundo request a DeepSeek debe llevar el resultado "no reconocida" como tool message.
        segundo_payload = json.loads(deepseek_route.calls[1].request.content)
        tool_msg = [m for m in segundo_payload["messages"] if m.get("role") == "tool"][0]
        assert "no reconocida" in tool_msg["content"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_limite_de_iteraciones_devuelve_500(self, client):
        respx.get(ERP_URL).mock(return_value=httpx.Response(200, json=[]))
        respx.post(DEEPSEEK_URL).mock(
            return_value=deepseek_response(
                tool_calls=[tool_call(arguments={
                    "tipo_filtro": "busqueda_general", "valor_busqueda": "x",
                })],
                finish_reason="tool_calls",
            )
        )
        body = {
            **BASE_BODY,
            "erp_url": ERP_URL,
            "erp_mapping": {"id": "id"},
            "allowed_tools": ["consultar_inventario_erp"],
        }
        resp = await client.post("/api/ia/process", json=body, headers=HEADERS)
        assert resp.status_code == 500
        assert "Límite de iteraciones" in resp.json()["detail"]


class TestErroresDeepSeek:
    @pytest.mark.asyncio
    @respx.mock
    async def test_deepseek_error_http_devuelve_502(self, client):
        respx.post(DEEPSEEK_URL).mock(return_value=httpx.Response(500, text="boom"))
        resp = await client.post("/api/ia/process", json=BASE_BODY, headers=HEADERS)
        assert resp.status_code == 502
        assert "DeepSeek devolvió error 500" in resp.json()["detail"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_excepcion_generica_devuelve_500(self, client):
        # Respuesta 200 sin "choices" -> KeyError dentro del try -> 500 "Fallo del motor".
        respx.post(DEEPSEEK_URL).mock(return_value=httpx.Response(200, json={}))
        resp = await client.post("/api/ia/process", json=BASE_BODY, headers=HEADERS)
        assert resp.status_code == 500
        assert "Fallo del motor" in resp.json()["detail"]


class TestRecorteDeContexto:
    @pytest.mark.asyncio
    @respx.mock
    async def test_historial_largo_se_recorta_preservando_el_system_prompt(self, client):
        route = respx.post(DEEPSEEK_URL).mock(
            return_value=deepseek_response(content="ok")
        )
        historial_largo = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg-{i}"}
            for i in range(20)
        ]
        body = {**BASE_BODY, "history": historial_largo}
        await client.post("/api/ia/process", json=body, headers=HEADERS)
        payload_enviado = json.loads(route.calls.last.request.content)
        # MAX_CONTEXT_MSGS=12 -> el system prompt + 12 mensajes finales = 13.
        assert len(payload_enviado["messages"]) == 13
        assert payload_enviado["messages"][0]["role"] == "system"
        assert payload_enviado["messages"][-1]["content"] == BASE_BODY["user_message"]
