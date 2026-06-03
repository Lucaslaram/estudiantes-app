import os
import json
import requests
from fastapi import HTTPException

def generate_recipe_from_llm(ingredients_list: list[str]) -> dict:
    """
    Se conecta con la API de OpenRouter usando el modelo gemini-2.5-flash
    para generar una receta estructurada basada en los ingredientes provistos.
    """
    # 1. Validar la existencia de la API Key en las variables de entorno (.env)
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="La clave de la API (OPENROUTER_API_KEY) no está configurada en las variables de entorno."
        )

    # 2. Construir la lista de ingredientes en texto plano para el prompt
    ingredients_text = ", ".join(ingredients_list)

    # 3. Diseñar un prompt estricto con el formato JSON requerido
    prompt = f"""
    Eres un chef experto y creativo. Crea una receta única y deliciosa utilizando obligatoriamente algunos o todos los siguientes ingredientes disponibles: {ingredients_text}. 
    Puedes asumir que el usuario tiene ingredientes básicos de cocina como sal, pimienta, agua y aceite de cocina.

    Debes responder ÚNICAMENTE con un objeto JSON válido, sin bloques de código Markdown (no uses ```json ni ```), sin texto introductorio ni explicaciones adicionales. El formato del JSON debe ser exactamente el siguiente:
    {{
        "nombre_plato": "Nombre creativo de la receta",
        "ingredientes": [
            "ingrediente 1 con su cantidad estimada",
            "ingrediente 2 con su cantidad estimada"
        ],
        "pasos": [
            "Paso 1: Descripción detallada de la primera instrucción.",
            "Paso 2: Descripción detallada de la segunda instrucción."
        ],
        "tiempo_estimado": "Ej: 35 minutos",
        "nivel_dificultad": "Fácil, Medio o Difícil"
    }}
    """

    # 4. Configurar los encabezados y el cuerpo para la petición HTTP de OpenRouter
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://localhost:8000",
        "X-Title": "App Estudiantes Cocina IA"
    }

    payload = {
        "model": "google/gemini-2.5-flash",
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.7
    }

    # 5. Ejecutar la petición de forma segura controlando excepciones de red
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=15
        )
        response.raise_for_status()
        result = response.json()
        
        # Extraer el contenido del mensaje devuelto por la IA
        content_str = result["choices"][0]["message"]["content"].strip()
        
        # Limpiar posibles bloques de código que el modelo retorne por inercia
        if content_str.startswith("```"):
            content_str = content_str.strip("```").strip("json").strip()

        # 6. Parsear la cadena de texto a un diccionario de Python válido
        recipe_data = json.loads(content_str)
        
        # Validar campos mínimos requeridos en el diccionario antes de retornar
        required_fields = ["nombre_plato", "ingredientes", "pasos", "tiempo_estimado", "nivel_dificultad"]
        if not all(field in recipe_data for field in required_fields):
            raise ValueError("El JSON devuelto por el modelo carece de campos obligatorios.")
            
        return recipe_data

    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=502,
            detail=f"Falla de comunicación con el proveedor de IA (OpenRouter): {str(e)}"
        )
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        raise HTTPException(
            status_code=502,
            detail="La IA generó una respuesta pero no pudo ser procesada en el formato estructurado correcto. Inténtalo de nuevo."
        )