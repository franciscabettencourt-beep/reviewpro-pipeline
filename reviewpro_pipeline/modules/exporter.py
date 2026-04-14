# modules/exporter.py
"""
Gera todos os ficheiros de output:
- Excel final (estrutura exata do master, sem formatações)
- CSV de controlo
- Ficheiro para ReviewPro (CSV compatível)
- Relatório de excluídos/suspensos
- Resumo de execução (dict)
"""

import pandas as pd
import io
import json
import datetime
from typing import Dict, Optional

from config.settings import OUTPUT_COLUMNS


def _clean_for_export(df: pd.DataFrame) -> pd.DataFrame:
    """Remove colunas internas (_match_type, _status, etc.) antes de exportar."""
    internal_cols = [c for c in df.columns if c.startswith("_")]
    return df.drop(columns=internal_cols, errors="ignore")


def export_excel_final(eligible_df: pd.DataFrame) -> bytes:
    """
    Gera Excel final com apenas os registos elegíveis.
    Sem formatações, sem cores, sem filtros — apenas dados.
    """
    df = _clean_for_export(eligible_df.copy())
    # Garantir ordem e presença das colunas do master
    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[OUTPUT_COLUMNS]

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="ReviewPro")
        # Sem formatações adicionais — apenas os dados
    return buffer.getvalue()


def export_csv_control(eligible_df: pd.DataFrame) -> bytes:
    """CSV de controlo com os mesmos dados do Excel final."""
    df = _clean_for_export(eligible_df.copy())
    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[OUTPUT_COLUMNS]
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


def export_reviewpro(eligible_df: pd.DataFrame) -> bytes:
    """
    Ficheiro para ReviewPro.
    CSV UTF-8 com BOM (compatível com importação Excel e maioria dos sistemas).
    Estrutura: mesmas colunas do output final.
    """
    df = _clean_for_export(eligible_df.copy())
    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[OUTPUT_COLUMNS]
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


def export_exclusion_report(
    excluded_df: pd.DataFrame,
    suspended_df: pd.DataFrame,
    processing_date: Optional[str] = None,
) -> bytes:
    """
    Relatório de excluídos e suspensos.
    Inclui: nome, quarto, motivo, origem, estado, notas, data.
    """
    if processing_date is None:
        processing_date = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")

    report_rows = []

    for _, row in excluded_df.iterrows():
        report_rows.append({
            "FIRST": row.get("FIRST", ""),
            "LAST": row.get("LAST", ""),
            "ROOM": row.get("ROOM", ""),
            "DEPARTURE_DATE_TIME": row.get("DEPARTURE_DATE_TIME", ""),
            "ESTADO": "EXCLUÍDO",
            "MOTIVO": row.get("_exclusion_reason", ""),
            "NOTAS_GIR": row.get("_gir_notes", ""),
            "MATCH_TYPE": row.get("_match_type", ""),
            "MATCH_SCORE": row.get("_match_score", ""),
            "DATA_PROCESSAMENTO": processing_date,
        })

    for _, row in suspended_df.iterrows():
        report_rows.append({
            "FIRST": row.get("FIRST", ""),
            "LAST": row.get("LAST", ""),
            "ROOM": row.get("ROOM", ""),
            "DEPARTURE_DATE_TIME": row.get("DEPARTURE_DATE_TIME", ""),
            "ESTADO": "SUSPENSO",
            "MOTIVO": row.get("_exclusion_reason", ""),
            "NOTAS_GIR": row.get("_gir_notes", ""),
            "MATCH_TYPE": row.get("_match_type", ""),
            "MATCH_SCORE": row.get("_match_score", ""),
            "DATA_PROCESSAMENTO": processing_date,
        })

    if not report_rows:
        report_rows.append({
            "FIRST": "", "LAST": "", "ROOM": "", "DEPARTURE_DATE_TIME": "",
            "ESTADO": "", "MOTIVO": "Sem exclusões ou suspensões neste lote.",
            "NOTAS_GIR": "", "MATCH_TYPE": "", "MATCH_SCORE": "",
            "DATA_PROCESSAMENTO": processing_date,
        })

    report_df = pd.DataFrame(report_rows)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        report_df.to_excel(writer, index=False, sheet_name="Exclusões e Suspensões")
    return buffer.getvalue()


def build_summary(
    total_vtrl: int,
    valid_vtrl: int,
    eligible_count: int,
    excluded_count: int,
    suspended_count: int,
    no_match_count: int,
    dupes_removed: int,
    pt_count: int,
    en_count: int,
    warnings: list,
) -> Dict:
    """Constrói dict de resumo de execução."""
    return {
        "data_processamento": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
        "total_vtrl": total_vtrl,
        "validos_apos_validacao": valid_vtrl,
        "elegiveis_final": eligible_count,
        "excluidos": excluded_count,
        "suspensos": suspended_count,
        "sem_match_gir": no_match_count,
        "duplicados_removidos": dupes_removed,
        "lingua_pt": pt_count,
        "lingua_en": en_count,
        "avisos": warnings,
    }


def save_history_json(summary: Dict, filepath: str):
    """Guarda resumo de execução em ficheiro JSON de histórico."""
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # Histórico é best-effort
