"""
Smoke tests — el microservicio levanta y expone lo mínimo esperado.
No mockean DeepSeek ni el ERP: solo verifican que la app y sus rutas existen.
"""
import pytest


class TestAppArranca:
    @pytest.mark.asyncio
    async def test_openapi_disponible_y_contiene_el_endpoint_principal(self, client):
        resp = await client.get("/openapi.json")
        assert resp.status_code == 200
        assert "/api/ia/process" in resp.json()["paths"]

    @pytest.mark.asyncio
    async def test_docs_disponible(self, client):
        resp = await client.get("/docs")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_titulo_de_la_app_es_el_esperado(self, main_module):
        assert main_module.app.title == "Agente X - Motor IA (Stateless Worker)"


class TestRutaPrincipalAccesible:
    @pytest.mark.asyncio
    async def test_post_sin_body_devuelve_422(self, client):
        resp = await client.post("/api/ia/process")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_post_con_body_invalido_devuelve_422(self, client):
        resp = await client.post("/api/ia/process", json={"tenant_id": 1})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_get_no_permitido_en_la_ruta_de_proceso(self, client):
        resp = await client.get("/api/ia/process")
        assert resp.status_code == 405

    @pytest.mark.asyncio
    async def test_ruta_desconocida_devuelve_404(self, client):
        resp = await client.get("/ruta-que-no-existe")
        assert resp.status_code == 404
