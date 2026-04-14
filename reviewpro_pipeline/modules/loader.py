# modules/loader.py
"""
Carrega ficheiros Excel, CSV, PDF ou XLS (HTML disfarçado de Excel do Opera/VTRL).
Normaliza nomes de colunas (strip, lower).
Retorna DataFrame com colunas normalizadas.
"""

import pandas as pd
import io
import pdfplumber
from typing import Optional


def _normalize_col(col: str) -> str:
    return str(col).strip().lower().replace("\n", " ").replace("  ", " ")


def _read_xls_html(uploaded_file) -> pd.DataFrame:
    """
    Lê ficheiros .xls que são na verdade HTML (formato gerado pelo Opera/VTRL).
    Estes ficheiros têm colunas alternadas com NaN que precisam de ser removidas.
    """
    content = uploaded_file.read()
    dfs = pd.read_html(io.BytesIO(content))
    if not dfs:
        raise ValueError("Não foi possível extrair dados do ficheiro XLS.")

    df = dfs[0].copy()

    # Remover colunas completamente vazias (NaN intercaladas)
    df = df.dropna(axis=1, how="all")

    # Usar a linha 0 como cabeçalho
    header_row = df.iloc[0].tolist()
    headers = [str(h).strip() if str(h) not in ("nan", "None", "") else f"col_{i}"
               for i, h in enumerate(header_row)]

    df = df.iloc[1:].reset_index(drop=True)
    df.columns = headers

    # Limpar valores
    df = df.replace({"nan": "", "None": "", "NaN": ""})
    df = df.dropna(how="all").reset_index(drop=True)

    # Normalizar colunas
    df.columns = [_normalize_col(c) for c in df.columns]

    # Remover linhas onde os valores são iguais aos nomes das colunas (cabeçalho duplicado)
    for col in df.columns:
        df = df[df[col].str.lower() != col.lower()].reset_index(drop=True)

    return df


def load_pdf(uploaded_file) -> pd.DataFrame:
    """
    Lê um PDF com tabela (como o Guest Interaction Report) usando pdfplumber.
    """
    rows = []
    headers = None

    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table:
                    continue
                if headers is None:
                    for i, row in enumerate(table):
                        if row and any(
                            cell and any(kw in str(cell).lower() for kw in
                                        ["guest name", "room", "status", "day"])
                            for cell in row
                        ):
                            headers = [
                                str(c).strip() if c else f"col_{j}"
                                for j, c in enumerate(row)
                            ]
                            for dr in table[i+1:]:
                                if dr and any(cell for cell in dr):
                                    rows.append(dr)
                            break
                else:
                    for row in table:
                        if row and any(cell for cell in row):
                            rows.append(row)

    if not headers or not rows:
        raise ValueError(
            "Não foi possível extrair tabela do PDF. "
            "Confirma que o PDF tem colunas como 'Guest Name', 'Room Number', 'Status'."
        )

    n_cols = len(headers)
    cleaned_rows = []
    for row in rows:
        row = list(row)
        if len(row) < n_cols:
            row = row + [""] * (n_cols - len(row))
        elif len(row) > n_cols:
            row = row[:n_cols]
        cleaned_rows.append(row)

    df = pd.DataFrame(cleaned_rows, columns=headers, dtype=str)
    df = df.dropna(how="all").reset_index(drop=True)
    df.columns = [_normalize_col(c) for c in df.columns]
    df = df.replace({"None": "", "nan": ""})
    return df


def _is_html_xls(uploaded_file) -> bool:
    """Detecta se um .xls é na verdade um ficheiro HTML."""
    try:
        start = uploaded_file.read(10)
        uploaded_file.seek(0)
        return start.strip().lower().startswith(b"<")
    except Exception:
        return False


def load_file(uploaded_file) -> pd.DataFrame:
    """
    Carrega um ficheiro Streamlit UploadedFile (xlsx, xls, csv ou pdf).
    Retorna DataFrame com colunas normalizadas.
    """
    name = uploaded_file.name.lower()
    try:
        if name.endswith(".pdf"):
            return load_pdf(uploaded_file)
        elif name.endswith(".csv"):
            try:
                df = pd.read_csv(uploaded_file, dtype=str, encoding="utf-8")
            except UnicodeDecodeError:
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, dtype=str, encoding="latin-1")
        elif name.endswith(".xlsx"):
            df = pd.read_excel(uploaded_file, dtype=str, engine="openpyxl")
        elif name.endswith(".xls"):
            if _is_html_xls(uploaded_file):
                return _read_xls_html(uploaded_file)
            else:
                try:
                    df = pd.read_excel(uploaded_file, dtype=str, engine="xlrd")
                except Exception:
                    uploaded_file.seek(0)
                    return _read_xls_html(uploaded_file)
        else:
            raise ValueError(
                f"Formato não suportado: '{uploaded_file.name}'. "
                "Aceites: .xlsx, .xls, .csv, .pdf"
            )
    except Exception as e:
        if isinstance(e, ValueError):
            raise
        raise ValueError(f"Erro ao ler '{uploaded_file.name}': {e}")

    if df.empty:
        raise ValueError(f"O ficheiro '{uploaded_file.name}' está vazio.")

    df.columns = [_normalize_col(c) for c in df.columns]
    df = df.dropna(how="all").reset_index(drop=True)
    return df


def get_master_columns(master_df: pd.DataFrame) -> list:
    return [c.strip().upper() for c in master_df.columns.tolist()]


def detect_column_match(df_cols: list, aliases: list) -> Optional[str]:
    normalized_aliases = [_normalize_col(a) for a in aliases]
    for col in df_cols:
        if col in normalized_aliases:
            return col
    return None
