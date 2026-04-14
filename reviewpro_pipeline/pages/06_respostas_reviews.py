# pages/06_respostas_reviews.py
"""
Módulo de resposta a reviews com IA.
Tom Forbes, quiet luxury, empático e luxuoso.
Suporta EN, FR, DE, ES, PT.
"""

import streamlit as st
import requests

SYSTEM_PROMPT = """You are the Director of Guest Relations at Vilalara Thalassa Resort, a Forbes Travel Guide Five-Star property on the Algarve coast of Portugal.

Your role is to craft responses to guest reviews on behalf of the resort. Every response must reflect the following standards without exception:

TONE & VOICE
- Warm, gracious and deeply empathetic — never corporate or scripted
- Quiet luxury: understated elegance, never boastful or effusive
- Personalised: reference specific details from the review whenever possible
- Human and sincere: the guest must feel genuinely heard
- Confident but humble: acknowledge imperfections with grace

FORBES FIVE-STAR STANDARDS
- Address the guest by name if mentioned, always with courtesy title (Mr., Mrs., Dr.) when known
- Open with a sincere expression of gratitude for their time and feedback
- Acknowledge every point raised — positive and negative — with equal care
- For complaints: take ownership, apologise without deflection, explain (briefly) what has been addressed
- For praise: receive it with gracious warmth, not excessive enthusiasm
- Close with a personal, heartfelt invitation to return
- Sign off as "Director of Guest Relations" or "Guest Relations Team, Vilalara Thalassa Resort"

STYLE RULES
- Never use: "We are delighted", "We are thrilled", "Amazing", "Absolutely", "Fantastic", "No problem"
- Never use exclamation marks
- Never use bullet points or lists in the response
- Paragraphs only — flowing, warm prose
- Length: 3 to 5 paragraphs, never more
- The response must feel bespoke — never templated

LANGUAGE
- Write in the language specified. Match the register and warmth to the culture:
  - English: refined British hospitality register
  - French: élégant, chaleureux, soigné
  - German: herzlich, respektvoll, gepflegt
  - Spanish: cálido, elegante, cercano
  - Portuguese (European): caloroso, elegante, genuíno — never Brazilian Portuguese

OUTPUT
- Return only the response text, ready to publish
- No preamble, no explanation, no quotation marks around the response
"""

LANGUAGE_OPTIONS = {
    "🇬🇧 English": "English",
    "🇫🇷 Français": "French",
    "🇩🇪 Deutsch": "German",
    "🇪🇸 Español": "Spanish",
    "🇵🇹 Português": "Portuguese (European)",
}

REVIEW_TYPES = [
    "Feedback positivo",
    "Reclamação",
    "Misto (positivo e negativo)",
    "Após service recovery",
]

st.title("✍️ Respostas a reviews")
st.caption("Tom Forbes · Quiet luxury · Empático e luxuoso")
st.markdown("---")

col_left, col_right = st.columns([1, 1], gap="large")

with col_left:
    st.markdown("### Review do hóspede")

    guest_name = st.text_input(
        "Nome do hóspede (opcional)",
        placeholder="Ex: Mr. James Whitfield",
    )

    col_lang, col_type = st.columns(2)
    with col_lang:
        lang_label = st.selectbox("Língua da resposta", list(LANGUAGE_OPTIONS.keys()))
        language = LANGUAGE_OPTIONS[lang_label]
    with col_type:
        review_type = st.selectbox("Tipo de review", REVIEW_TYPES)

    rating = st.select_slider(
        "Classificação dada pelo hóspede",
        options=["1 ★", "2 ★★", "3 ★★★", "4 ★★★★", "5 ★★★★★"],
        value="5 ★★★★★",
    )

    review_text = st.text_area(
        "Texto da review",
        height=220,
        placeholder="Cola aqui o texto da review do hóspede...",
    )

    additional_context = st.text_area(
        "Contexto interno (não aparece na resposta)",
        height=80,
        placeholder="Ex: hóspede teve problema com AC no quarto 4312, resolvido no dia 2...",
    )

    generate = st.button(
        "Gerar resposta",
        type="primary",
        use_container_width=True,
        disabled=not review_text.strip(),
    )

with col_right:
    st.markdown("### Resposta gerada")

    if "generated_response" not in st.session_state:
        st.session_state.generated_response = ""

    if generate and review_text.strip():
        user_prompt = f"""Please write a response to the following guest review.

Language: {language}
Review type: {review_type}
Guest rating: {rating}
{f"Guest name: {guest_name}" if guest_name.strip() else "Guest name: not provided"}
{f"Internal context (do not include in response, use only to inform tone): {additional_context}" if additional_context.strip() else ""}

Guest review:
{review_text}"""

        with st.spinner("A redigir resposta..."):
            try:
                resp = requests.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"Content-Type": "application/json"},
                    json={
                        "model": "claude-sonnet-4-20250514",
                        "max_tokens": 1000,
                        "system": SYSTEM_PROMPT,
                        "messages": [{"role": "user", "content": user_prompt}],
                    },
                    timeout=30,
                )
                data = resp.json()
                if "content" in data and data["content"]:
                    st.session_state.generated_response = data["content"][0]["text"]
                else:
                    st.error("Não foi possível gerar resposta. Tenta novamente.")
                    st.session_state.generated_response = ""
            except Exception as e:
                st.error(f"Erro ao contactar a IA: {e}")
                st.session_state.generated_response = ""

    if st.session_state.generated_response:
        edited = st.text_area(
            "Revê e ajusta antes de publicar",
            value=st.session_state.generated_response,
            height=400,
        )

        col_copy, col_regen = st.columns(2)
        with col_copy:
            st.download_button(
                label="⬇ Descarregar resposta",
                data=edited,
                file_name="resposta_review.txt",
                mime="text/plain",
                use_container_width=True,
            )
        with col_regen:
            if st.button("↺ Gerar nova versão", use_container_width=True):
                st.session_state.generated_response = ""
                st.rerun()

        st.markdown("---")
        st.caption(
            "Revê sempre a resposta antes de publicar. "
            "A IA pode cometer erros ou omitir detalhes importantes."
        )
    else:
        st.markdown(
            """
            <div style="
                border: 1px dashed var(--color-border-tertiary);
                border-radius: 8px;
                padding: 48px 32px;
                text-align: center;
                color: var(--color-text-tertiary);
            ">
                <p style="margin: 0; font-size: 15px;">
                    Cola a review à esquerda e clica em <strong>Gerar resposta</strong>
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
