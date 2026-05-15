# motor-ia-AgenteX/tools.py
import httpx
import time
import unicodedata
import re

# =============================================================================
# 1. MANIFIESTO DE HERRAMIENTAS
# =============================================================================
tools_manifest = [
    {
        "type": "function",
        "function": {
            "name": "consultar_inventario_erp",
            "description": (
                "Motor analítico del ERP. REGLA DE SEGURIDAD CRÍTICA: "
                "Solo puedes ejecutar esta herramienta UNA VEZ por turno. "
                "Si la herramienta te devuelve un mensaje de "
                "'SISTEMA: DEMASIADOS RESULTADOS', PROHIBIDO volver a usar "
                "la herramienta. Debes detenerte inmediatamente y copiarle "
                "esa directiva al usuario para que él decida."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo_filtro": {
                        "type": "string",
                        "enum": [
                            "busqueda_general",
                            "stock_critico",
                            "stock_mayor",
                            "mayor_valor",
                            "menor_valor",
                            "conteo_total",
                        ],
                        "description": (
                            "REGLA: Si pide 'el más caro', usa 'mayor_valor'. "
                            "Si pide 'el más barato', 'menor_valor'. "
                            "Si pide 'el de mayor stock', 'más unidades' "
                            "o 'con más stock', usa 'stock_mayor'. "
                            "Si pide 'con menos stock', usa 'stock_critico'. "
                            "Para buscar nombres genéricos, usa 'busqueda_general'."
                        ),
                    },
                    "valor_busqueda": {
                        "type": "string",
                        "description": (
                            "REGLA VITAL DE EXTRACCIÓN: Traduce la intención "
                            "del usuario a un término técnico corto.\n"
                            "1. Extrae SOLO el sustantivo principal o código de pieza.\n"
                            "2. NUNCA envíes preposiciones gramaticales.\n"
                            "3. EXCLUYE términos genéricos del rubro del cliente "
                            "según su Contexto de Negocio.\n"
                            "4. Para dimensiones: ELIMINA la letra 'x' y los espacios. "
                            "Si el usuario pide '29 x 2.10', envía '29 2.10'.\n"
                            "5. Si el usuario dice 'de los N que encontraste' o hace "
                            "referencia a una búsqueda anterior, REPITE el mismo "
                            "valor_busqueda que usaste en esa búsqueda. NUNCA uses "
                            "el historial como fuente de datos."
                        ),
                    },
                    "categoria_refinada": {
                        "type": "string",
                        "description": (
                            "Úsalo ÚNICAMENTE si el sistema te pidió refinar "
                            "por categoría en el turno anterior y el usuario "
                            "ya te dio su elección."
                        ),
                    },
                },
                "required": ["tipo_filtro", "valor_busqueda"],
            },
        },
    }
]

