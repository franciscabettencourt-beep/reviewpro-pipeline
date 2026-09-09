# modules/auth.py
"""
Porta de entrada da app: password única de equipa, guardada em segredo
(st.secrets ou variável de ambiente). A app trata dados pessoais de
hóspedes, por isso nenhuma página é servida sem a password certa.
"""

import os

import streamlit as st


def get_secret(name: str) -> str:
    """Lê um segredo do st.secrets (Streamlit Cloud) ou do ambiente (local)."""
    try:
        if name in st.secrets:
            return str(st.secrets[name]).strip()
    except Exception:
        pass
    return os.environ.get(name, "").strip()


def require_password() -> None:
    """
    Bloqueia a página até a password de equipa ser introduzida.
    Sem APP_PASSWORD configurada, a app fica aberta (uso local no hotel);
    na cloud a password deve estar SEMPRE definida nos Secrets da app.
    """
    expected = get_secret("APP_PASSWORD")
    if not expected:
        return
    if st.session_state.get("_auth_ok"):
        return

    st.markdown("## 🏨 ReviewPro Pipeline")
    st.caption("Dados pessoais de hóspedes. Acesso reservado à equipa do Vilalara.")
    with st.form("password_gate"):
        pwd = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Entrar", type="primary")
    if submitted:
        if pwd == expected:
            st.session_state._auth_ok = True
            st.rerun()
        else:
            st.error("Password errada.")
    st.stop()
