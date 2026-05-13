import httpx
import time

# 1. EL MANIFIESTO ESTRATÉGICO
tools_manifest = [
    {
        "type": "function",
        "function": {
            "name": "consultar_inventario_erp",
            "description": "Motor analítico del ERP. Úsalo para buscar productos o aplicar filtros duros. REGLA: Si la herramienta te devuelve un mensaje de 'SISTEMA: DEMASIADOS RESULTADOS', debes copiar esa directiva y preguntarle al usuario de qué categoría desea ver los productos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo_filtro": {
                        "type": "string",
                        "enum": ["busqueda_general", "stock_critico", "stock_mayor", "mayor_valor", "menor_valor", "conteo_total"],
                        "description": "REGLA: Si pide 'el más caro', usa 'mayor_valor'. Si pide 'el más barato', 'menor_valor'. Si pide 'el de mayor stock', 'más unidades' o 'con más stock', usa 'stock_mayor'. Si pide 'con menos stock', usa 'stock_critico'. Para buscar nombres genéricos, usa 'busqueda_general'."
                    },
                    "valor_busqueda": {
                        "type": "string",
                        "description": "La palabra clave (ej. 'producto_A', 'repuesto_B') o 'ALL' para revisar toda la base."
                    },
                    "categoria_refinada": {
                        "type": "string",
                        "description": "Úsalo ÚNICAMENTE si el sistema te pidió refinar por categoría en el turno anterior y el usuario ya te dio su elección."
                    }
                },
                "required": ["tipo_filtro", "valor_busqueda"]
            }
        }
    }
]