# =============================================================================
# 2. MOTOR DE BÚSQUEDA
# =============================================================================
async def consultar_inventario_erp(
    tipo_filtro:       str,
    valor_busqueda:    str,
    erp_url:           str,
    erp_mapping:       dict = None,
    categoria_refinada: str = None,
) -> str:

    if not erp_url:
        return (
            "SISTEMA: URL del ERP no configurada. "
            "Dile al usuario que contacte a soporte."
        )

    if not erp_mapping:
        return (
            "SISTEMA: Falta el diccionario de mapeo. "
            "Configuración B2B incompleta."
        )

    # ── Claves del mapeo (agnóstico al tenant) ────────────────────────────────
    k_id       = erp_mapping.get("id",        "id")
    k_sku      = erp_mapping.get("sku",       "sku")
    k_nombre   = erp_mapping.get("nombre",    "articulo")
    k_precio   = erp_mapping.get("precio",    "precio_tienda")
    k_stock    = erp_mapping.get("stock",     "stock_min")
    k_categoria = erp_mapping.get("categoria", "categoria")

    url = f"{erp_url}?_timestamp={int(time.time())}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)

            if response.status_code != 200:
                return (
                    f"SISTEMA: Fallo de conexión ERP "
                    f"(Status {response.status_code})."
                )

            articulos = response.json()

        # ── PASO 1: CONTEO RÁPIDO ─────────────────────────────────────────────
        if tipo_filtro == "conteo_total":
            return (
                f"SISTEMA: El ERP contiene {len(articulos)} artículos en total. "
                f"Pregúntale al usuario qué segmento desea explorar."
            )

        # ── FUNCIÓN DE LIMPIEZA ───────────────────────────────────────────────
        def limpiar_texto(texto: str) -> str:
            if not texto:
                return ""
            return (
                unicodedata.normalize("NFKD", str(texto))
                .encode("ASCII", "ignore")
                .decode("utf-8")
                .lower()
            )

        # ── PASO 2: TOKENIZACIÓN CON SEPARACIÓN TEXTO / NÚMEROS ───────────────
        #
        # FIX CRÍTICO: Antes, todos los tokens se evaluaban con AND, lo que
        # hacía que "29 2.10" fallara en un producto "29x2.125" porque "2.10"
        # no coincide exactamente con "2.125".
        #
        # Nueva lógica:
        #   - Tokens de TEXTO → AND (todos deben estar en el nombre)
        #   - Tokens NUMÉRICOS → OR  (al menos uno debe estar en el nombre)
        #
        # Esto permite que "29 2.10" encuentre productos "29x2.10", "29x2.125",
        # "29x2.20", etc., devolviendo un set útil en vez de cero resultados.
        # ─────────────────────────────────────────────────────────────────────

        palabras_basura = {
            "de", "para", "el", "la", "los", "las", "con",
            "sin", "en", "un", "una", "unos", "unas", "y", "o", "a",
        }

        termino_limpio = limpiar_texto(valor_busqueda)
        tokens_raw = termino_limpio.split()

        # Tokens que contienen al menos un dígito → numéricos
        tokens_numericos = [t for t in tokens_raw if re.search(r'\d', t)]

        # Tokens sin dígitos, sin stop-words, con corte de plural simple
        tokens_texto = [
            t[:-1] if t.endswith("s") and len(t) > 3 else t
            for t in tokens_raw
            if t not in palabras_basura and not re.search(r'\d', t)
        ]

        # ── PASO 3: FILTRADO BASE ─────────────────────────────────────────────
        resultados_base = []

        for art in articulos:
            val_id    = str(art.get(k_id, ""))
            val_sku   = limpiar_texto(art.get(k_sku,    ""))
            val_nombre = limpiar_texto(art.get(k_nombre, ""))

            # FIX: Usar termino_limpio (normalizado) en lugar de la variable
            # sin normalizar que existía antes como termino_lower.
            match_id_sku = (
                val_id == termino_limpio
                or termino_limpio in val_sku
            )

            # Texto: AND — todos los tokens de texto deben estar
            match_texto = (
                all(t in val_nombre for t in tokens_texto)
                if tokens_texto else True
            )

            # Números: OR — al menos un token numérico debe estar
            # (tolerancia a medidas similares, ej. 2.10 / 2.125 / 2.20)
            match_numeros = (
                any(t in val_nombre for t in tokens_numericos)
                if tokens_numericos else True
            )

            if valor_busqueda == "ALL" or match_id_sku or (match_texto and match_numeros):

                if tipo_filtro == "stock_critico":
                    if float(art.get(k_stock) or 0) <= 3:
                        resultados_base.append(art)
                else:
                    resultados_base.append(art)

        # ── PARCHE ANTI-ALUCINACIÓN: Cero resultados ──────────────────────────
        if not resultados_base:
            return (
                f"SISTEMA: Cero coincidencias reales en el ERP para "
                f"'{valor_busqueda}'. "
                f"ORDEN ESTRICTA: Informa al usuario que ese artículo no existe "
                f"en el inventario. Bajo ninguna circunstancia inventes productos, "
                f"precios o IDs."
            )

        # ── PASO 4: REFINAMIENTO DE CATEGORÍA ────────────────────────────────
        resultados_finales = resultados_base

        if categoria_refinada:
            cat_lower = limpiar_texto(categoria_refinada)
            resultados_finales = [
                a for a in resultados_base
                if cat_lower in limpiar_texto(str(a.get(k_categoria, "")))
            ]

            if not resultados_finales:
                return (
                    f"SISTEMA: No hay productos en la categoría "
                    f"'{categoria_refinada}' para esta búsqueda."
                )

        # ── PASO 5: ORDENAMIENTO Y BYPASS ────────────────────────────────────
        if tipo_filtro == "mayor_valor":
            resultados_finales.sort(
                key=lambda x: float(x.get(k_precio) or 0), reverse=True
            )
            resultados_finales = resultados_finales[:3]

        elif tipo_filtro == "menor_valor":
            resultados_finales.sort(
                key=lambda x: float(x.get(k_precio) or 0)
            )
            resultados_finales = resultados_finales[:3]

        elif tipo_filtro == "stock_mayor":
            resultados_finales.sort(
                key=lambda x: float(x.get(k_stock) or 0), reverse=True
            )
            resultados_finales = resultados_finales[:5]

        elif tipo_filtro == "stock_critico":
            resultados_finales.sort(
                key=lambda x: float(x.get(k_stock) or 0)
            )

        # ── PASO 6: TRAMPA DE FRICCIÓN (>20 resultados) ───────────────────────
        UMBRAL_MAXIMO = 20

        if len(resultados_finales) > UMBRAL_MAXIMO:
            categorias_reales = [
                str(a.get(k_categoria, "")).strip()
                for a in resultados_finales
                if str(a.get(k_categoria, "")).strip()
            ]
            categorias_unicas = list(set(categorias_reales))

            if len(categorias_unicas) > 1:
                categorias_limpias = categorias_unicas[:5]
                return (
                    f"SISTEMA: DEMASIADOS RESULTADOS. Encontrados: {len(resultados_finales)}. "
                    f"REGLA DE HIERRO: NO INVENTES CATEGORÍAS. "
                    f"Pídele al usuario que elija ÚNICAMENTE entre estas opciones reales: "
                    f"{', '.join(categorias_limpias)}."
                )
            else:
                ejemplos_nombres = [
                    str(a.get(k_nombre, "")) for a in resultados_finales[:4]
                ]
                return (
                    f"SISTEMA: DEMASIADOS RESULTADOS ({len(resultados_finales)} ítems). "
                    f"La consulta es muy amplia. MUESTRA al usuario esta lista de ejemplos "
                    f"reales que encontraste para que vea las opciones disponibles:\n"
                    f"- " + "\n- ".join(ejemplos_nombres) +
                    f"\n\nORDEN: Pregúntale al usuario: 'Tengo {len(resultados_finales)} productos. "
                    f"Aquí hay algunos ejemplos reales. ¿Qué medida exacta o modelo necesita?'"
                )

        # ── PASO 7: RESPUESTA FINAL ───────────────────────────────────────────
        texto_respuesta = (
            "SISTEMA: Búsqueda exitosa. "
            "Entrégale esta lista detallada al usuario:\n"
        )

        for art in resultados_finales:
            r_id     = art.get(k_id,     "N/A")
            r_nombre = art.get(k_nombre, "Desconocido")
            r_precio = art.get(k_precio, 0)
            r_stock  = art.get(k_stock,  0)

            texto_cat = (
                f"[{art.get(k_categoria)}] "
                if k_categoria in erp_mapping
                else ""
            )

            texto_respuesta += (
                f"- {texto_cat}{r_nombre} "
                f"(ID: {r_id}) | "
                f"Precio: ${r_precio} | "
                f"Stock: {r_stock}\n"
            )

        return texto_respuesta

    except Exception as e:
        return f"SISTEMA: Fallo de ejecución en el pre-filtro: {str(e)}"