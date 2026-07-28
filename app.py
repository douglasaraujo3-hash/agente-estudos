import streamlit as st
import fitz  # PyMuPDF
import re
import json
import random
import time
import google.generativeai as genai

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

# ==================== CONEXÃO GEMINI ====================
def get_gemini_model():
    api_key = st.session_state.get("api_key", "")
    if not api_key:
        api_key = st.secrets.get("GEMINI_API_KEY", "")
    if not api_key:
        st.error("⚠️ Chave da API do Google Gemini não configurada. Insira na barra lateral.")
        st.stop()
        
    genai.configure(api_key=api_key)
    
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
        st.error(f"Erro ao buscar lista de modelos: {e}")
        st.stop()

# ==================== GERAÇÃO COM PAUSA ESTRATÉGICA ====================
def llm_generate(prompt):
    tentativas = 3
    for i in range(tentativas):
        try:
            model = get_gemini_model()
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            erro_str = str(e)
            if "429" in erro_str or "Quota" in erro_str:
                if i < tentativas - 1:
                    st.toast("⏳ O Google pediu uma pausa (plano gratuito). Retomando em 30 segundos...", icon="⏳")
                    time.sleep(32)
                else:
                    st.error("⚠️ Limite do minuto esgotado. Aguarde um pouco e clique novamente.")
                    return ""
            else:
                st.error(f"Erro inesperado: {e}")
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

# ==================== FUNÇÕES DE IA (SOB DEMANDA) ====================
def generate_structured_summary(text, comando_especifico=""):
    foco = f"Foque EXCLUSIVAMENTE neste comando/assunto: {comando_especifico}" if comando_especifico else "Faça um resumo geral dos pontos principais."
    
    prompt = f"""
Você é um assistente de estudos. 
{foco}

- Organize em tópicos e subtópicos claros.
- Destaque termos importantes e conceitos chave.
- Seja fiel ao texto fornecido.

Texto base para a busca:
{text}

Resposta:"""
    return llm_generate(prompt)

def generate_flashcards(text, assunto="", num_cards=10):
    foco = f"Foque APENAS neste assunto/comando: {assunto}" if assunto else "Gere os cards sobre os pontos mais importantes do texto."
    
    prompt_cards = f"""
Você é um criador de flashcards.
{foco}

Crie EXATAMENTE {num_cards} flashcards Certo/Errado baseados no texto.
RETORNE APENAS UM ARRAY JSON VÁLIDO. NÃO ESCREVA MAIS NADA ALÉM DO JSON.
Formato obrigatório:
[
  {{"frente": "Afirmação que pode ser verdadeira ou falsa", "verso": "Certo/Errado. Explicação..."}}
]

Texto base:
{text}
"""
    result = llm_generate(prompt_cards)
    if not result:
        return []
    try:
        clean_json = result.strip().strip("```json").strip("```").strip()
        cards = json.loads(clean_json)
        return cards[:num_cards]
    except json.JSONDecodeError:
        st.error("Falha ao interpretar os flashcards. Tente simplificar o comando.")
        return []

def extract_questions_by_topic(text, topic, num_questions, banca=None):
    filtro_banca = f"Simule o estilo da banca {banca}." if banca else ""
    foco = f"O tema EXCLUSIVO das questões deve ser: '{topic}'" if topic else "Crie questões variadas sobre o texto."
    
    prompt = f"""
Crie EXATAMENTE {num_questions} questões de múltipla escolha baseadas no texto abaixo. 
{foco}
{filtro_banca}

O formato DEVE ser exatamente este (separado por ---):

---
Enunciado: [Texto da questão]
Alternativas:
a) ...
b) ...
c) ...
d) ...
e) ...
Gabarito: [Letra]
---

Texto base:
{text}
"""
    result = llm_generate(prompt)
    if not result:
        return []
    questoes = [bloco.strip() for bloco in result.split('---') if 'Enunciado:' in bloco]
    return questoes[:num_questions]

# ==================== ESTADO DA APLICAÇÃO ====================
if 'notebooks' not in st.session_state:
    st.session_state.notebooks = {}
