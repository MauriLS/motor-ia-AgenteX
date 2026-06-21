"""
Unit tests para tools.py — motor de búsqueda del ERP (consultar_inventario_erp).

Estrategia: la función hace una sola llamada httpx.AsyncClient.get(erp_url) y
el resto es lógica pura de filtrado/orden en memoria. Se mockea esa llamada
con respx y se ejercitan las ramas de la lógica de filtrado directamente.
"""
import httpx
import pytest
import respx

from tools import consultar_inventario_erp, tools_manifest

ERP_URL = "https://erp.example.com/articulos"

MAPPING = {
    "id": "id",
    "sku": "sku",
    "nombre": "articulo",
    "precio": "precio_tienda",
    "stock": "stock_min",
    "categoria": "categoria",
}

ARTICULOS_BASE = [
    {"id": "1", "sku": "COR-29210", "articulo": "Correa 29x2.10", "precio_tienda": 15000, "stock_min": 10, "categoria": "Correas"},
    {"id": "2", "sku": "COR-29125", "articulo": "Correa 29x2.125", "precio_tienda": 16000, "stock_min": 2, "categoria": "Correas"},
    {"id": "3", "sku": "NEU-700", "articulo": "Neumático 700c", "precio_tienda": 25000, "stock_min": 0, "categoria": "Neumáticos"},
    {"id": "4", "sku": "CAD-001", "articulo": "Cadena reforzada", "precio_tienda": 8000, "stock_min": 50, "categoria": "Transmisión"},
]


def mock_erp(articulos=ARTICULOS_BASE, status_code=200):
    respx.get(ERP_URL).mock(
        return_value=httpx.Response(status_code, json=articulos)
    )


class TestManifest:
    def test_manifest_define_la_unica_tool_esperada(self):
        nombres = [t["function"]["name"] for t in tools_manifest]
        assert nombres == ["consultar_inventario_erp"]

    def test_manifest_requiere_tipo_filtro_y_valor_busqueda(self):
        params = tools_manifest[0]["function"]["parameters"]
        assert set(params["required"]) == {"tipo_filtro", "valor_busqueda"}


class TestConfiguracionFaltante:
    @pytest.mark.asyncio
    async def test_sin_erp_url_devuelve_mensaje_sistema(self):
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="correa",
            erp_url=None, erp_mapping=MAPPING,
        )
        assert "URL del ERP no configurada" in resultado

    @pytest.mark.asyncio
    async def test_sin_erp_mapping_devuelve_mensaje_sistema(self):
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="correa",
            erp_url=ERP_URL, erp_mapping=None,
        )
        assert "Falta el diccionario de mapeo" in resultado

    @pytest.mark.asyncio
    async def test_erp_mapping_vacio_se_trata_como_faltante(self):
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="correa",
            erp_url=ERP_URL, erp_mapping={},
        )
        assert "Falta el diccionario de mapeo" in resultado


class TestFalloConexionERP:
    @pytest.mark.asyncio
    @respx.mock
    async def test_status_distinto_200_devuelve_mensaje_de_fallo(self):
        respx.get(ERP_URL).mock(return_value=httpx.Response(503))
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="correa",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        assert "Fallo de conexión ERP" in resultado
        assert "503" in resultado

    @pytest.mark.asyncio
    @respx.mock
    async def test_excepcion_en_prefiltro_es_capturada(self):
        # JSON inválido -> response.json() lanza excepción dentro del try/except.
        respx.get(ERP_URL).mock(
            return_value=httpx.Response(200, content=b"no-es-json")
        )
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="correa",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        assert "Fallo de ejecución en el pre-filtro" in resultado


class TestConteoTotal:
    @pytest.mark.asyncio
    @respx.mock
    async def test_conteo_total_devuelve_cantidad_de_articulos(self):
        mock_erp()
        resultado = await consultar_inventario_erp(
            tipo_filtro="conteo_total", valor_busqueda="ALL",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        assert f"{len(ARTICULOS_BASE)} artículos en total" in resultado


class TestBusquedaPorTexto:
    @pytest.mark.asyncio
    @respx.mock
    async def test_match_por_nombre_busqueda_general(self):
        mock_erp()
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="cadena",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        assert "Cadena reforzada" in resultado
        assert "Neumático" not in resultado

    @pytest.mark.asyncio
    @respx.mock
    async def test_match_por_sku_exacto(self):
        mock_erp()
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="NEU-700",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        assert "Neumático 700c" in resultado

    @pytest.mark.asyncio
    @respx.mock
    async def test_match_por_id_exacto(self):
        mock_erp()
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="4",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        assert "Cadena reforzada" in resultado

    @pytest.mark.asyncio
    @respx.mock
    async def test_sin_resultados_devuelve_mensaje_anti_alucinacion(self):
        mock_erp()
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="producto-inexistente-xyz",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        assert "Cero coincidencias reales" in resultado
        assert "Bajo ninguna circunstancia inventes" in resultado

    @pytest.mark.asyncio
    @respx.mock
    async def test_stopwords_y_plural_se_ignoran_en_tokenizacion(self):
        mock_erp()
        # "las correas" -> tokens de texto deberían reducirse a "correa" (sin 's', sin "las").
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="las correas",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        assert "Correa 29x2.10" in resultado
        assert "Correa 29x2.125" in resultado


class TestCategoriaRefinada:
    @pytest.mark.asyncio
    @respx.mock
    async def test_refinamiento_filtra_por_categoria(self):
        mock_erp()
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="correa",
            erp_url=ERP_URL, erp_mapping=MAPPING, categoria_refinada="Correas",
        )
        assert "Correa 29x2.10" in resultado

    @pytest.mark.asyncio
    @respx.mock
    async def test_refinamiento_sin_coincidencias_devuelve_mensaje(self):
        mock_erp()
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="correa",
            erp_url=ERP_URL, erp_mapping=MAPPING, categoria_refinada="Neumáticos",
        )
        assert "No hay productos en la categoría" in resultado


