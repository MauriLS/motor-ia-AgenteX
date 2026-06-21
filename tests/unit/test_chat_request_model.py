"""Unit tests para el modelo pydantic ChatRequest de main.py."""
import pytest
from pydantic import ValidationError


class TestChatRequestDefaults:
    def test_campos_opcionales_usan_sus_defaults(self, main_module):
        req = main_module.ChatRequest(
            tenant_id=1, user_message="hola", system_prompt="eres un agente",
        )
        assert req.temperature == 0.3
        assert req.erp_url is None
        assert req.erp_mapping is None
        assert req.allowed_tools == []
        assert req.history == []

    def test_acepta_todos_los_campos_explicitos(self, main_module):
        req = main_module.ChatRequest(
            tenant_id=7,
            user_message="¿cuánto stock queda?",
            system_prompt="eres un agente B2B",
            temperature=0.8,
            erp_url="https://erp.acme.com",
            erp_mapping={"id": "codigo"},
            allowed_tools=["consultar_inventario_erp"],
            history=[{"role": "user", "content": "hola"}],
        )
        assert req.temperature == 0.8
        assert req.erp_mapping == {"id": "codigo"}
        assert req.allowed_tools == ["consultar_inventario_erp"]
        assert req.history == [{"role": "user", "content": "hola"}]


class TestChatRequestValidacion:
    def test_falla_sin_tenant_id(self, main_module):
        with pytest.raises(ValidationError):
            main_module.ChatRequest(user_message="hola", system_prompt="x")

    def test_falla_sin_user_message(self, main_module):
        with pytest.raises(ValidationError):
            main_module.ChatRequest(tenant_id=1, system_prompt="x")

    def test_falla_sin_system_prompt(self, main_module):
        with pytest.raises(ValidationError):
            main_module.ChatRequest(tenant_id=1, user_message="hola")

    def test_tenant_id_no_castea_texto_no_numerico(self, main_module):
        with pytest.raises(ValidationError):
            main_module.ChatRequest(
                tenant_id="no-es-un-numero", user_message="hola", system_prompt="x",
            )
