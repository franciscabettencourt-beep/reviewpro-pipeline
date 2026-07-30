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

from config.settings import GIR_HEADER_KEYWORDS


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


def _norm_cell(c) -> str:
    if c is None:
        return ""
    return str(c).replace("\n", " ").strip()


def _is_header_row(cells) -> bool:
    """Uma linha é cabeçalho se pelo menos 2 células contêm palavras-chave do GIR."""
    hits = 0
    for cell in cells:
        text = _norm_cell(cell).lower()
        if text and any(kw in text for kw in GIR_HEADER_KEYWORDS):
            hits += 1
    return hits >= 2


def _find_header_index(table) -> Optional[int]:
    for i, row in enumerate(table):
        if row and _is_header_row(row):
            return i
    return None


def _extract_tables_any_strategy(page):
    """
    Tenta várias estratégias do pdfplumber. Muitos GIR não têm linhas de
    tabela desenhadas — nesse caso a estratégia por defeito não encontra nada
    e é preciso detetar colunas pelo alinhamento do texto.
    Só aceita uma estratégia se produzir uma tabela com cabeçalho reconhecível.
    """
    strategies = [
        None,  # por defeito: linhas desenhadas
        {"vertical_strategy": "lines", "horizontal_strategy": "text"},
        {"vertical_strategy": "text", "horizontal_strategy": "text"},
    ]
    for ts in strategies:
        try:
            tables = page.extract_tables(ts) if ts else page.extract_tables()
        except Exception:
            continue
        tables = [t for t in tables if t and len(t) >= 2]
        if any(_find_header_index(t) is not None for t in tables):
            return tables
    return []


def _lines_from_words(page):
    """Agrupa as palavras da página em linhas, pela posição vertical."""
    words = page.extract_words()
    lines = []
    current, current_top = [], None
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if current_top is not None and abs(w["top"] - current_top) > 3:
            lines.append(sorted(current, key=lambda w: w["x0"]))
            current, current_top = [], None
        current.append(w)
        if current_top is None:
            current_top = w["top"]
    if current:
        lines.append(sorted(current, key=lambda w: w["x0"]))
    return lines


def _table_from_words(page, headers=None, col_bounds=None):
    """
    Fallback para PDFs sem tabela detetável: reconstrói as colunas a partir
    das posições das palavras. O cabeçalho é detetado por palavras-chave e os
    espaçamentos entre os rótulos definem os limites das colunas.
    headers/col_bounds persistem entre páginas (cabeçalho só na 1ª).
    """
    rows = []
    for line in _lines_from_words(page):
        texts = [w["text"] for w in line]
        if headers is None:
            if not _is_header_row(texts):
                continue
            # Agrupar palavras do cabeçalho em rótulos (gap horizontal > 10pt)
            clusters = []
            for w in line:
                if clusters and w["x0"] - clusters[-1]["x1"] <= 10:
                    clusters[-1]["text"] += " " + w["text"]
                    clusters[-1]["x1"] = w["x1"]
                else:
                    clusters.append({"text": w["text"], "x0": w["x0"], "x1": w["x1"]})
            headers = [c["text"] for c in clusters]
            col_bounds = [0.0] + [
                (clusters[i - 1]["x1"] + clusters[i]["x0"]) / 2
                for i in range(1, len(clusters))
            ]
            continue
        if _is_header_row(texts):
            continue  # cabeçalho repetido nas páginas seguintes
        cells = [""] * len(col_bounds)
        for w in line:
            idx = 0
            for i, left in enumerate(col_bounds):
                if w["x0"] >= left:
                    idx = i
            cells[idx] = (cells[idx] + " " + w["text"]).strip()
        if any(cells):
            rows.append(cells)
    return headers, col_bounds, rows


def load_pdf(uploaded_file) -> pd.DataFrame:
    """
    Lê um PDF com tabela (como o Guest Interaction Report).
    1º tenta a extração de tabelas do pdfplumber (várias estratégias);
    se o PDF não tiver tabela detetável, reconstrói as colunas a partir
    das posições das palavras no texto.
    """
    headers = None
    rows = []
    word_headers, word_bounds = None, None
    first_page_text = ""

    with pdfplumber.open(uploaded_file) as pdf:
        for page_no, page in enumerate(pdf.pages):
            if page_no == 0:
                first_page_text = page.extract_text() or ""
            tables = _extract_tables_any_strategy(page)
            if tables:
                for table in tables:
                    h_idx = _find_header_index(table)
                    if headers is None:
                        if h_idx is None:
                            continue
                        headers = [
                            _norm_cell(c) if _norm_cell(c) else f"col_{j}"
                            for j, c in enumerate(table[h_idx])
                        ]
                        data = table[h_idx + 1:]
                    else:
                        # Páginas seguintes: saltar cabeçalho repetido se existir
                        data = table[h_idx + 1:] if h_idx is not None else table
                    for r in data:
                        if r and any(_norm_cell(c) for c in r):
                            rows.append([_norm_cell(c) for c in r])
            else:
                word_headers, word_bounds, page_rows = _table_from_words(
                    page, word_headers, word_bounds
                )
                rows.extend(page_rows)

    if headers is None and word_headers:
        headers = word_headers

    if not headers or not rows:
        sample = " / ".join(
            l.strip() for l in first_page_text.split("\n")[:6] if l.strip()
        )
        raise ValueError(
            "Não foi possível extrair a tabela do PDF do GIR — nenhuma linha de "
            "cabeçalho reconhecida (procuro pelo menos 2 palavras como 'Guest Name', "
            "'Room', 'Status', 'Date'). "
            f"Início do documento: «{sample[:300]}». "
            "Se as colunas do teu GIR têm outros nomes, acrescenta-os a "
            "GIR_HEADER_KEYWORDS em config/settings.py."
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
    df = df.replace({"None": "", "nan": ""}).fillna("")
    df.columns = [_normalize_col(c) for c in df.columns]

    # Remover cabeçalhos repetidos que tenham entrado como dados (páginas 2+)
    header_names = set(df.columns)
    mask_header = df.apply(
        lambda r: sum(1 for v in r if _normalize_col(str(v)) in header_names) >= 2,
        axis=1,
    )
    df = df[~mask_header]

    # Remover linhas totalmente vazias
    df = df[df.apply(lambda r: any(str(v).strip() for v in r), axis=1)]
    return df.reset_index(drop=True)


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
