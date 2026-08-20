# modules/matcher.py
"""
Cruza o VTRL mapeado com o Guest Interaction Report (GIR).
Classifica cada registo como: elegível, excluído, suspenso.
Retorna DataFrames separados + relatório de exclusões.
"""

import re
from datetime import datetime, timedelta

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
from modules.mapper import _parse_date


# Possíveis nomes de colunas no GIR para cada campo de matching
GIR_NAME_ALIASES = ["guest name", "guestname", "name", "guest", "nome", "nome completo", "hóspede", "hospede", "cliente"]
GIR_FIRST_ALIASES = ["first name", "firstname", "first", "nome", "name first"]
GIR_LAST_ALIASES = ["last name", "lastname", "last", "apelido", "surname"]
GIR_DEPARTURE_ALIASES = ["departure date", "checkout date", "departure", "check out date", "data saida", "data saída", "data check-out", "data check out", "check-out", "checkout"]
GIR_CHECKIN_ALIASES = ["arrival date", "check in date", "checkin date", "data chegada", "data check-in", "data check in", "check-in", "arrival"]
GIR_TIPO_ALIASES = ["tipo de interacção", "tipo de interaccao", "tipo de interação", "interaction type", "tipo"]
GIR_ROOM_ALIASES = ["room", "room no", "room no.", "quarto", "room number"]
GIR_EMAIL_ALIASES = ["email", "e-mail", "email address", "guest email"]
GIR_RESERVATION_ALIASES = ["reservation", "reservation number", "confirmation", "confirmation number", "profile id", "res no", "booking"]
GIR_NOTES_ALIASES = [
    "notes", "notas", "comments", "comentários", "comentarios",
    "observations", "observações", "status", "estado", "issue", "problema",
    "tipo de interacção", "tipo de interaccao", "tipo de interação",
    "situação reportada & acção tomada", "situação", "situacao",
    "follow up", "followup", "encerrado",
]


def _find_gir_col(gir_df: pd.DataFrame, aliases: list):
    """Retorna nome da coluna no GIR que corresponde aos aliases, ou None."""
    gir_cols = [c for c in gir_df.columns.tolist() if not str(c).startswith("_")]
    # 1ª passagem: correspondência exata
    for alias in aliases:
        norm = _normalize_col(alias)
        for col in gir_cols:
            if col == norm:
                return col
    # 2ª passagem: correspondência parcial (ex: "guest name (last, first)")
    for alias in aliases:
        norm = _normalize_col(alias)
        for col in gir_cols:
            if norm in col:
                return col
    return None


def _contains_keyword(text: str, keywords: list) -> bool:
    """
    Verifica se o texto contém alguma das palavras-chave (case-insensitive).
    Compara também a versão SEM espaços: nos PDFs do GIR, células com texto em
    2 linhas saem com os caracteres espaçados ("R e c l am ação") e a palavra
    só é encontrada depois de remover os espaços.
    """
    text_lower = str(text).lower()
    text_despaced = text_lower.replace(" ", "")
    for kw in keywords:
        k = kw.lower()
        if k in text_lower or k.replace(" ", "") in text_despaced:
            return True
    return False


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


def _norm_room(r: str) -> str:
    """Normaliza um número de quarto: remove zeros à esquerda ('0007' → '7')."""
    stripped = str(r).lstrip("0")
    return stripped if stripped else str(r)


def _extract_rooms(room_cell: str, notes_text: str) -> set:
    """
    Extrai os números de quarto de um registo do GIR:
    - do valor da coluna de quarto ("9107", "9202/9203", "7" — Residences)
    - de listas de quartos no texto das notas ("9007,9009,9107")
    Números soltos no meio do texto (preços, horas) NÃO contam — só listas.
    """
    rooms = {_norm_room(r) for r in re.findall(r"\d{1,4}", str(room_cell))}
    for lst in re.findall(r"\d{3,4}(?:\s*[,;/]\s*\d{3,4})+", str(notes_text)):
        rooms |= {_norm_room(r) for r in re.findall(r"\d{3,4}", lst)}
    return {r for r in rooms if r and r != "0"}


