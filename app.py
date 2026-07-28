import streamlit as st
import fitz  # PyMuPDF
import re
import json
import random
import google.generativeai as genai
from collections import defaultdict

# ==================== CONFIGURAÇÃO DA PÁGINA ====================
st.set_page_config(page_title="Agente de Estudos Pro", layout="wide", initial_sidebar_state="expanded")

if 'dark_mode' not in st.session_state:
    st.session_state.dark_mode = False

def apply_theme():
    if st.session_state.dark_mode:
        dark_css = """
        <style>
        .stApp { background-color: #1e1e1e; color: #e0e0e0; }
        .stTextInput, .stTextArea, .stNumberInput, .stSlider, .stFileUploader, .stSelectbox {
            background-color: #2d2d2d; color: #e0e0e0; }
        .stMarkdown, .stCaption, .stInfo, .stSuccess, .stWarning, .stError { color: #e0e0e0; }
        .stButton button { background-color: #4a4a4a; color: #ffffff; }
        .stTabs [data-baseweb="tab"] { color: #e0e0e0; }
        .stExpander { background-color: #2d2d2d; }
        </style>"""
        st.markdown(dark_css, unsafe_allow_html=True)

apply_theme()

# ==================== CONEXÃO GEMINI (À Prova de 404) ====================
def get_gemini_model():
    api_key = st.session_state.get("api_key", "")
    if not api_key:
        api_key = st.secrets.get("GEMINI_API_KEY", "")
    if not api_key:
        st.error("⚠️ Chave da API do Google Gemini não configurada. Insira na barra lateral.")
        st.stop()
        
    genai.configure(api_key=api_key)
    
    # Busca dinamicamente os modelos disponíveis para evitar o erro "404 Not Found"
    modelos_disponiveis = []
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                nome_limpo = m.name.replace("models/", "")
                modelos_disponiveis.append(nome_limpo)
                
        modelo_escolhido = None
        for m in modelos_disponiveis:
            if "flash" in m:
                modelo_escolhido = m
                break
                
        if not modelo_escolhido:
            for m in modelos_disponiveis:
                if "pro" in m:
                    modelo_escolhido = m
                    break
                    
        if not modelo_escolhido and modelos_disponiveis:
            modelo_escolhido = modelos_disponiveis[0]
            
        return genai.GenerativeModel(modelo_escolhido)
        
    except Exception as e:
        st.error(f"Erro ao buscar lista de modelos do Google: {e}")
        st.stop()

def llm_generate(prompt):
    try:
        model = get_gemini_model()
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        st.error(f"Erro na API do Gemini: {e}")
        return ""

# ==================== EXTRAÇÃO DE PDF ====================
def extract_text_from_pdf(file_bytes):
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text("text") + "\n"
        doc.close()
        text = re.sub(r'\n+', '\n', text)
        return text
    except Exception as e:
        st.error(f"Erro ao ler PDF: {e}")
        return ""

# ==================== FUNÇÕES DE IA ====================
def generate_structured_summary(text, custom_instruction=""):
    extra = f"\n\nInstrução adicional do usuário: {custom_instruction}" if custom_instruction else ""
    prompt = f"""
Crie um resumo ESQUEMATIZADO e COMPLETO do texto a seguir.
- Organize em tópicos e subtópicos.
- NÃO omita detalhes importantes (datas, prazos, fórmulas, exceções, exemplos).
- Destaque **atualizações jurídicas recentes** e 💡 **dicas de professores**.{extra}
- Seja fiel ao texto original.

Texto completo:
{text}

Resumo Esquematizado:"""
    
    return llm_generate(prompt)

def generate_flashcards(text, num_cards=30):
    prompt_cards = f"""
Baseado no texto abaixo, crie EXATAMENTE {num_cards} flashcards para estudo. Foque nos pontos cruciais.

Texto completo:
{text}

RETORNE APENAS UM ARRAY JSON VÁLIDO. NÃO ESCREVA MAIS NADA ALÉM DO JSON.
Formato obrigatório:
[
  {{"frente": "Afirmação que pode ser verdadeira ou falsa", "verso": "Certo/Errado. Explicação curta..."}},
  {{"frente": "Outra afirmação...", "verso": "Certo/Errado. Explicação..."}}
]
"""
    result = llm_generate(prompt_cards)
    
    try:
        clean_json = result.strip().strip("```json").strip("```").strip()
        cards = json.loads(clean_json)
        return cards[:num_cards]
    except json.JSONDecodeError:
        st.error("Falha ao interpretar os flashcards. A IA não retornou o formato correto. Tente novamente.")
        return []

def extract_topics(text):
    prompt = f"""Identifique os principais tópicos do texto abaixo. 
Retorne APENAS um array JSON de strings, com no máximo 8 tópicos. Exemplo: ["Direito Civil", "Prazos", "Recursos"].

Texto completo:
{text}"""
    
    resposta = llm_generate(prompt)
    try:
        clean_json = resposta.strip().strip("```json").strip("