if 'active_notebook' not in st.session_state:
    st.session_state.active_notebook = None

# ==================== INTERFACE ====================
st.title("📚 Agente de Estudos Pro — Modo Direto")
st.caption("A IA só lê e processa o documento quando você dá um comando, economizando seus limites grátis.")

with st.sidebar:
    st.header("🎨 Aparência")
    dark = st.checkbox("Modo escuro", value=st.session_state.dark_mode)
    if dark != st.session_state.dark_mode:
        st.session_state.dark_mode = dark
        st.rerun()

    st.markdown("---")
    st.header("🔑 API Gemini")
    api_key = st.text_input("Chave da API", type="password")
    if api_key:
        st.session_state.api_key = api_key
    if st.button("Salvar chave"):
        st.success("Chave salva!")
    st.markdown("---")

    st.header("📓 Notebooks")
    novo = st.text_input("Novo notebook")
    if st.button("➕ Criar") and novo:
        if novo not in st.session_state.notebooks:
            st.session_state.notebooks[novo] = {"pdfs": [], "texto": ""}
            st.success("Criado!")
            st.rerun()

    nomes = list(st.session_state.notebooks.keys())
    if nomes:
        active = st.selectbox("Ativo", nomes)
        st.session_state.active_notebook = active
    else:
        st.info("Crie um notebook para começar.")
        st.stop()

if not st.session_state.active_notebook:
    st.stop()

active = st.session_state.active_notebook

# Upload de PDF (Agora ele SÓ extrai o texto, não analisa nada no fundo)
uploaded = st.file_uploader(f"Carregar PDFs no notebook '{active}'", type="pdf", accept_multiple_files=True)
if uploaded:
    for f in uploaded:
        if f.name not in st.session_state.notebooks[active]['pdfs']:
            with st.spinner(f"Extraindo texto de {f.name}..."):
                txt = extract_text_from_pdf(f.read())
                if txt.strip():
                    st.session_state.notebooks[active]['pdfs'].append(f.name)
                    st.session_state.notebooks[active]['texto'] += txt + "\n\n"
                    st.success(f"✅ {f.name} carregado!")

# Corte de segurança para o plano gratuito (Limita a ~50 páginas por vez)
texto_completo = st.session_state.notebooks[active].get('texto', "")
texto_seguro = texto_completo[:150000]

if len(texto_completo) > 150000:
    st.info("💡 PDF muito longo! Para evitar bloqueio do Google gratuito, a IA analisará o limite máximo de segurança por vez (cerca de 50 páginas).")

if not texto_seguro:
    st.warning("Nenhum texto carregado. Faça upload de um PDF.")
    st.stop()

# Tabs de Comando Direto
tab1, tab2, tab3, tab4 = st.tabs(["📝 Resumo Sob Demanda", "🃏 Flashcards Direcionados", "❓ Questões Específicas", "💬 Consulta Livre (Chat)"])

with tab1:
    st.subheader("Resumir partes específicas")
    comando_resumo = st.text_input("O que você quer que a IA busque e resuma?", placeholder="Ex: Resuma as hipóteses de prisão preventiva")
    if st.button("🚀 Gerar Resumo Direcionado"):
        with st.spinner("Buscando no texto..."):
            st.session_state['resumo'] = generate_structured_summary(texto_seguro, comando_resumo)
    if 'resumo' in st.session_state:
        st.markdown(st.session_state['resumo'])

