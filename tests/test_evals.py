"""Valida la estructura de la suite golden y el verificador (sin llamar al modelo)."""
import yaml

from evals.run_evals import ROOT, check, norm


def test_golden_bien_formado():
    casos = yaml.safe_load((ROOT / "golden.yaml").read_text(encoding="utf-8"))["casos"]
    ids = [c["id"] for c in casos]
    assert len(ids) == len(set(ids)) >= 15
    for c in casos:
        assert c["pregunta"] and c["categoria"]
        assert any(k in c for k in ("incluye_alguno", "incluye_todos", "excluye"))


def test_verificador_ignora_acentos_y_mayusculas():
    assert norm("Alta Dirección") == "alta direccion"
    caso = {"incluye_alguno": ["alta dirección"], "excluye": ["BBVA"]}
    assert check(caso, "Reporta a la ALTA DIRECCION") == []
    assert check(caso, "Trabaja en bbva") != []


def test_error_http_nunca_pasa():
    """Un caso que solo tiene 'excluye' no debe aprobar con una respuesta de error."""
    assert check({"excluye": ["bbva"]}, "[HTTP 504] upstream timeout") != []
