# modules/loader.py
"""
Carrega ficheiros Excel ou CSV.
Normaliza nomes de colunas (strip, lower).
Detecta encodings comuns.
Retorna DataFrame com colunas normalizadas + dict de mapeamento encontrado.
"""

import pandas as pd
import io
from typing import Optional


def _normalize_col(col: str) -> str:
    """Strip espaços, lower, remove newlines."""
    return str(col).strip().lower().replace("\n", " ").replace("  ", " ")


def load_file(uploaded_file) -> pd.DataFrame:
    """
    Carrega um ficheiro Streamlit UploadedFile (xlsx, xls ou csv).
    Retorna DataFrame com colunas normalizadas.
    Lança ValueError com mensagem clara em caso de falha.
    """
    name = uploaded_file.name.lower()
    try:
        if name.endswith(".csv"):
            # Tenta UTF-8, depois latin-1
            try:
                df = pd.read_csv(uploaded_file, dtype=str, encoding="utf-8")
            except UnicodeDecodeError:
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, dtype=str, encoding="latin-1")
        elif name.endswith((".xlsx", ".xls")):
            df = pd.read_excel(uploaded_file, dtype=str, engine="openpyxl")
        else:
            raise ValueError(
                f"Formato não suportado: '{uploaded_file.name}'. "
                "Aceites: .xlsx, .xls, .csv"
            )
    except Exception as e:
        if isinstance(e, ValueError):
            raise
        raise ValueError(f"Erro ao ler '{uploaded_file.name}': {e}")

    if df.empty:
        raise ValueError(f"O ficheiro '{uploaded_file.name}' está vazio.")

    # Normalizar nomes de colunas
    df.columns = [_normalize_col(c) for c in df.columns]

    # Remover linhas completamente vazias
    df = df.dropna(how="all").reset_index(drop=True)

    return df


def get_master_columns(master_df: pd.DataFrame) -> list:
    """
    Extrai os nomes de colunas do master (uppercase para comparação).
    Usado apenas como referência de estrutura.
    """
    return [c.strip().upper() for c in master_df.columns.tolist()]


def detect_column_match(df_cols: list, aliases: list) -> Optional[str]:
    """
    Dado um DataFrame com colunas normalizadas e uma lista de aliases,
    retorna o nome da coluna encontrada ou None.
    """
    normalized_aliases = [_normalize_col(a) for a in aliases]
    for col in df_cols:
        if col in normalized_aliases:
            return col
    return None
