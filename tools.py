# motor-ia-AgenteX/tools.py
import httpx
import time

# 1. EL MANIFIESTO ESTRATÉGICO
tools_manifest = [
    {
        "type": "function",
        "function": {
            "name": "consultar_inventario_zxtreme",
            "description": "Obtiene información en tiempo real del ERP corporativo sobre un artículo (toritos, bicicletas, repuestos) usando su ID interno. EJECUTA ESTO SIEMPRE para dar precios, stock o disponibilidad web.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_articulo": {
                        "type": "integer",
                        "description": "El ID numérico exacto del artículo a consultar."
                    }
                },
                "required": ["id_articulo"]
            }
        }
    }
]

# 2. LA FUNCIÓN FÍSICA (Tu Endpoint Real)
# Reemplaza SOLO la función física en tools.py

async def consultar_inventario_zxtreme(id_articulo: int) -> str:
    """
    Consume el endpoint masivo de Zxtreme y filtra en memoria de Python.
    (Workaround arquitectónico para ERP sin rutas individuales).
    """
    # Apuntamos a la raíz. Traerá TODO el inventario.
    url = f"http://92.113.39.10:3001/articulos?_timestamp={int(time.time())}" 
    
    try:
        # Aumentamos el timeout a 30 segundos previendo una carga pesada de datos
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            
            if response.status_code != 200:
                return f"Fallo de enlace con el ERP Zxtreme (Status {response.status_code})."
                
            articulos_array = response.json()
            
            # Buscamos el ID exacto dentro de la matriz masiva que entregó tu ERP
            # Usamos next() para detener la búsqueda en el instante en que lo encuentre
            articulo_encontrado = next((item for item in articulos_array if item.get('id') == id_articulo), None)
            
            if not articulo_encontrado:
                return f"Error: No existe el artículo ID {id_articulo} en la base de datos del ERP."
            
            # Mapeo estricto a tu esquema SQL (MyISAM)
            sku = articulo_encontrado.get('sku', 'Sin SKU')
            nombre = articulo_encontrado.get('articulo', 'Artículo Desconocido')
            precio = articulo_encontrado.get('precio_tienda', 0)
            stock = articulo_encontrado.get('stock_min', 0)
            estado = "Activo" if articulo_encontrado.get('estado') else "Inactivo/Descontinuado"
            web = "Publicado en Zxtreme.cl" if articulo_encontrado.get('web') else "Venta solo interna"
            descripcion = articulo_encontrado.get('descripcion', 'Sin descripción')
            
            return f"DATOS DEL ERP: Artículo: {nombre}. SKU: {sku}. Precio Tienda: ${precio} CLP. Stock Mínimo Registrado: {stock}. Estado Comercial: {estado}. Estado Web: {web}. Descripción Técnica: {descripcion}."
            
    except Exception as e:
        return f"Error crítico al consultar el servidor 92.113.39.10: {str(e)}"