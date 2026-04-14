# modules/matcher.py
"""
Cruza o VTRL mapeado com o Guest Interaction Report (GIR).
Classifica cada registo como: elegível, excluído, suspenso.
Retorna DataFrames separados + relatório de exclusões.
"""

import pandas as pd
from rapidfuzz import fuzz
from typing import Tuple, Dict, List

from config.settings import (
    EXCLUSION_KEYWORDS,
    SUSPENSION_KEYWORDS,
    FUZZY_EXACT_THRESHOLD,
    FUZZY_PROBABLE_THRESHOLD,
)
from modules.loader import _normalize_col


# Possíveis nomes de colunas no GIR para cada campo de matching
GIR_NAME_ALIASES = ["guest name", "name", "nome", "first name", "firstname", "nome completo"]
GIR_FIRST_ALIASES = ["first name", "firstname", "first", "nome", "name first"]
GIR_LAST_ALIASES = ["last name", "lastname", "last", "apelido", "surname"]
GIR_DEPARTURE_ALIASES = ["departure date", "checkout date", "departure", "check out date", "data saida", "data saída"]
GIR_ROOM_ALIASES = ["room", "room no", "room no.", "quarto", "room number"]
GIR_EMAIL_ALIASES = ["email", "e-mail", "email address", "guest email"]
GIR_RESERVATION_ALIASES = ["reservation", "reservation number", "confirmation", "confirmation number", "profile id", "res no", "booking"]
GIR_NOTES_ALIASES = ["notes", "notas", "comments", "comentários", "comentarios", "observations", "observações", "status", "estado", "issue", "problema"]


def _find_gir_col(gir_df: pd.DataFrame, aliases: list):
    """Retorna nome da coluna no GIR que corresponde aos aliases, ou None."""
    gir_cols = gir_df.columns.tolist()
    for alias in aliases:
        norm = _normalize_col(alias)
        for col in gir_cols:
            if col == norm:
                return col
    return None


def _contains_keyword(text: str, keywords: list) -> bool:
    """Verifica se o texto contém alguma das palavras-chave (case-insensitive)."""
    text_lower = str(text).lower()
    return any(kw.lower() in text_lower for kw in keywords)


def _classify_gir_record(gir_row: pd.Series, notes_cols: list) -> str:
    """
    Analisa as colunas de notas/estado do GIR para um registo.
    Retorna: 'excluded', 'suspended' ou 'ok'.
    """
    combined_text = " ".join(
        str(gir_row.get(col, "")) for col in notes_cols
    )
    if _contains_keyword(combined_text, EXCLUSION_KEYWORDS):
        return "excluded"
    if _contains_keyword(combined_text, SUSPENSION_KEYWORDS):
        return "suspended"
    return "ok"


def _get_notes_text(gir_row: pd.Series, notes_cols: list) -> str:
    """Extrai texto de notas relevante do GIR para mostrar ao utilizador."""
    parts = []
    for col in notes_cols:
        val = str(gir_row.get(col, "")).strip()
        if val and val not in ("nan", "None", ""):
            parts.append(f"[{col}] {val}")
    return " | ".join(parts)[:300]  # Limitar comprimento