# 2. EL MOTOR DE NAVEGACIÓN EN PROFUNDIDAD (Drill-Down)
async def consultar_inventario_erp(tipo_filtro: str, valor_busqueda: str, erp_url: str, erp_mapping: dict = None, categoria_refinada: str = None) -> str:
    if not erp_url:
        return "SISTEMA: URL del ERP no configurada. Dile al usuario que contacte a soporte."
    
    if not erp_mapping:
        return "SISTEMA: Falta el diccionario de mapeo. Configuración B2B incompleta."

    # Extraemos las llaves del mapeo (Asumimos que el cliente configuró 'categoria')
    k_id = erp_mapping.get("id", "id")
    k_sku = erp_mapping.get("sku", "sku")
    k_nombre = erp_mapping.get("nombre", "articulo")
    k_precio = erp_mapping.get("precio", "precio_tienda")
    k_stock = erp_mapping.get("stock", "stock_min")
    k_categoria = erp_mapping.get("categoria", "categoria") # 🚩 NUEVO PARÁMETRO VITAL

    url = f"{erp_url}?_timestamp={int(time.time())}" 
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            if response.status_code != 200:
                return f"SISTEMA: Fallo de conexión ERP (Status {response.status_code})."
                
            articulos = response.json()
            termino_lower = str(valor_busqueda).lower()
            
            # PASO 1: CONTEO RÁPIDO (Bypass de rendimiento)
            if tipo_filtro == "conteo_total":
                return f"SISTEMA: El ERP contiene {len(articulos)} artículos en total. Pregúntale al usuario qué segmento desea explorar."

            # PASO 2: FILTRADO BASE
            resultados_base = []
            for art in articulos:
                match_id = str(art.get(k_id, '')) == termino_lower
                match_sku = termino_lower in str(art.get(k_sku, '')).lower()
                match_nombre = termino_lower in str(art.get(k_nombre, '')).lower()
                
                # Si busca 'ALL', entra todo. Si no, solo coincidencias.
                if valor_busqueda == "ALL" or match_id or match_sku or match_nombre:
                    # Aplicar filtro duro si es necesario
                    if tipo_filtro == "stock_critico":
                        stock_actual = float(art.get(k_stock) or 0)
                        if stock_actual <= 3: # Definimos 3 como límite crítico interno
                            resultados_base.append(art)
                    else:
                        resultados_base.append(art)

            if not resultados_base:
                return f"SISTEMA: Cero coincidencias para '{valor_busqueda}' con filtro '{tipo_filtro}'."

            # PASO 3: REFINAMIENTO DE CATEGORÍA (Si el usuario ya cayó en la trampa y eligió)
            resultados_finales = resultados_base
            if categoria_refinada:
                cat_lower = categoria_refinada.lower()
                resultados_finales = [a for a in resultados_base if cat_lower in str(a.get(k_categoria, '')).lower()]

            if not resultados_finales:
                return f"SISTEMA: No hay productos en la categoría '{categoria_refinada}' para esta búsqueda."

            # PASO 4: ORDENAMIENTO Y BYPASS INTELIGENTE
            if tipo_filtro == "mayor_valor":
                resultados_finales.sort(key=lambda x: float(x.get(k_precio) or 0), reverse=True)
                resultados_finales = resultados_finales[:3] 
                
            elif tipo_filtro == "menor_valor":
                resultados_finales.sort(key=lambda x: float(x.get(k_precio) or 0))
                resultados_finales = resultados_finales[:3]
                
            elif tipo_filtro == "stock_mayor": # 🚩 NUEVO BYPASS
                resultados_finales.sort(key=lambda x: float(x.get(k_stock) or 0), reverse=True)
                # Cortamos a 5. Así nunca chocará con la trampa de >10.
                resultados_finales = resultados_finales[:5]
                
            elif tipo_filtro == "stock_critico":
                resultados_finales.sort(key=lambda x: float(x.get(k_stock) or 0))
                # Los críticos no los cortamos, queremos que caigan en la trampa si son muchos

            # PASO 5: LA TRAMPA DE FRICCIÓN (Adaptativa según el ERP del cliente)
            UMBRAL_MAXIMO = 15
            
            if len(resultados_finales) > UMBRAL_MAXIMO:
                # Intentamos extraer categorías REALES del JSON, ignorando vacíos y nulos
                categorias_reales = [str(a.get(k_categoria, '')).strip() for a in resultados_finales if str(a.get(k_categoria, '')).strip()]
                categorias_unicas = list(set(categorias_reales))

                # Escenario A: El cliente SÍ tiene categorías reales en su ERP
                if len(categorias_unicas) > 1:
                    categorias_limpias = categorias_unicas[:5]
                    return (f"SISTEMA: DEMASIADOS RESULTADOS. Encontrados: {len(resultados_finales)}. "
                            f"REGLA DE HIERRO: NO INVENTES CATEGORÍAS. NO digas 'Electrónicos' o cosas genéricas. "
                            f"Pídele al usuario que elija ÚNICAMENTE entre estas opciones reales: "
                            f"{', '.join(categorias_limpias)}.")
                
                # Escenario B: El cliente NO tiene categorías (o todos son la misma)
                else:
                    # Extraemos palabras clave reales de los primeros 3 productos
                    ejemplos_nombres = [str(a.get(k_nombre, '')).split()[0] for a in resultados_finales[:3]]
                    return (f"SISTEMA: DEMASIADOS RESULTADOS. Encontrados: {len(resultados_finales)}. "
                            f"El sistema no tiene categorías. Pídele al usuario que te dé una PALABRA CLAVE para filtrar el nombre. "
                            f"Guíalo diciéndole algo como: 'Encontré {len(resultados_finales)} resultados. ¿Buscas algún modelo en específico? "
                            f"Por ejemplo, ¿algo relacionado con {', '.join(ejemplos_nombres)}...?'")

            # PASO 6: RESPUESTA FINAL (Sobreviviendo a datos nulos)
            texto_respuesta = f"SISTEMA: Búsqueda exitosa. Entrégale esta lista detallada al usuario:\n"
            for art in resultados_finales:
                r_id = art.get(k_id, "N/A")
                r_nombre = art.get(k_nombre, "Desconocido")
                r_precio = art.get(k_precio, 0)
                r_stock = art.get(k_stock, 0)
                
                # Solo agregamos el texto de categoría si la empresa lo soporta
                texto_cat = f"[{art.get(k_categoria)}] " if k_categoria in erp_mapping else ""
                
                texto_respuesta += f"- {texto_cat}{r_nombre} (ID: {r_id}) | Precio: ${r_precio} | Stock: {r_stock}\n"
            
            return texto_respuesta
            
    except Exception as e:
        return f"SISTEMA: Fallo de ejecución en el pre-filtro: {str(e)}"