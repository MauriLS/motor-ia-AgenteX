# motor-ia-AgenteX/tools.py
import httpx

# 1. EL MANIFIESTO (El contrato estricto para DeepSeek)
tools_manifest = [
    {
        "type": "function",
        "function": {
            "name": "consultar_producto_tienda",
            "description": "Obtiene información en tiempo real de un producto específico en la tienda por su ID (incluye precio, categoría, descripción). Usa esta herramienta SIEMPRE que el usuario pregunte por detalles de un producto específico.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "integer",
                        "description": "El ID numérico del producto a consultar (ejemplo: 1, 5, 10)."
                    }
                },
                "required": ["product_id"]
            }
        }
    }
]

# 2. LA FUNCIÓN FÍSICA (La ejecución real)
async def consultar_producto_tienda(product_id: int) -> str:
    """
    Va a la API externa y devuelve un string con los datos en crudo para la IA.
    """
    url = f"https://fakestoreapi.com/products/{product_id}"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            
            if response.status_code == 404:
                return f"Error: No existe ningún producto con el ID {product_id}."
            if response.status_code != 200:
                return f"Error de conexión con la tienda (Status {response.status_code})."
                
            data = response.json()
            # Devolvemos un string estructurado para que la IA lo entienda fácil
            return f"Producto encontrado: {data['title']}. Precio: ${data['price']}. Categoría: {data['category']}. Descripción: {data['description']}."
            
    except Exception as e:
        return f"Error interno al consultar la base de datos de productos: {str(e)}"