with tab2:
    st.subheader("Gerador de Flashcards")
    comando_flash = st.text_input("Sobre qual assunto do PDF você quer os flashcards?", placeholder="Ex: Apenas sobre prazos processuais")
    n = st.slider("Quantidade de Cards", 5, 30, 10, 5)
    
    if st.button("Gerar Flashcards"):
        with st.spinner("Extraindo e criando os cards..."):
            st.session_state['flashcards'] = generate_flashcards(texto_seguro, comando_flash, n)
            st.session_state['card_idx'] = 0
            
    if 'flashcards' in st.session_state and st.session_state['flashcards']:
        cards = st.session_state['flashcards']
        idx = st.session_state.get('card_idx', 0)
        
        if idx < len(cards):
            card = cards[idx]
            st.markdown(f"### Card {idx+1} de {len(cards)}")
            with st.container(border=True):
                st.markdown(f"**{card.get('frente', '')}**")
            with st.expander("Mostrar Resposta"):
                st.write(card.get('verso', ''))
            
            c1, c2, c3 = st.columns([1,2,1])
            if c1.button("⬅️ Anterior") and idx > 0:
                st.session_state['card_idx'] -= 1
                st.rerun()
            if c3.button("Próximo ➡️") and idx < len(cards)-1:
                st.session_state['card_idx'] += 1
                st.rerun()

with tab3:
    st.subheader("Questões Sob Medida")
    comando_questoes = st.text_input("Qual assunto exato você quer testar?", placeholder="Ex: Licitações e Contratos")
    banca = st.text_input("Estilo da banca (opcional)", placeholder="Ex: FGV, VUNESP")
    total = st.number_input("Total de questões desejadas", 1, 20, 5)
    
    if st.button("Iniciar Busca e Criar Quiz"):
        with st.spinner("A IA está buscando esse assunto no PDF..."):
            quiz = extract_questions_by_topic(texto_seguro, comando_questoes, total, banca)
            if quiz:
                st.session_state['quiz'] = quiz
                st.session_state['q_idx'] = 0
                st.session_state['respostas'] = []
                st.session_state['gabaritos'] = []
                st.session_state['quiz_fim'] = False
                st.rerun()
            else:
                st.warning("Não achei esse assunto ou ocorreu um erro.")
                
    if 'quiz' in st.session_state and st.session_state['quiz'] and not st.session_state.get('quiz_fim', False):
        idx = st.session_state['q_idx']
        q_texto = st.session_state['quiz'][idx]
        
        st.markdown(f"### Questão {idx+1}/{len(st.session_state['quiz'])}")
        display_q = re.sub(r'Gabarito:.*', '', q_texto, flags=re.IGNORECASE)
        st.markdown(display_q)
        
        alt = re.findall(r'([a-e])\)\s*(.*)', q_texto)
        gab = re.search(r'Gabarito:\s*([a-eA-E])', q_texto)
        gab_letra = gab.group(1).upper() if gab else None
        
        resp = st.radio("Sua resposta:", [a[0].upper() for a in alt] if alt else ["A","B","C","D","E"], key=f"resp_{idx}")
        if st.button("Confirmar", key=f"prox_{idx}"):
            st.session_state['respostas'].append(resp)
            st.session_state['gabaritos'].append(gab_letra)
            if idx+1 < len(st.session_state['quiz']):
                st.session_state['q_idx'] += 1
            else:
                st.session_state['quiz_fim'] = True
            st.rerun()
            
    elif st.session_state.get('quiz_fim'):
        acertos = sum(1 for i, q in enumerate(st.session_state['quiz']) if i < len(st.session_state['respostas']) and st.session_state['respostas'][i] == st.session_state['gabaritos'][i])
        total_q = len(st.session_state['quiz'])
        st.success("Quiz finalizado!")
        st.metric("Acertos", f"{acertos}/{total_q}", f"{(acertos/total_q)*100:.0f}%")
        if st.button("Fazer novo Quiz"):
            del st.session_state['quiz']
            st.rerun()

with tab4:
    st.subheader("💬 Consulta Livre (Converse com o PDF)")
    st.write("Tem uma dúvida pontual? Digite abaixo e a IA vai buscar a resposta dentro do PDF.")
    pergunta_direta = st.text_input("Faça uma pergunta sobre o texto:")
    
    if st.button("Buscar resposta no PDF"):
        if pergunta_direta:
            with st.spinner("Procurando..."):
                prompt = f"Responda a esta pergunta baseando-se EXCLUSIVAMENTE no texto abaixo. Pergunta: {pergunta_direta}\n\nTexto:\n{texto_seguro}"
                st.info(llm_generate(prompt))
        else:
            st.warning("Digite uma pergunta primeiro.")