def cross_with_gir(
    vtrl_df: pd.DataFrame,
    gir_df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, List[str]]:
    """
    Cruza o VTRL mapeado com o GIR.

    Retorna:
    - eligible_df: registos elegíveis para ReviewPro
    - excluded_df: excluídos automaticamente
    - suspended_df: suspensos para revisão humana
    - no_match_df: sem correspondência no GIR (tratados como elegíveis por defeito)
    - warnings: lista de avisos
    """
    warnings = []

    # Descobrir colunas do GIR
    gir_first_col = _find_gir_col(gir_df, GIR_FIRST_ALIASES)
    gir_last_col = _find_gir_col(gir_df, GIR_LAST_ALIASES)
    gir_departure_col = _find_gir_col(gir_df, GIR_DEPARTURE_ALIASES)
    gir_room_col = _find_gir_col(gir_df, GIR_ROOM_ALIASES)
    gir_email_col = _find_gir_col(gir_df, GIR_EMAIL_ALIASES)
    gir_res_col = _find_gir_col(gir_df, GIR_RESERVATION_ALIASES)

    # Descobrir colunas de notas/estado no GIR
    notes_cols = []
    for aliases in [GIR_NOTES_ALIASES]:
        for alias in aliases:
            col = _find_gir_col(gir_df, [alias])
            if col and col not in notes_cols:
                notes_cols.append(col)

    if not notes_cols:
        warnings.append(
            "Não foram encontradas colunas de notas/estado no GIR. "
            "Não será possível aplicar regras de exclusão/suspensão automáticas."
        )

    # Normalizar GIR para matching
    if gir_first_col and gir_last_col:
        gir_df = gir_df.copy()
        gir_df["_full_name"] = (
            gir_df[gir_first_col].fillna("").astype(str).str.strip().str.lower()
            + " "
            + gir_df[gir_last_col].fillna("").astype(str).str.strip().str.lower()
        ).str.strip()
    elif gir_first_col:
        gir_df = gir_df.copy()
        gir_df["_full_name"] = gir_df[gir_first_col].fillna("").astype(str).str.strip().str.lower()
    else:
        gir_df = gir_df.copy()
        gir_df["_full_name"] = ""

    # Resultados
    eligible_rows = []
    excluded_rows = []
    suspended_rows = []
    no_match_rows = []

    for idx, vtrl_row in vtrl_df.iterrows():
        vtrl_name = (
            str(vtrl_row.get("FIRST", "")).strip().lower()
            + " "
            + str(vtrl_row.get("LAST", "")).strip().lower()
        ).strip()
        vtrl_departure = str(vtrl_row.get("DEPARTURE_DATE_TIME", "")).strip()
        vtrl_room = str(vtrl_row.get("ROOM", "")).strip().lower()
        vtrl_email = str(vtrl_row.get("PHONE_TYPE", "")).strip().lower()

        best_match_idx = None
        best_score = 0
        match_type = "no_match"

        for gir_idx, gir_row in gir_df.iterrows():
            # Nível 1: Matching por email (exato)
            if vtrl_email and gir_email_col:
                gir_email = str(gir_row.get(gir_email_col, "")).strip().lower()
                if vtrl_email == gir_email and vtrl_email != "":
                    best_match_idx = gir_idx
                    best_score = 100
                    match_type = "exact"
                    break

            # Nível 2: Matching fuzzy por nome + data saída
            gir_name = str(gir_row.get("_full_name", "")).strip()
            name_score = fuzz.token_sort_ratio(vtrl_name, gir_name)

            if gir_departure_col:
                gir_dep = str(gir_row.get(gir_departure_col, "")).strip()
                # Normalizar datas para comparação simples
                dep_match = (vtrl_departure == gir_dep) or (
                    vtrl_departure[:10] == gir_dep[:10]
                )
            else:
                dep_match = True  # Sem coluna de data, não penalizar

            if gir_room_col:
                gir_room = str(gir_row.get(gir_room_col, "")).strip().lower()
                room_match = (vtrl_room == gir_room)
            else:
                room_match = True

            # Score combinado
            if dep_match and room_match:
                combined = name_score
            elif dep_match or room_match:
                combined = name_score * 0.85
            else:
                combined = name_score * 0.6

            if combined > best_score:
                best_score = combined
                best_match_idx = gir_idx

        # Classificar com base no score
        if best_score >= FUZZY_EXACT_THRESHOLD:
            match_type = "exact"
        elif best_score >= FUZZY_PROBABLE_THRESHOLD:
            match_type = "probable"
        else:
            match_type = "no_match"

        if match_type == "no_match":
            row_out = vtrl_row.to_dict()
            row_out["_match_type"] = "no_match"
            row_out["_match_score"] = round(best_score, 1)
            row_out["_gir_notes"] = ""
            row_out["_exclusion_reason"] = ""
            row_out["_status"] = "eligible"
            no_match_rows.append(row_out)
            continue

        # Registo com match → classificar pelo conteúdo do GIR
        gir_row = gir_df.iloc[best_match_idx]
        gir_classification = _classify_gir_record(gir_row, notes_cols)
        gir_notes = _get_notes_text(gir_row, notes_cols)

        row_out = vtrl_row.to_dict()
        row_out["_match_type"] = match_type
        row_out["_match_score"] = round(best_score, 1)
        row_out["_gir_notes"] = gir_notes

        if gir_classification == "excluded":
            row_out["_status"] = "excluded"
            row_out["_exclusion_reason"] = "Exclusão automática por palavra-chave no GIR"
            excluded_rows.append(row_out)
        elif gir_classification == "suspended" or match_type == "probable":
            row_out["_status"] = "suspended"
            reason = []
            if gir_classification == "suspended":
                reason.append("Palavra-chave de suspensão no GIR")
            if match_type == "probable":
                reason.append(f"Match provável (score {round(best_score,1)}%) — requer validação")
            row_out["_exclusion_reason"] = " | ".join(reason)
            suspended_rows.append(row_out)
        else:
            row_out["_status"] = "eligible"
            row_out["_exclusion_reason"] = ""
            eligible_rows.append(row_out)

    def to_df(rows):
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    eligible_df = to_df(eligible_rows)
    excluded_df = to_df(excluded_rows)
    suspended_df = to_df(suspended_rows)
    no_match_df = to_df(no_match_rows)

    return eligible_df, excluded_df, suspended_df, no_match_df, warnings
