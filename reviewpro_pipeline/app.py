# app.py
"""
ReviewPro Pipeline — Aplicação Streamlit
Interface para processamento diário de check-outs e geração de ficheiros para ReviewPro.
"""

import streamlit as st
import pandas as pd
import datetime
import os
import json

from modules.loader import load_file, get_master_columns
from modules.mapper import map_vtrl_to_master, validate_required_fields
from modules.matcher import cross_with_gir
from modules.exporter import (
    export_excel_final,
    export_csv_control,
    export_reviewpro,
    export_exclusion_report,
    build_summary,
    save_history_json,
)
from config.settings import OUTPUT_COLUMNS

# ─── Configuração da página ───────────────────────────────────────────────────
st.set_page_config(
    page_title="ReviewPro Pipeline",
    page_icon="🏨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Estado da sessão ─────────────────────────────────────────────────────────
def init_state():
    defaults = {
        "master_df": None,
        "vtrl_df": None,
        "gir_df": None,
        "mapped_df": None,
        "eligible_df": None,
        "excluded_df": None,
        "suspended_df": None,
        "no_match_df": None,
        "summary": None,
        "warnings": [],
        "processing_done": False,
        "dupes_removed": 0,
        "total_vtrl": 0,
        "valid_vtrl": 0,
        # Notas manuais da equipa (edições no ecrã de revisão)
        "manual_notes": {},
        "manual_states": {},
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🏨 ReviewPro Pipeline")
    st.markdown("---")
    page = st.radio(
        "Navegação",
        [
            "📊 Dashboard",
            "📂 Importar ficheiros",
            "🔍 Revisão de matches",
            "✏️ Revisão operacional",
            "💾 Exportar",
            "📜 Histórico",
        ],
        label_visibility="collapsed",
    )
    st.markdown("---")
    if st.session_state.processing_done:
        st.success("✓ Processamento concluído")
        if st.session_state.summary:
            s = st.session_state.summary
            st.metric("Elegíveis", s.get("elegiveis_final", 0))
            st.metric("Excluídos", s.get("excluidos", 0))
            st.metric("Suspensos", s.get("suspensos", 0))
    else:
        st.info("Aguarda importação de ficheiros")

# ═══════════════════════════════════════════════════════════════════════════════
# PÁGINA 1 — DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════
if page == "📊 Dashboard":
    st.title("Dashboard")
    st.markdown(f"**Data atual:** {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}")

    if not st.session_state.processing_done:
        st.info("Ainda não foi processado nenhum lote hoje. Vai a **Importar ficheiros** para começar.")
        st.markdown("### Como funciona")
        st.markdown("""
1. **Importar ficheiros** — carrega o Master, o VTRL das 14h e o Guest Interaction Report
2. **Revisão de matches** — valida correspondências prováveis com o GIR
3. **Revisão operacional** — as guest relations reveem casos suspensos e adicionam notas
4. **Exportar** — gera Excel final, CSV e ficheiro para ReviewPro
        """)
    else:
        s = st.session_state.summary
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Total VTRL", s.get("total_vtrl", 0))
        col2.metric("Válidos", s.get("validos_apos_validacao", 0))
        col3.metric("Elegíveis", s.get("elegiveis_final", 0), delta=None)
        col4.metric("Excluídos", s.get("excluidos", 0))
        col5.metric("Suspensos", s.get("suspensos", 0))

        st.markdown("---")
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Língua PT", s.get("lingua_pt", 0))
        col_b.metric("Língua EN", s.get("lingua_en", 0))
        col_c.metric("Duplicados removidos", s.get("duplicados_removidos", 0))

        if s.get("avisos"):
            st.markdown("### ⚠️ Avisos do processamento")
            for w in s["avisos"]:
                st.warning(w)

        st.markdown("---")
        st.markdown(f"**Último processamento:** {s.get('data_processamento', '—')}")


# ═══════════════════════════════════════════════════════════════════════════════
# PÁGINA 2 — IMPORTAR FICHEIROS
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📂 Importar ficheiros":
    st.title("Importar ficheiros")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("### 1. Ficheiro Master")
        st.caption("Usado apenas como modelo de colunas")
        master_file = st.file_uploader(
            "Master", type=["xlsx", "xls", "csv"], key="master_upload",
            label_visibility="collapsed"
        )
        if master_file:
            try:
                df = load_file(master_file)
                st.session_state.master_df = df
                st.success(f"✓ Master carregado — {len(df.columns)} colunas")
                st.caption(f"Colunas: {', '.join(df.columns.tolist()[:6])}...")
            except ValueError as e:
                st.error(str(e))

    with col2:
        st.markdown("### 2. VTRL diário")
        st.caption("Lote de check-outs do dia")
        vtrl_file = st.file_uploader(
            "VTRL", type=["xlsx", "xls", "csv"], key="vtrl_upload",
            label_visibility="collapsed"
        )
        if vtrl_file:
            try:
                df = load_file(vtrl_file)
                st.session_state.vtrl_df = df
                st.success(f"✓ VTRL carregado — {len(df)} registos")
                st.caption(f"Colunas: {', '.join(df.columns.tolist()[:6])}...")
            except ValueError as e:
                st.error(str(e))

    with col3:
        st.markdown("### 3. Guest Interaction Report")
        st.caption("Relatório das guest relations")
        gir_file = st.file_uploader(
            "GIR", type=["xlsx", "xls", "csv", "pdf"], key="gir_upload",
            label_visibility="collapsed"
        )
        if gir_file:
            try:
                df = load_file(gir_file)
                st.session_state.gir_df = df
                st.success(f"✓ GIR carregado — {len(df)} registos")
                st.caption(f"Colunas: {', '.join(df.columns.tolist()[:6])}...")
            except ValueError as e:
                st.error(str(e))

    st.markdown("---")

    # Pré-visualização do mapeamento
    if st.session_state.vtrl_df is not None:
        st.markdown("### Pré-visualização do VTRL")
        st.dataframe(st.session_state.vtrl_df.head(5), use_container_width=True)

    st.markdown("---")

    # Botão de processamento
    can_process = (
        st.session_state.vtrl_df is not None
        and st.session_state.gir_df is not None
    )

    if not can_process:
        st.info("Carrega o VTRL e o GIR para poder processar. O Master é opcional mas recomendado.")

    if st.button(
        "▶ Processar lote",
        disabled=not can_process,
        type="primary",
        use_container_width=True,
    ):
        all_warnings = []

        with st.spinner("A mapear colunas do VTRL..."):
            try:
                mapped_df, mapping_found, map_warnings = map_vtrl_to_master(
                    st.session_state.vtrl_df
                )
                all_warnings.extend(map_warnings)
                st.session_state.total_vtrl = len(st.session_state.vtrl_df)
            except Exception as e:
                st.error(f"Erro no mapeamento: {e}")
                st.stop()

        with st.spinner("A validar campos obrigatórios..."):
            valid_df, invalid_df = validate_required_fields(mapped_df)
            if len(invalid_df) > 0:
                all_warnings.append(
                    f"{len(invalid_df)} registo(s) excluídos por falta de campos obrigatórios "
                    f"(nome ou data de saída)."
                )
            st.session_state.valid_vtrl = len(valid_df)

        with st.spinner("A cruzar com o Guest Interaction Report..."):
            try:
                eligible_df, excluded_df, suspended_df, no_match_df, match_warnings = cross_with_gir(
                    valid_df, st.session_state.gir_df
                )
                all_warnings.extend(match_warnings)
            except Exception as e:
                st.error(f"Erro no cruzamento com GIR: {e}")
                st.stop()

        # Contar duplicados a partir dos warnings
        dupes_removed = 0
        for w in all_warnings:
            if "duplicado" in w.lower():
                try:
                    dupes_removed = int(w.split()[0])
                except Exception:
                    pass

        # Construir lista final de elegíveis (elegíveis + sem match)
        final_eligible = pd.concat(
            [df for df in [eligible_df, no_match_df] if not df.empty],
            ignore_index=True,
        )

        pt_count = len(final_eligible[final_eligible.get("LANGUAGE", pd.Series()) == "PT"]) if not final_eligible.empty else 0
        en_count = len(final_eligible[final_eligible.get("LANGUAGE", pd.Series()) == "EN"]) if not final_eligible.empty else 0

        # Guardar em session state
        st.session_state.mapped_df = mapped_df
        st.session_state.eligible_df = final_eligible
        st.session_state.excluded_df = excluded_df
        st.session_state.suspended_df = suspended_df
        st.session_state.no_match_df = no_match_df
        st.session_state.warnings = all_warnings
        st.session_state.processing_done = True
        st.session_state.dupes_removed = dupes_removed

        summary = build_summary(
            total_vtrl=st.session_state.total_vtrl,
            valid_vtrl=st.session_state.valid_vtrl,
            eligible_count=len(final_eligible),
            excluded_count=len(excluded_df),
            suspended_count=len(suspended_df),
            no_match_count=len(no_match_df),
            dupes_removed=dupes_removed,
            pt_count=pt_count,
            en_count=en_count,
            warnings=all_warnings,
        )
        st.session_state.summary = summary

        # Guardar histórico
        os.makedirs("history", exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        save_history_json(summary, f"history/run_{ts}.json")

        st.success(
            f"✓ Processamento concluído — "
            f"{len(final_eligible)} elegíveis, "
            f"{len(excluded_df)} excluídos, "
            f"{len(suspended_df)} suspensos"
        )
        if all_warnings:
            for w in all_warnings:
                st.warning(w)


# ═══════════════════════════════════════════════════════════════════════════════
# PÁGINA 3 — REVISÃO DE MATCHES
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🔍 Revisão de matches":
    st.title("Revisão de matches com o GIR")

    if not st.session_state.processing_done:
        st.info("Processa primeiro um lote na página **Importar ficheiros**.")
        st.stop()

    tab1, tab2, tab3 = st.tabs(["Matches exactos", "Matches prováveis", "Sem match"])

    with tab1:
        eligible = st.session_state.eligible_df
        if eligible is not None and not eligible.empty:
            exact = eligible[eligible.get("_match_type", pd.Series()) == "exact"]
            if not exact.empty:
                display_cols = ["FIRST", "LAST", "ROOM", "DEPARTURE_DATE_TIME", "_match_score", "_gir_notes"]
                display_cols = [c for c in display_cols if c in exact.columns]
                st.dataframe(exact[display_cols].reset_index(drop=True), use_container_width=True)
            else:
                st.info("Nenhum match exato neste lote.")
        else:
            st.info("Sem dados de matches.")

    with tab2:
        suspended = st.session_state.suspended_df
        if suspended is not None and not suspended.empty:
            probable = suspended[suspended.get("_match_type", pd.Series()) == "probable"]
            if not probable.empty:
                st.warning(
                    f"{len(probable)} match(es) provável(is) aguardam validação manual. "
                    "Revê e decide o estado em **Revisão operacional**."
                )
                display_cols = ["FIRST", "LAST", "ROOM", "DEPARTURE_DATE_TIME", "_match_score", "_gir_notes", "_exclusion_reason"]
                display_cols = [c for c in display_cols if c in probable.columns]
                st.dataframe(probable[display_cols].reset_index(drop=True), use_container_width=True)
            else:
                st.info("Nenhum match provável neste lote.")
        else:
            st.info("Nenhum caso suspenso.")

    with tab3:
        no_match = st.session_state.no_match_df
        if no_match is not None and not no_match.empty:
            st.info(
                f"{len(no_match)} hóspede(s) sem correspondência no GIR. "
                "Tratados como elegíveis por defeito."
            )
            display_cols = ["FIRST", "LAST", "ROOM", "DEPARTURE_DATE_TIME"]
            display_cols = [c for c in display_cols if c in no_match.columns]
            st.dataframe(no_match[display_cols].reset_index(drop=True), use_container_width=True)
        else:
            st.info("Todos os hóspedes têm correspondência no GIR.")


# ═══════════════════════════════════════════════════════════════════════════════
# PÁGINA 4 — REVISÃO OPERACIONAL
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "✏️ Revisão operacional":
    st.title("Revisão operacional — Guest Relations")

    if not st.session_state.processing_done:
        st.info("Processa primeiro um lote na página **Importar ficheiros**.")
        st.stop()

    # Templates de notas rápidas
    TEMPLATES = [
        "Reclamação resolvida",
        "Aguardar feedback",
        "Follow-up necessário",
        "Não enviar questionário",
        "Apto para envio após validação",
        "Service recovery concluído",
        "Hóspede contactado — aguarda resposta",
    ]

    ESTADOS = [
        "Manter suspenso",
        "Aprovar para envio",
        "Excluir definitivamente",
        "Enviar amanhã",
        "Aguardar validação",
        "Precisa de follow-up",
    ]

    # Filtros
    st.markdown("### Filtros")
    col_f1, col_f2 = st.columns(2)
    filter_name = col_f1.text_input("Procurar por nome ou quarto", "")
    filter_status = col_f2.selectbox(
        "Estado",
        ["Todos", "Suspensos", "Excluídos"],
    )

    # Combinar suspensos e excluídos para revisão
    review_dfs = []
    if st.session_state.suspended_df is not None and not st.session_state.suspended_df.empty:
        review_dfs.append(st.session_state.suspended_df.copy())
    if st.session_state.excluded_df is not None and not st.session_state.excluded_df.empty:
        review_dfs.append(st.session_state.excluded_df.copy())

    if not review_dfs:
        st.success("✓ Nenhum caso para rever neste lote. Todos os hóspedes são elegíveis.")
        st.stop()

    review_df = pd.concat(review_dfs, ignore_index=True)

    # Aplicar filtros
    if filter_name:
        mask = (
            review_df.get("FIRST", pd.Series("")).fillna("").str.lower().str.contains(filter_name.lower(), na=False)
            | review_df.get("LAST", pd.Series("")).fillna("").str.lower().str.contains(filter_name.lower(), na=False)
            | review_df.get("ROOM", pd.Series("")).fillna("").str.lower().str.contains(filter_name.lower(), na=False)
        )
        review_df = review_df[mask]

    if filter_status == "Suspensos":
        review_df = review_df[review_df.get("_status", pd.Series()) == "suspended"]
    elif filter_status == "Excluídos":
        review_df = review_df[review_df.get("_status", pd.Series()) == "excluded"]

    if review_df.empty:
        st.info("Nenhum caso corresponde aos filtros.")
        st.stop()

    st.markdown(f"**{len(review_df)} caso(s) para rever**")
    st.markdown("---")

    # Rever cada caso
    for idx, row in review_df.iterrows():
        guest_key = f"{row.get('FIRST','')}_{row.get('LAST','')}_{row.get('ROOM','')}_{idx}"
        status_badge = "🔴 Excluído" if row.get("_status") == "excluded" else "🟡 Suspenso"

        with st.expander(
            f"{status_badge} — {row.get('FIRST','')} {row.get('LAST','')} | "
            f"Quarto {row.get('ROOM','')} | Saída {row.get('DEPARTURE_DATE_TIME','')}",
            expanded=False,
        ):
            col_info, col_action = st.columns([2, 1])

            with col_info:
                st.markdown(f"**Motivo:** {row.get('_exclusion_reason', '—')}")
                if row.get("_gir_notes"):
                    st.markdown(f"**Notas GIR:** {row.get('_gir_notes', '')}")
                st.markdown(f"**Match:** {row.get('_match_type', '—')} ({row.get('_match_score', '—')}%)")

            with col_action:
                # Seletor de estado
                current_estado = st.session_state.manual_states.get(guest_key, ESTADOS[0])
                new_estado = st.selectbox(
                    "Alterar estado",
                    ESTADOS,
                    index=ESTADOS.index(current_estado) if current_estado in ESTADOS else 0,
                    key=f"estado_{guest_key}",
                )
                st.session_state.manual_states[guest_key] = new_estado

                # Template de nota
                template = st.selectbox(
                    "Template de nota",
                    ["— selecionar —"] + TEMPLATES,
                    key=f"template_{guest_key}",
                )

                # Nota livre
                existing_note = st.session_state.manual_notes.get(guest_key, "")
                note_val = template if template != "— selecionar —" else existing_note
                note = st.text_area(
                    "Nota interna",
                    value=note_val,
                    key=f"note_{guest_key}",
                    height=80,
                )
                st.session_state.manual_notes[guest_key] = note

    if st.button("Guardar todas as alterações", type="primary"):
        st.success("✓ Alterações guardadas. Vai a **Exportar** para gerar os ficheiros finais.")


# ═══════════════════════════════════════════════════════════════════════════════
# PÁGINA 5 — EXPORTAR
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "💾 Exportar":
    st.title("Exportar")

    if not st.session_state.processing_done:
        st.info("Processa primeiro um lote na página **Importar ficheiros**.")
        st.stop()

    eligible = st.session_state.eligible_df
    excluded = st.session_state.excluded_df or pd.DataFrame()
    suspended = st.session_state.suspended_df or pd.DataFrame()

    if eligible is None or eligible.empty:
        st.error("Sem registos elegíveis para exportar.")
        st.stop()

    ts = datetime.datetime.now().strftime("%Y%m%d")

    st.markdown(f"**{len(eligible)} hóspede(s) elegíveis prontos para exportação.**")
    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Excel final")
        st.caption("Estrutura exata do master — sem formatações")
        excel_bytes = export_excel_final(eligible)
        st.download_button(
            label="⬇ Descarregar Excel final",
            data=excel_bytes,
            file_name=f"reviewpro_final_{ts}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

        st.markdown("### CSV de controlo")
        st.caption("Para validação e conferência")
        csv_bytes = export_csv_control(eligible)
        st.download_button(
            label="⬇ Descarregar CSV controlo",
            data=csv_bytes,
            file_name=f"controlo_{ts}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with col2:
        st.markdown("### Ficheiro para ReviewPro")
        st.caption("CSV UTF-8 compatível para importação")
        rp_bytes = export_reviewpro(eligible)
        st.download_button(
            label="⬇ Descarregar ficheiro ReviewPro",
            data=rp_bytes,
            file_name=f"reviewpro_import_{ts}.csv",
            mime="text/csv",
            use_container_width=True,
        )

        st.markdown("### Relatório de excluídos/suspensos")
        st.caption("Excel com motivos e notas")
        report_bytes = export_exclusion_report(excluded, suspended)
        st.download_button(
            label="⬇ Descarregar relatório",
            data=report_bytes,
            file_name=f"excluidos_suspensos_{ts}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    st.markdown("---")
    st.markdown("### Pré-visualização dos elegíveis")
    from modules.exporter import _clean_for_export
    st.dataframe(_clean_for_export(eligible)[OUTPUT_COLUMNS], use_container_width=True)

    # Resumo final
    if st.session_state.summary:
        st.markdown("---")
        st.markdown("### Resumo de execução")
        s = st.session_state.summary
        summary_text = f"""
| Métrica | Valor |
|---|---|
| Data de processamento | {s.get('data_processamento','—')} |
| Total no VTRL | {s.get('total_vtrl',0)} |
| Válidos após validação | {s.get('validos_apos_validacao',0)} |
| Elegíveis finais | {s.get('elegiveis_final',0)} |
| Excluídos | {s.get('excluidos',0)} |
| Suspensos | {s.get('suspensos',0)} |
| Sem match no GIR | {s.get('sem_match_gir',0)} |
| Duplicados removidos | {s.get('duplicados_removidos',0)} |
| Língua PT | {s.get('lingua_pt',0)} |
| Língua EN | {s.get('lingua_en',0)} |
        """
        st.markdown(summary_text)


# ═══════════════════════════════════════════════════════════════════════════════
# PÁGINA 6 — HISTÓRICO
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📜 Histórico":
    st.title("Histórico de processamentos")

    history_dir = "history"
    if not os.path.exists(history_dir):
        st.info("Ainda não há histórico de processamentos.")
        st.stop()

    history_files = sorted(
        [f for f in os.listdir(history_dir) if f.endswith(".json")],
        reverse=True,
    )

    if not history_files:
        st.info("Ainda não há histórico de processamentos.")
        st.stop()

    for fname in history_files[:20]:  # Mostrar últimos 20
        fpath = os.path.join(history_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            label = data.get("data_processamento", fname)
            with st.expander(f"Processamento: {label}"):
                col1, col2, col3 = st.columns(3)
                col1.metric("Elegíveis", data.get("elegiveis_final", 0))
                col2.metric("Excluídos", data.get("excluidos", 0))
                col3.metric("Suspensos", data.get("suspensos", 0))
                if data.get("avisos"):
                    st.markdown("**Avisos:**")
                    for w in data["avisos"]:
                        st.caption(f"• {w}")
        except Exception:
            st.caption(f"Não foi possível ler {fname}")
