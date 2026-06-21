import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("DEEPSEEK_API_KEY", "test-deepseek-key")
os.environ.setdefault("INTERNAL_SECRET", "test-internal-secret")

import httpx
import pytest


def make_client(app):
    """Cliente HTTP que habla directo con la app ASGI, sin levantar un puerto real."""
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def reload_main():
    """Recarga main.py con variables de entorno controladas.

    main.py lee DEEPSEEK_API_KEY/INTERNAL_SECRET una sola vez al importarse,
    así que los tests que necesitan variar esos valores (p. ej. INTERNAL_SECRET
    vacío vs configurado) deben forzar un reload del módulo.
    """

    def _reload(internal_secret="test-internal-secret", deepseek_key="test-deepseek-key"):
        os.environ["INTERNAL_SECRET"] = internal_secret
        os.environ["DEEPSEEK_API_KEY"] = deepseek_key
        import main

        importlib.reload(main)
        return main

    return _reload


@pytest.fixture
def main_module(reload_main):
    return reload_main()


@pytest.fixture
async def client(main_module):
    async with make_client(main_module.app) as ac:
        yield ac