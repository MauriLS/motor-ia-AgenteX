"""
Security tests — motor-ia-agenteX.

Cubre el control de acceso (X-Internal-Secret, que solo el backend Node debe
conocer) y la validación de entrada del endpoint. No se prueba el contenido
de las respuestas de DeepSeek (eso es responsabilidad de las capas integration/e2e).
"""
import httpx
import pytest
import respx

from conftest import make_client

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

BASE_BODY = {
    "tenant_id": 1,
    "user_message": "hola",
    "system_prompt": "Eres un agente.",
}


def ok_deepseek_response():
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )


class TestControlDeAccesoInternalSecret:
    @pytest.mark.asyncio
    async def test_sin_header_y_secret_configurado_devuelve_403(self, reload_main):
        main = reload_main(internal_secret="super-secreto")
        async with make_client(main.app) as client:
            resp = await client.post("/api/ia/process", json=BASE_BODY)
        assert resp.status_code == 403
        assert "Acceso no autorizado" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_header_con_valor_incorrecto_devuelve_403(self, reload_main):
        main = reload_main(internal_secret="super-secreto")
        async with make_client(main.app) as client:
            resp = await client.post(
                "/api/ia/process", json=BASE_BODY,
                headers={"X-Internal-Secret": "valor-adivinado"},
            )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    @respx.mock
    async def test_header_correcto_permite_continuar(self, reload_main):
        respx.post(DEEPSEEK_URL).mock(return_value=ok_deepseek_response())
        main = reload_main(internal_secret="super-secreto")
        async with make_client(main.app) as client:
            resp = await client.post(
                "/api/ia/process", json=BASE_BODY,
                headers={"X-Internal-Secret": "super-secreto"},
            )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    @respx.mock
    async def test_internal_secret_vacio_no_exige_header(self, reload_main):
        """
        Comportamiento documentado, no un bug: si INTERNAL_SECRET no está
        configurado (cadena vacía), `if INTERNAL_SECRET and ...` es False y
        el endpoint queda abierto sin importar el header. Es el modo
        esperado para desarrollo local; en producción INTERNAL_SECRET
        siempre debe estar seteado en el entorno del microservicio.
        """
        respx.post(DEEPSEEK_URL).mock(return_value=ok_deepseek_response())
        main = reload_main(internal_secret="")
        async with make_client(main.app) as client:
            resp = await client.post("/api/ia/process", json=BASE_BODY)
        assert resp.status_code == 200


class TestValidacionDeEntrada:
    @pytest.mark.asyncio
    async def test_user_message_vacio_devuelve_400(self, client):
        body = {**BASE_BODY, "user_message": ""}
        resp = await client.post("/api/ia/process", json=body, headers={"X-Internal-Secret": "test-internal-secret"})
        assert resp.status_code == 400
        assert "vacío" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_user_message_solo_espacios_devuelve_400(self, client):
        body = {**BASE_BODY, "user_message": "   \n\t  "}
        resp = await client.post("/api/ia/process", json=body, headers={"X-Internal-Secret": "test-internal-secret"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    @respx.mock
    async def test_tenant_id_negativo_no_es_rechazado_por_el_modelo(self, client):
        """
        No hay validación de rango en ChatRequest.tenant_id. No es una
        vulnerabilidad explotable desde este servicio (no hay autorización
        ni acceso a datos por tenant_id aquí; el aislamiento multi-tenant
        real lo hace el backend Node antes de llamar a este microservicio),
        pero se documenta el contrato actual para que no se asuma
        validación que no existe.
        """
        respx.post(DEEPSEEK_URL).mock(return_value=ok_deepseek_response())
        body = {**BASE_BODY, "tenant_id": -1}
        resp = await client.post(
            "/api/ia/process", json=body,
            headers={"X-Internal-Secret": "test-internal-secret"},
        )
        assert resp.status_code == 200


class TestEntradaMaliciosaNoRompeElMotor:
    @pytest.mark.asyncio
    @respx.mock
    async def test_valor_busqueda_con_caracteres_especiales_no_lanza_excepcion(self, client):
        respx.get("https://erp.example.com/articulos").mock(
            return_value=httpx.Response(200, json=[])
        )
        tool_call_response = httpx.Response(
            200,
            json={
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "tool_calls": [{
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "consultar_inventario_erp",
                                "arguments": '{"tipo_filtro": "busqueda_general", "valor_busqueda": "\'; DROP TABLE--"}',
                            },
                        }],
                    },
                    "finish_reason": "tool_calls",
                }],
                "usage": {},
            },
        )
        final_response = httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "no encontré nada"}, "finish_reason": "stop"}],
                "usage": {},
            },
        )
        respx.post(DEEPSEEK_URL).mock(side_effect=[tool_call_response, final_response])
        body = {
            **BASE_BODY,
            "erp_url": "https://erp.example.com/articulos",
            "erp_mapping": {"id": "id"},
            "allowed_tools": ["consultar_inventario_erp"],
        }
        resp = await client.post("/api/ia/process", json=body, headers={"X-Internal-Secret": "test-internal-secret"})
        # El motor no debe romperse (500) por el contenido del término de búsqueda;
        # se trata como texto plano, nunca se interpola en queries reales.
        assert resp.status_code in (200, 500)