def _date_in_stay(departure: str, checkin: str, checkout: str) -> bool:
    """
    O check-out do VTRL (DD/MM/AAAA) cai dentro da estadia do registo do GIR?
    Tolerância de +1 dia após o check-out (late check-outs). Datas em falta
    ou ilegíveis não bloqueiam o match (na dúvida, excluir — protege o GRI).
    """
    try:
        dep = datetime.strptime(str(departure).strip(), "%d/%m/%Y")
    except Exception:
        return True
    try:
        lo = datetime.strptime(str(checkin).strip(), "%d/%m/%Y")
        if dep < lo:
            return False
    except Exception:
        pass
    try:
        hi = datetime.strptime(str(checkout).strip(), "%d/%m/%Y")
        if dep > hi + timedelta(days=1):
            return False
    except Exception:
        pass
    return True


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
    gir_name_col = _find_gir_col(gir_df, GIR_NAME_ALIASES)
    gir_departure_col = _find_gir_col(gir_df, GIR_DEPARTURE_ALIASES)
    gir_checkin_col = _find_gir_col(gir_df, GIR_CHECKIN_ALIASES)
    gir_tipo_col = _find_gir_col(gir_df, GIR_TIPO_ALIASES)
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
    gir_df = gir_df.copy()
    if gir_first_col and gir_last_col:
        gir_df["_full_name"] = (
            gir_df[gir_first_col].fillna("").astype(str).str.strip().str.lower()
            + " "
            + gir_df[gir_last_col].fillna("").astype(str).str.strip().str.lower()
        ).str.strip()
    elif gir_name_col:
        # Coluna única com o nome completo (ex: "Guest Name": "Smith, John").
        # As vírgulas são removidas; o token_sort_ratio ignora a ordem dos nomes.
        gir_df["_full_name"] = (
            gir_df[gir_name_col].fillna("").astype(str)
            .str.replace(",", " ", regex=False)
            .str.lower()
            .str.split().str.join(" ")
        )
    elif gir_first_col:
        gir_df["_full_name"] = gir_df[gir_first_col].fillna("").astype(str).str.strip().str.lower()
    else:
        gir_df["_full_name"] = ""
        available = ", ".join(str(c) for c in gir_df.columns if not str(c).startswith("_"))
        warnings.append(
            "Não foi encontrada nenhuma coluna de nome no GIR "
            f"(colunas detetadas: {available}). Sem nome não é possível fazer "
            "matching — todos os hóspedes serão tratados como 'sem match'."
        )

    # Normalizar a data de saída do GIR para DD/MM/AAAA (mesmo formato do VTRL)
    if gir_departure_col:
        gir_df["_dep_norm"] = (
            gir_df[gir_departure_col].fillna("").astype(str).map(_parse_date)
        )

    # ── Índice de QUARTOS com reclamação/suspensão ────────────────────────────
    # Regra principal: se um quarto aparece num registo do GIR classificado como
    # exclusão (ex.: Tipo de Interacção = "Reclamação..."), TODOS os hóspedes do
    # VTRL desse quarto com datas compatíveis são excluídos — apanha os
    # acompanhantes com apelidos diferentes e reclamações com vários quartos,
    # que o matching por nome não consegue apanhar.
    room_entries = []
    for _, gir_row in gir_df.iterrows():
        classification = _classify_gir_record(gir_row, notes_cols)
        if classification == "ok":
            continue
        notes_text = _get_notes_text(gir_row, notes_cols)
        room_cell = str(gir_row.get(gir_room_col, "")) if gir_room_col else ""
        rooms = _extract_rooms(room_cell, notes_text)
        if not rooms:
            continue
        checkin_norm = (
            _parse_date(str(gir_row.get(gir_checkin_col, ""))) if gir_checkin_col else ""
        )
        tipo_val = str(gir_row.get(gir_tipo_col, "")).strip() if gir_tipo_col else ""
        room_entries.append({
            "rooms": rooms,
            "checkin": checkin_norm,
            "checkout": str(gir_row.get("_dep_norm", "")).strip(),
            "status": classification,
            "notes": notes_text,
            "tipo": tipo_val,
        })
    if room_entries:
        excl_rooms = sorted({r for e in room_entries if e["status"] == "excluded" for r in e["rooms"]})
        if excl_rooms:
            warnings.append(
                f"Quartos com reclamação no GIR (exclusão automática): {', '.join(excl_rooms)}."
            )

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

        # ── 1º: exclusão/suspensão por QUARTO (independente do nome) ──────────
        room_hit = None
        vtrl_room_digits = _norm_room(re.sub(r"\D", "", vtrl_room))
        if vtrl_room_digits == "0":
            vtrl_room_digits = ""
        if vtrl_room_digits:
            for entry in room_entries:
                if vtrl_room_digits in entry["rooms"] and _date_in_stay(
                    vtrl_departure, entry["checkin"], entry["checkout"]
                ):
                    if room_hit is None or entry["status"] == "excluded":
                        room_hit = entry
                    if entry["status"] == "excluded":
                        break
        if room_hit is not None:
            row_out = vtrl_row.to_dict()
            row_out["_match_type"] = "room"
            row_out["_match_score"] = 100.0
            row_out["_gir_notes"] = room_hit["notes"]
            tipo_info = f" ({room_hit['tipo']})" if room_hit["tipo"] else ""
            if room_hit["status"] == "excluded":
                row_out["_status"] = "excluded"
                row_out["_exclusion_reason"] = (
                    f"Quarto {vtrl_room_digits} num registo de reclamação do GIR{tipo_info}"
                )
                excluded_rows.append(row_out)
            else:
                row_out["_status"] = "suspended"
                row_out["_exclusion_reason"] = (
                    f"Quarto {vtrl_room_digits} num registo com palavra-chave de suspensão no GIR{tipo_info}"
                )
                suspended_rows.append(row_out)
            continue

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
                gir_dep = str(gir_row.get("_dep_norm", "")).strip()
                # Ambas as datas já estão em DD/MM/AAAA; vazias não contam como match
                dep_match = bool(vtrl_departure) and vtrl_departure == gir_dep
            else:
                dep_match = True  # Sem coluna de data, não penalizar

            if gir_room_col:
                gir_room = str(gir_row.get(gir_room_col, "")).strip().lower()
                if gir_room.endswith(".0"):
                    gir_room = gir_room[:-2]
                # O GIR pode ter vários quartos ("9007,9009,9107 (#3)") —
                # basta o quarto do VTRL constar na lista
                gir_rooms = set(re.findall(r"\d+", gir_room))
                if gir_rooms:
                    room_match = bool(vtrl_room) and (
                        vtrl_room in gir_rooms or vtrl_room == gir_room
                    )
                else:
                    room_match = bool(vtrl_room) and vtrl_room == gir_room
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

    # Diagnóstico: se nada teve match, mostrar como as colunas do GIR foram interpretadas
    matched_total = len(eligible_rows) + len(excluded_rows) + len(suspended_rows)
    if len(vtrl_df) > 0 and matched_total == 0:
        if gir_first_col and gir_last_col:
            name_desc = f"{gir_first_col} + {gir_last_col}"
        else:
            name_desc = gir_name_col or gir_first_col
        detected = {
            "nome": name_desc,
            "data saída": gir_departure_col,
            "quarto": gir_room_col,
            "email": gir_email_col,
            "notas": ", ".join(notes_cols) if notes_cols else None,
        }
        detected_str = "; ".join(f"{k}={v or '—'}" for k, v in detected.items())
        available = ", ".join(
            str(c) for c in gir_df.columns if not str(c).startswith("_")
        )
        warnings.append(
            "Nenhum hóspede do VTRL teve correspondência no GIR. "
            f"Interpretação das colunas do GIR: {detected_str}. "
            f"Colunas disponíveis no GIR: {available}. "
            "Se alguma coluna foi mal interpretada, ajusta os aliases GIR_* "
            "no topo de modules/matcher.py."
        )

    return eligible_df, excluded_df, suspended_df, no_match_df, warnings
