# modules/mapper.py
"""
Mapeia as colunas do VTRL para a estrutura exata do master.
Normaliza datas para DD/MM/AAAA.
Aplica regra de língua PT/EN por Country Code.
Remove duplicados exatos.
Valida estado CHECKED OUT.
"""

import pandas as pd
from dateutil import parser as date_parser
from typing import Tuple, Dict, List

from config.settings import (
    COLUMN_MAPPING,
    OUTPUT_COLUMNS,
    PORTUGUESE_COUNTRY_CODES,
    CHECKEDOUT_VALUES,
    REQUIRED_FIELDS,
)
from modules.loader import detect_column_match, _normalize_col


def _parse_date(value: str) -> str:
    """
    Converte qualquer formato de data para DD/MM/AAAA.
    Ignora componente horária.
    Retorna string vazia se inválido.
    """
    if not value or str(value).strip() in ("", "nan", "None", "NaT"):
        return ""
    try:
        dt = date_parser.parse(str(value).strip(), dayfirst=True)
        return dt.strftime("%d/%m/%Y")
    except Exception:
        try:
            # Tenta formatos comuns manuais
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y",
                        "%Y/%m/%d", "%d.%m.%Y", "%m.%d.%Y"):
                try:
                    import datetime
                    dt = datetime.datetime.strptime(str(value).strip()[:10], fmt)
                    return dt.strftime("%d/%m/%Y")
                except ValueError:
                    continue
        except Exception:
            pass
        return ""


def _apply_language_rule(country_code: str) -> str:
    """
    PT se o country code for Portugal, EN para qualquer outro.
    Valor vazio/inválido → EN.
    """
    if not country_code or str(country_code).strip() in ("", "nan", "None"):
        return "EN"
    cc = str(country_code).strip().upper()
    if cc in PORTUGUESE_COUNTRY_CODES:
        return "PT"
    return "EN"


def map_vtrl_to_master(vtrl_df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict, List[str]]:
    """
    Mapeia VTRL para estrutura do master.

    Retorna:
    - DataFrame mapeado com colunas OUTPUT_COLUMNS
    - dict com o mapeamento encontrado (output_col → vtrl_col)
    - lista de avisos/warnings
    """
    warnings = []
    mapping_found = {}
    vtrl_cols = vtrl_df.columns.tolist()  # já normalizados pelo loader

    # Descobrir qual coluna do VTRL mapeia para cada coluna do output
    raw_cols = {}
    for output_col, aliases in COLUMN_MAPPING.items():
        matched = detect_column_match(vtrl_cols, aliases)
        if matched:
            raw_cols[output_col] = matched
            mapping_found[output_col] = matched
        else:
            raw_cols[output_col] = None
            # PHONE_NUMBER e LANGUAGE podem ser derivadas, não são críticas se ausentes
            if output_col not in ("PHONE_NUMBER", "LANGUAGE"):
                warnings.append(
                    f"Coluna '{output_col}' não encontrada no VTRL "
                    f"(aliases esperados: {aliases[:3]}...)"
                )

    # Construir DataFrame de output
    out_rows = []
    invalid_status_count = 0

    for _, row in vtrl_df.iterrows():
        # Validar estado CHECKED OUT (se a coluna existir)
        if raw_cols.get("PHONE_NUMBER"):
            status_val = str(row.get(raw_cols["PHONE_NUMBER"], "")).strip().lower()
            if status_val and status_val not in CHECKEDOUT_VALUES:
                invalid_status_count += 1
                continue  # Excluir da lista final

        out_row = {}

        # RESORT
        col = raw_cols.get("RESORT")
        out_row["RESORT"] = str(row[col]).strip() if col and col in row else ""

        # FIRST
        col = raw_cols.get("FIRST")
        out_row["FIRST"] = str(row[col]).strip().title() if col and col in row else ""

        # LAST
        col = raw_cols.get("LAST")
        out_row["LAST"] = str(row[col]).strip().title() if col and col in row else ""

        # PHONE_TYPE (email do hóspede)
        col = raw_cols.get("PHONE_TYPE")
        val = str(row[col]).strip().lower() if col and col in row else ""
        out_row["PHONE_TYPE"] = val if "@" in val else val

        # PHONE_NUMBER (status — fixo "CHECKED OUT" conforme regra)
        out_row["PHONE_NUMBER"] = "CHECKED OUT"

        # ARRIVAL_DATE_TIME
        col = raw_cols.get("ARRIVAL_DATE_TIME")
        raw_val = str(row[col]).strip() if col and col in row else ""
        out_row["ARRIVAL_DATE_TIME"] = _parse_date(raw_val)

        # DEPARTURE_DATE_TIME
        col = raw_cols.get("DEPARTURE_DATE_TIME")
        raw_val = str(row[col]).strip() if col and col in row else ""
        out_row["DEPARTURE_DATE_TIME"] = _parse_date(raw_val)

        # LANGUAGE (derivado de Country Code)
        col = raw_cols.get("LANGUAGE")
        cc_val = str(row[col]).strip() if col and col in row else ""
        out_row["LANGUAGE"] = _apply_language_rule(cc_val)

        # ROOM
        col = raw_cols.get("ROOM")
        room_val = str(row[col]).strip() if col and col in row else ""
        # Remover casas decimais de números inteiros (ex: "101.0" → "101")
        if room_val.endswith(".0"):
            room_val = room_val[:-2]
        out_row["ROOM"] = room_val

        out_rows.append(out_row)

    if invalid_status_count > 0:
        warnings.append(
            f"{invalid_status_count} registo(s) excluído(s) por estado diferente de CHECKED OUT."
        )

    mapped_df = pd.DataFrame(out_rows, columns=OUTPUT_COLUMNS)

    # Limpar valores "nan" para string vazia
    mapped_df = mapped_df.replace({"nan": "", "None": "", "NaT": ""})

    # Remover duplicados exatos
    before = len(mapped_df)
    mapped_df = mapped_df.drop_duplicates().reset_index(drop=True)
    dupes_removed = before - len(mapped_df)
    if dupes_removed > 0:
        warnings.append(f"{dupes_removed} duplicado(s) exato(s) removido(s).")

    return mapped_df, mapping_found, warnings


def validate_required_fields(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Separa registos com campos mínimos obrigatórios dos que não têm.
    Retorna (válidos, inválidos).
    """
    mask_invalid = df[REQUIRED_FIELDS].apply(
        lambda col: col.str.strip() == ""
    ).any(axis=1)
    return df[~mask_invalid].reset_index(drop=True), df[mask_invalid].reset_index(drop=True)
