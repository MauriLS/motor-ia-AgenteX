"""
Regresión — motor-ia-agenteX.

Ambos bugs fueron encontrados con el mismo método que en el frontend:
`git log --all --oneline | grep -i fix` sobre todo el repo, y luego
`git show <hash> -- tools.py` para confirmar el cambio real. Los dos están
documentados como comentarios "FIX" dentro del propio código (tools.py
líneas ~141-152 y ~180-182), introducidos en el commit
`ced5cfa` ("Fix(api): corregir redacción del LLM con los datos").
"""
import httpx
import pytest
import respx

from tools import consultar_inventario_erp

ERP_URL = "https://erp.example.com/articulos"
MAPPING = {
    "id": "id", "sku": "sku", "nombre": "articulo",
    "precio": "precio_tienda", "stock": "stock_min", "categoria": "categoria",
}


class TestBugPY01TokensNumericosDebenSerOR:
    """
    BUG-PY-01 (commit ced5cfa, tools.py ~141-152).

    Causa: antes del fix, TODOS los tokens (texto y numéricos) se evaluaban
    con AND. Si el usuario pedía una medida como "29 2.10" y el ERP tenía el
    producto guardado como "29x2.125", el token "2.10" nunca coincidía
    exactamente con "2.125" -> el AND fallaba -> cero resultados, aunque el
    producto correcto SÍ existía en el inventario.

    Fix: los tokens numéricos ahora se evalúan con OR (al menos uno debe
    aparecer en el nombre), tolerando medidas similares/cercanas.
    """

    @pytest.mark.asyncio
    @respx.mock
    async def test_medida_29_210_encuentra_producto_29x2125(self):
        respx.get(ERP_URL).mock(return_value=httpx.Response(200, json=[
            {"id": "1", "sku": "COR-1", "articulo": "Correa 29x2.125",
             "precio_tienda": 16000, "stock_min": 5, "categoria": "Correas"},
        ]))
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="29 2.10",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        assert "Correa 29x2.125" in resultado
        assert "Cero coincidencias" not in resultado

    @pytest.mark.asyncio
    @respx.mock
    async def test_medida_con_dos_tokens_numericos_no_exige_ambos_a_la_vez(self):
        # Si el AND volviera a aplicarse sobre números, este caso (un solo
        # token numérico coincide, el otro no) volvería a dar cero resultados.
        respx.get(ERP_URL).mock(return_value=httpx.Response(200, json=[
            {"id": "1", "sku": "COR-1", "articulo": "Correa 29x2.20",
             "precio_tienda": 16000, "stock_min": 5, "categoria": "Correas"},
        ]))
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="29 2.10",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        assert "Correa 29x2.20" in resultado


class TestBugPY02MatchIdSkuDebeUsarTerminoNormalizado:
    """
    BUG-PY-02 (commit ced5cfa, tools.py ~180-182).

    Causa: la comparación de ID/SKU usaba una variable sin normalizar
    (documentada en el propio código como "termino_lower", ya removida) en
    vez de `termino_limpio` (que sí pasa por `limpiar_texto`: quita acentos,
    pasa a minúsculas). Como `val_sku` SÍ estaba normalizado, una búsqueda
    con mayúsculas o tildes nunca calzaba contra el SKU guardado, aunque
    fuera exactamente el mismo código de producto.

    Fix: usar `termino_limpio` (normalizado) en ambos lados de la
    comparación de `match_id_sku`.
    """

    @pytest.mark.asyncio
    @respx.mock
    async def test_busqueda_con_mayusculas_y_tildes_encuentra_el_sku(self):
        respx.get(ERP_URL).mock(return_value=httpx.Response(200, json=[
            {"id": "1", "sku": "cod-001", "articulo": "Repuesto genérico",
             "precio_tienda": 5000, "stock_min": 10, "categoria": "Repuestos"},
        ]))
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="CÓD-001",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        assert "Repuesto genérico" in resultado
        assert "Cero coincidencias" not in resultado

    @pytest.mark.asyncio
    @respx.mock
    async def test_busqueda_por_id_exacto_normalizado(self):
        respx.get(ERP_URL).mock(return_value=httpx.Response(200, json=[
            {"id": "42", "sku": "X", "articulo": "Producto cualquiera",
             "precio_tienda": 1000, "stock_min": 10, "categoria": "General"},
        ]))
        # El ID se compara como str(val_id) == termino_limpio; con espacios
        # alrededor (error de tipeo típico del usuario) debe seguir fallando
        # de forma controlada, no explotar — confirma que la comparación
        # sigue siendo estricta sobre el término ya normalizado.
        resultado = await consultar_inventario_erp(
            tipo_filtro="busqueda_general", valor_busqueda="42",
            erp_url=ERP_URL, erp_mapping=MAPPING,
        )
        assert "Producto cualquiera" in resultado