class TestOrdenamientoYBypass:
    @pytest.mark.asyncio
    @respx.mock
    async def test_mayor_valor_ordena_descendente_y_limita_a_3(self):
        mock_erp()
        resultado = await consultar_inventario_erp(
            tipo_filtro="mayor_valor", valor_busqueda="ALL",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        primera_linea = [l for l in resultado.split("\n") if l.startswith("-")][0]
        assert "Neumático 700c" in primera_linea  # precio_tienda=25000, el más caro

    @pytest.mark.asyncio
    @respx.mock
    async def test_menor_valor_ordena_ascendente(self):
        mock_erp()
        resultado = await consultar_inventario_erp(
            tipo_filtro="menor_valor", valor_busqueda="ALL",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        primera_linea = [l for l in resultado.split("\n") if l.startswith("-")][0]
        assert "Cadena reforzada" in primera_linea  # precio_tienda=8000, el más barato

    @pytest.mark.asyncio
    @respx.mock
    async def test_stock_mayor_ordena_descendente_y_limita_a_5(self):
        mock_erp()
        resultado = await consultar_inventario_erp(
            tipo_filtro="stock_mayor", valor_busqueda="ALL",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        primera_linea = [l for l in resultado.split("\n") if l.startswith("-")][0]
        assert "Cadena reforzada" in primera_linea  # stock_min=50, el mayor

    @pytest.mark.asyncio
    @respx.mock
    async def test_stock_critico_filtra_stock_menor_o_igual_a_3_y_ordena_ascendente(self):
        mock_erp()
        resultado = await consultar_inventario_erp(
            tipo_filtro="stock_critico", valor_busqueda="ALL",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        # Solo "Neumático 700c" (stock=0) y "Correa 29x2.125" (stock=2) califican (<=3).
        assert "Cadena reforzada" not in resultado
        assert "Correa 29x2.10" not in resultado  # stock_min=10, no califica
        lineas = [l for l in resultado.split("\n") if l.startswith("-")]
        assert "Neumático 700c" in lineas[0]  # stock 0, va primero

    @pytest.mark.asyncio
    @respx.mock
    async def test_stock_critico_sin_resultados_bajo_el_umbral(self):
        # Ningún artículo de ARTICULOS_BASE con stock<=3 coincide con "cadena".
        mock_erp()
        resultado = await consultar_inventario_erp(
            tipo_filtro="stock_critico", valor_busqueda="cadena",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        assert "Cero coincidencias reales" in resultado


class TestTrampaDeFriccion:
    @pytest.mark.asyncio
    @respx.mock
    async def test_mas_de_20_resultados_con_categorias_multiples(self):
        articulos = [
            {"id": str(i), "sku": f"SKU-{i}", "articulo": f"Producto genérico {i}",
             "precio_tienda": 1000, "stock_min": 10,
             "categoria": "CategoriaA" if i % 2 == 0 else "CategoriaB"}
            for i in range(25)
        ]
        mock_erp(articulos)
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="producto",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        assert "DEMASIADOS RESULTADOS" in resultado
        assert "NO INVENTES CATEGORÍAS" in resultado
        assert "CategoriaA" in resultado or "CategoriaB" in resultado

    @pytest.mark.asyncio
    @respx.mock
    async def test_mas_de_20_resultados_con_una_sola_categoria_muestra_ejemplos(self):
        articulos = [
            {"id": str(i), "sku": f"SKU-{i}", "articulo": f"Producto genérico {i}",
             "precio_tienda": 1000, "stock_min": 10, "categoria": "Unica"}
            for i in range(25)
        ]
        mock_erp(articulos)
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="producto",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        assert "DEMASIADOS RESULTADOS" in resultado
        assert "25 ítems" in resultado
        assert "Producto genérico" in resultado


class TestFormatoDeRespuesta:
    @pytest.mark.asyncio
    @respx.mock
    async def test_incluye_categoria_solo_si_esta_en_el_mapping(self):
        mock_erp()
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="cadena",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        assert "[Transmisión]" in resultado

    @pytest.mark.asyncio
    @respx.mock
    async def test_articulo_sin_sku_no_rompe_la_limpieza_de_texto(self):
        # limpiar_texto debe manejar valores vacíos/ausentes (art sin "sku")
        # sin lanzar excepción, devolviendo "" en vez de fallar.
        articulos = [
            {"id": "9", "articulo": "Producto sin sku", "precio_tienda": 1000,
             "stock_min": 10, "categoria": "General"},
        ]
        mock_erp(articulos)
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="producto",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        assert "Producto sin sku" in resultado

    @pytest.mark.asyncio
    @respx.mock
    async def test_sin_categoria_en_mapping_no_la_muestra(self):
        mock_erp()
        mapping_sin_categoria = {k: v for k, v in MAPPING.items() if k != "categoria"}
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="cadena",
            erp_url=ERP_URL, erp_mapping=mapping_sin_categoria,
        )
        assert "[Transmisión]" not in resultado
        assert "Cadena reforzada" in resultado
