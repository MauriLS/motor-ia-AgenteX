# motor-ia-AgenteX/tools.py
import httpx
import time

# 1. EL MANIFIESTO GENÉRICO (SaaS)
# Quitamos el nombre del cliente. Ahora es una herramienta estándar.
tools_manifest = [
    {
        "type": "function",
        "function": {
            "name": "consultar_inventario_erp",
            "description": "Obtiene información en tiempo real del ERP del cliente actual sobre un artículo usando su ID interno.",
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

# 2. LA FUNCIÓN FÍSICA Y DINÁMICA
# 🚩 AHORA RECIBE LA URL DEL ERP POR PARÁMETRO
async def consultar_inventario_erp(id_articulo: int, erp_url: str) -> str:
    """
    Consume el endpoint del ERP inyectado por el Tenant y filtra en memoria.
    """
    if not erp_url:
        return "Error crítico: No se ha configurado la URL del ERP para este cliente."

    url = f"{erp_url}?_timestamp={int(time.time())}" 
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            
            if response.status_code != 200:
                return f"Fallo de enlace con el ERP (Status {response.status_code})."
                
            articulos_array = response.json()
            
            articulo_encontrado = next((item for item in articulos_array if item.get('id') == id_articulo), None)
            
            if not articulo_encontrado:
                return f"Error: No existe el artículo ID {id_articulo} en la base de datos del ERP actual."
            
            # Mapeo estándar (Si los ERPs de distintos clientes tienen esquemas distintos, 
            # aquí en el futuro usarás el Patrón Adapter, pero por ahora estandarizamos la salida)
            sku = articulo_encontrado.get('sku', 'Sin SKU')
            nombre = articulo_encontrado.get('articulo', 'Artículo Desconocido')
            precio = articulo_encontrado.get('precio_tienda', 0)
            stock = articulo_encontrado.get('stock_min', 0)
            estado = "Activo" if articulo_encontrado.get('estado') else "Inactivo"
            
            return f"DATOS DEL ERP: Artículo: {nombre}. SKU: {sku}. Precio: ${precio} CLP. Stock: {stock}. Estado: {estado}."
            
    except Exception as e:
        return f"Error crítico al consultar el servidor ERP proporcionado: {str(e)}"