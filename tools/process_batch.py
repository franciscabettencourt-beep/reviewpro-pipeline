#!/usr/bin/env python3
# tools/process_batch.py
"""
Processa um lote fora do Streamlit: os mesmos módulos e o mesmo fluxo da app
(mapear cada VTRL com as suas colunas, agregar com dedup, cruzar com TODOS os
GIR num único índice), a devolver os três ficheiros de export e o resumo.
É o motor que o vigia da ponte Lovable usa.
"""

import io
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "reviewpro_pipeline"))

import pandas as pd

from modules.loader import load_file
from modules.mapper import map_vtrl_to_master, validate_required_fields
from modules.matcher import cross_with_gir
from modules.exporter import (
    export_excel_final,
    export_reviewpro,
    export_exclusion_report,
)


class _NamedBytes(io.BytesIO):
    """O load_file espera um UploadedFile do Streamlit; bytes com .name chegam."""

    def __init__(self, data: bytes, name: str):
        super().__init__(data)
        self.name = name


def _load(item):
    """Aceita um caminho no disco ou um par (bytes, nome)."""
    if isinstance(item, tuple):
        data, name = item
    else:
        with open(item, "rb") as f:
            data = f.read()
        name = os.path.basename(item)
    return name, load_file(_NamedBytes(data, name))


def process_batch(vtrl_items, gir_items):
    """
    vtrl_items / gir_items: caminhos ou pares (bytes, nome).
    Devolve (resumo dict, ficheiros dict nome→bytes, avisos list).
    """
    warnings = []

    mapped_parts = []
    total_vtrl = 0
    for item in vtrl_items:
        name, df = _load(item)
        total_vtrl += len(df)
        part, _, ws = map_vtrl_to_master(df)
        mapped_parts.append(part)
        warnings += [f"{name}: {w}" for w in ws]
    mapped = pd.concat(mapped_parts, ignore_index=True)
    before = len(mapped)
    mapped = mapped.drop_duplicates().reset_index(drop=True)
    if before - len(mapped) > 0:
        warnings.append(
            f"{before - len(mapped)} duplicado(s) removido(s) entre ficheiros VTRL."
        )

    valid, invalid = validate_required_fields(mapped)
    if len(invalid) > 0:
        warnings.append(
            f"{len(invalid)} registo(s) excluídos por falta de campos obrigatórios."
        )

    girs = []
    for item in gir_items:
        name, df = _load(item)
        girs.append(df)
    gir_all = pd.concat(girs, ignore_index=True)

    eligible, excluded, suspended, no_match, ws = cross_with_gir(valid, gir_all)
    warnings += ws

    frames = [d for d in [eligible, no_match] if not d.empty]
    final_eligible = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if final_eligible.empty:
        raise ValueError("Sem registos elegíveis no lote.")

    lang = final_eligible.get("LANGUAGE", pd.Series(dtype=str))
    resumo = {
        "elegiveis": int(len(final_eligible)),
        "excluidos": int(len(excluded)),
        "suspensos": int(len(suspended)),
        "sem_match": int(len(no_match)),
        "total_vtrl": int(total_vtrl),
        "lingua_pt": int((lang == "PT").sum()),
        "lingua_en": int((lang == "EN").sum()),
    }

    def as_bytes(v):
        return v.encode("utf-8") if isinstance(v, str) else bytes(v)

    ficheiros = {
        "reviewpro_import.csv": as_bytes(export_reviewpro(final_eligible)),
        "excel_final.xlsx": as_bytes(export_excel_final(final_eligible)),
        "relatorio_exclusoes.xlsx": as_bytes(export_exclusion_report(excluded, suspended)),
    }
    return resumo, ficheiros, warnings
