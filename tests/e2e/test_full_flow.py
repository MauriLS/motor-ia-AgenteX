"""
E2E — simula un viaje de usuario real a través de DOS turnos de conversación
(dos requests HTTP secuenciales a /api/ia/process, como lo haría el backend
Node reenviando el historial real). A diferencia de integration/ (que prueba
un único request y una rama puntual), esto valida que el contrato entre
turnos —history ida y vuelta, refinamiento por categoría— funciona de punta
a punta contra la app ASGI real.

DeepSeek y el ERP siguen mockeados (no hay backend Node ni red real
disponible en este repo), igual que el resto de las capas.
"""
import json

import httpx
import pytest
import respx

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
ERP_URL = "https://erp.example.com/articulos"
HEADERS = {"X-Internal-Secret": "test-internal-secret"}

SYSTEM_PROMPT = "Eres el agente de soporte B2B de una tienda de repuestos de bicicleta."

ERP_MAPPING = {
    "id": "id", "sku": "sku", "nombre": "articulo",
    "precio": "precio_tienda", "stock": "stock_min", "categoria": "categoria",
}


def correas_amplias():
    categorias = ["Carretera", "Montaña", "Urbana"]
    return [
        {"id": str(i), "sku": f"COR-{i}", "articulo": f"Correa modelo {i}",
         "precio_tienda": 10000 + i, "stock_min": 20, "categoria": categorias[i % 3]}
        for i in range(25)
    ]


def correas_carretera():
    return [
        {"id": "1", "sku": "COR-1", "articulo": "Correa modelo 1",
         "precio_tienda": 10001, "stock_min": 20, "categoria": "Carretera"},
        {"id": "4", "sku": "COR-4", "articulo": "Correa modelo 4",
         "precio_tienda": 10004, "stock_min": 5, "categoria": "Carretera"},
    ]


def deepseek_json(content=None, tool_calls=None, finish_reason="stop"):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return httpx.Response(
        200,
        json={
            "choices": [{"message": message, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
        },
    )


def make_tool_call(call_id, arguments):
    return [{
        "id": call_id,
        "type": "function",
        "function": {"name": "consultar_inventario_erp", "arguments": json.dumps(arguments)},
    }]


class TestFlujoBusquedaConRefinamientoPorCategoria:
    @pytest.mark.asyncio
    @respx.mock
    async def test_turno1_demasiados_resultados_turno2_refinado_por_categoria(self, client):
        # ---- Turno 1: el usuario pide "correas", el ERP tiene 25 en 3 categorías ----
        erp_route = respx.get(ERP_URL).mock(
            return_value=httpx.Response(200, json=correas_amplias())
        )
        respx.post(DEEPSEEK_URL).mock(
            side_effect=[
                deepseek_json(
                    tool_calls=make_tool_call("call_1", {
                        "tipo_filtro": "busqueda_general", "valor_busqueda": "correa",
                    }),
                    finish_reason="tool_calls",
                ),
                deepseek_json(
                    content="Tengo 25 correas. ¿Buscas Carretera, Montaña o Urbana?"
                ),
            ]
        )
        turno1_body = {
            "tenant_id": 1,
            "user_message": "qué correas tienen",
            "system_prompt": SYSTEM_PROMPT,
            "erp_url": ERP_URL,
            "erp_mapping": ERP_MAPPING,
            "allowed_tools": ["consultar_inventario_erp"],
            "history": [],
        }
        resp1 = await client.post("/api/ia/process", json=turno1_body, headers=HEADERS)
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert "Carretera" in data1["reply"]

        # El backend Node reconstruiría el historial con lo que pasó en el turno 1.
        history_turno2 = [
            {"role": "user", "content": turno1_body["user_message"]},
            {"role": "assistant", "content": data1["reply"]},
        ]

        # ---- Turno 2: el usuario elige "Carretera", ahora el ERP filtra a 2 items ----
        erp_route.side_effect = None
        erp_route.mock(return_value=httpx.Response(200, json=correas_carretera()))
        respx.post(DEEPSEEK_URL).mock(
            side_effect=[
                deepseek_json(
                    tool_calls=make_tool_call("call_2", {
                        "tipo_filtro": "busqueda_general", "valor_busqueda": "correa",
                        "categoria_refinada": "Carretera",
                    }),
                    finish_reason="tool_calls",
                ),
                deepseek_json(
                    content="Encontré 2 correas de Carretera: modelo 1 y modelo 4."
                ),
            ]
        )
        turno2_body = {
            "tenant_id": 1,
            "user_message": "Carretera",
            "system_prompt": SYSTEM_PROMPT,
            "erp_url": ERP_URL,
            "erp_mapping": ERP_MAPPING,
            "allowed_tools": ["consultar_inventario_erp"],
            "history": history_turno2,
        }
        resp2 = await client.post("/api/ia/process", json=turno2_body, headers=HEADERS)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert "modelo 1" in data2["reply"]
        assert data2["used_tools"] is True


class TestFlujoStockCriticoDeFinAFin:
    @pytest.mark.asyncio
    @respx.mock
    async def test_usuario_pregunta_por_stock_critico_y_recibe_lista_real(self, client):
        respx.get(ERP_URL).mock(
            return_value=httpx.Response(200, json=[
                {"id": "1", "sku": "A1", "articulo": "Cámara 26", "precio_tienda": 3000, "stock_min": 1, "categoria": "Cámaras"},
                {"id": "2", "sku": "A2", "articulo": "Cámara 29", "precio_tienda": 3500, "stock_min": 50, "categoria": "Cámaras"},
            ])
        )
        respx.post(DEEPSEEK_URL).mock(
            side_effect=[
                deepseek_json(
                    tool_calls=make_tool_call("call_1", {
                        "tipo_filtro": "stock_critico", "valor_busqueda": "ALL",
                    }),
                    finish_reason="tool_calls",
                ),
                deepseek_json(content="Solo la Cámara 26 tiene stock crítico (1 unidad)."),
            ]
        )
        body = {
            "tenant_id": 5,
            "user_message": "qué productos tienen stock crítico",
            "system_prompt": SYSTEM_PROMPT,
            "erp_url": ERP_URL,
            "erp_mapping": ERP_MAPPING,
            "allowed_tools": ["consultar_inventario_erp"],
        }
        resp = await client.post("/api/ia/process", json=body, headers=HEADERS)
        assert resp.status_code == 200
        assert "Cámara 26" in resp.json()["reply"]
        assert "Cámara 29" not in resp.json()["reply"]
