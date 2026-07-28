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

# ==================== CONEXÃO GEMINI ====================
def get_gemini_model():
    api_key = st.session_state.get("api_key", "")
    if not api_key:
        # Tenta pegar das configurações de Secrets do Streamlit Cloud
        api_key = st.secrets.get("GEMINI_API_KEY", "")
    if not api_key:
        st.error("⚠️ Chave da API do Google Gemini não configurada. Insira na barra lateral.")
        st.stop()
        
    genai.configure(api_key=api_key)
    # gemini-1.5-flash é super rápido e suporta milhões de tokens (lê PDFs inteiros)
    return genai.GenerativeModel('gemini-1.5-flash')

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
        # Limpeza básica de quebras de linha em excesso
        text = re.sub(r'\n+', '\n', text)
        return text
    except Exception as e:
        st.error(f"Erro ao ler PDF: {e}")
        return ""

# ==================== FUNÇÕES DE IA (GEMINI LENDO TUDO) ====================
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
        st.error("Falha ao interpretar os flashcards. A IA não retornou o formato correto.")
        return []

def extract_topics(text):
    prompt = f"""Identifique os principais tópicos do texto abaixo. 
Retorne APENAS um array JSON de strings, com no máximo 8 tópicos. Exemplo: ["Direito Civil", "Prazos", "Recursos"].

Texto completo:
{text}"""
    
    resposta = llm_generate(prompt)
    try:
        clean_json = resposta.strip().strip("```json").strip("```").strip()
        topicos = json.loads(clean_json)
        return topicos[:8] if topicos else ["Geral"]
    except:
        return ["Geral"]

def extract_questions_by_topic(text, topic, num_questions, banca=None):
    filtro = f"Estilo da banca {banca}. " if banca else ""
    prompt = f"""
Crie EXATAMENTE {num_questions} questões de múltipla escolha baseadas no texto abaixo sobre o tópico "{topic}". {filtro}
O formato DEVE ser exatamente este (separado por ---):

---
Enunciado: [Texto da questão]
Alternativas:
a) ...
b) ...
c) ...
d) ...
e) ...
Gabarito: [Apenas a letra, ex: C]
---

Texto completo:
{text}
"""
    result = llm_generate(prompt)
    questoes = [bloco.strip() for bloco in result.split('---') if 'Enunciado:' in bloco]
    return questoes[:num_questions]

# ==================== ESTADO DA APLICAÇÃO ====================
if 'notebooks' not in st.session_state:
    st.session_state.notebooks = {}
if 'active_notebook' not in st.session_state:
    st.session_state.active_notebook = None
if 'show_delete_confirm' not in st.session_state:
    st.session_state.show_delete_confirm = None

# ==================== INTERFACE ====================
st.title("📚 Agente de Estudos Pro — Online (Gemini)")

with st.sidebar:
    st.header("🎨 Aparência")
    dark = st.checkbox("Modo escuro", value=st.session_state.dark_mode)
    if dark != st.session_state.dark_mode:
        st.session_state.dark_mode = dark
        st.rerun()

    st.markdown("---")
    st.header("🔑 API Gemini")
    api_key = st.text_input("Chave da API Google Gemini", type="password")
    if api_key:
        st.session_state.api_key = api_key
    if st.button("Salvar chave"):
        st.success("Chave salva para esta sessão.")
    st.info("Obtenha sua chave gratuita em https://aistudio.google.com/app/apikey")
    st.markdown("---")

    st.header("📓 Notebooks")
    novo = st.text_input("Novo notebook")
    if st.button("➕ Criar") and novo:
        if novo not in st.session_state.notebooks:
            st.session_state.notebooks[novo] = {"pdfs": [], "texto": "", "topicos": []}
            st.success(f"'{novo}' criado!")
            st.rerun()
        else:
            st.error("Já existe um notebook com este nome.")

    nomes = list(st.session_state.notebooks.keys())
    if nomes:
        if st.session_state.active_notebook not in nomes:
            st.session_state.active_notebook = nomes[0]
        active = st.selectbox("Notebook Ativo", nomes, key="active_notebook_selector")
        st.session_state.active_notebook = active
        st.markdown("---")
        with st.expander("⚙️ Gerenciar"):
            if st.button("🗑️ Apagar"):
                if st.session_state.show_delete_confirm != active:
                    st.session_state.show_delete_confirm = active
                    st.warning("Clique novamente para confirmar exclusão.")
                else:
                    del st.session_state.notebooks[active]
                    st.session_state.show_delete_confirm = None
                    if st.session_state.active_notebook == active:
                        st.session_state.active_notebook = None
                    st.success("Apagado.")
                    st.rerun()
    else:
        st.info("Crie um notebook para começar.")
        st.stop()

if not st.session_state.active_notebook:
    st.stop()

active = st.session_state.active_notebook
st.subheader(f"📖 Notebook: {active}")

# Upload de PDF
uploaded = st.file_uploader("Arraste PDFs (texto selecionável)", type="pdf", accept_multiple_files=True, key=f"upload_{active}")
if uploaded:
    for f in uploaded:
        if f.name not in st.session_state.notebooks[active]['pdfs']:
            with st.spinner(f"Lendo {f.name}..."):
                txt = extract_text_from_pdf(f.read())
                if txt.strip():
                    st.session_state.notebooks[active]['pdfs'].append(f.name)
                    st.session_state.notebooks[active]['texto'] += txt + "\n\n"
                    st.success(f"✅ {f.name} carregado!")
                else:
                    st.error(f"❌ {f.name} não tem texto extraível. Use um PDF selecionável.")
    
    if st.session_state.notebooks[active]['texto']:
        with st.spinner("Identificando tópicos..."):
            st.session_state.notebooks[active]['topicos'] = extract_topics(st.session_state.notebooks[active]['texto'])

if st.session_state.notebooks[active]['pdfs']:
    st.caption(f"📚 PDFs carregados: {', '.join(st.session_state.notebooks[active]['pdfs'])}")
    if st.button("🗑️ Limpar PDFs"):
        st.session_state.notebooks[active] = {"pdfs": [], "texto": "", "topicos": []}
        st.rerun()
else:
    st.warning("⬆️ Nenhum PDF carregado neste notebook ainda.")

texto_atual = st.session_state.notebooks[active]['texto']

# Tabs principais
tab1, tab2, tab3, tab4 = st.tabs(["📝 Resumo", "🃏 Flashcards", "❓ Questões", "🎯 Revisão"])

with tab1:
    custom = st.text_area("Instruções adicionais (opcional):", placeholder="Ex: Destaque os prazos processuais e faça tabelas...", key="custom")
    if st.button("🚀 Gerar Resumo"):
        if texto_atual:
            with st.spinner("O Gemini está analisando o documento completo..."):
                st.session_state['resumo'] = generate_structured_summary(texto_atual, custom)
            st.success("Resumo gerado!")
        else:
            st.error("Por favor, carregue um PDF primeiro.")
    
    if 'resumo' in st.session_state:
        st.markdown(st.session_state['resumo'])

with tab2:
    st.subheader("Flashcards de Revisão (Certo/Errado)")
    n = st.slider("Quantidade (Máximo 50)", 5, 50, 15, 5)
    
    if st.button("Gerar Flashcards"):
        if texto_atual:
            with st.spinner("Criando cards interativos..."):
                st.session_state['flashcards'] = generate_flashcards(texto_atual, n)
                st.session_state['card_idx'] = 0
            if st.session_state.get('flashcards'):
                st.success(f"{len(st.session_state['flashcards'])} cards gerados com sucesso.")
        else:
            st.error("Sem PDF carregado.")
            
    if 'flashcards' in st.session_state and st.session_state['flashcards']:
        cards = st.session_state['flashcards']
        idx = st.session_state.get('card_idx', 0)
        
        if idx < len(cards):
            card = cards[idx]
            st.markdown(f"### Card {idx+1} de {len(cards)}")
            
            with st.container(border=True):
                st.markdown(f"**{card.get('frente', 'Erro ao carregar frente')}**")
            
            with st.expander("Mostrar Resposta"):
                verso = card.get('verso', 'Erro ao carregar verso')
                if verso.upper().startswith("CERTO"):
                    st.success(verso)
                elif verso.upper().startswith("ERRADO"):
                    st.error(verso)
                else:
                    st.info(verso)
            
            c1, c2, c3 = st.columns([1,2,1])
            if c1.button("⬅️ Anterior") and idx > 0:
                st.session_state['card_idx'] -= 1
                st.rerun()
            if c3.button("Próximo ➡️") and idx < len(cards)-1:
                st.session_state['card_idx'] += 1
                st.rerun()

with tab3:
    st.subheader("Bateria de Questões Inéditas")
    if not texto_atual:
        st.error("Carregue um PDF para gerar questões.")
    else:
        topicos = st.session_state.notebooks[active].get('topicos', ["Geral"])
        banca = st.text_input("Simular estilo da banca (opcional)", placeholder="Ex: CEBRASPE, FGV, VUNESP")
        total = st.number_input("Total de questões desejadas", 1, 30, 5)
        
        st.write("Distribuição (Selecione de quais tópicos deseja as questões):")
        sliders = {}
        cols = st.columns(min(len(topicos), 4)) 
        for i, t in enumerate(topicos[:4]):
            with cols[i]:
                sliders[t] = st.slider(t, 0, total, 0, key=f"sl_{t}")
                
        soma = sum(sliders.values())
        if soma != total:
            st.warning(f"A soma das questões selecionadas ({soma}) deve ser igual ao total ({total}).")
        else:
            if st.button("Iniciar Quiz"):
                quiz = []
                with st.spinner("O Gemini está elaborando as questões..."):
                    for t, q in sliders.items():
                        if q > 0:
                            quiz += extract_questions_by_topic(texto_atual, t, q, banca if banca else None)
                
                if quiz:
                    random.shuffle(quiz)
                    st.session_state['quiz'] = quiz
                    st.session_state['q_idx'] = 0
                    st.session_state['respostas'] = []
                    st.session_state['gabaritos'] = []
                    st.session_state['quiz_fim'] = False
                    st.rerun()
                else:
                    st.error("Não foi possível gerar as questões. Tente novamente.")
                    
        if 'quiz' in st.session_state and st.session_state['quiz'] and not st.session_state.get('quiz_fim', False):
            idx = st.session_state['q_idx']
            q_texto = st.session_state['quiz'][idx]
            
            st.markdown(f"### Questão {idx+1}/{len(st.session_state['quiz'])}")
            
            # Oculta o gabarito no momento de responder
            display_q = re.sub(r'Gabarito:.*', '', q_texto, flags=re.IGNORECASE)
            st.markdown(display_q)
            
            alt = re.findall(r'([a-e])\)\s*(.*)', q_texto)
            gab = re.search(r'Gabarito:\s*([a-eA-E])', q_texto)
            gab_letra = gab.group(1).upper() if gab else None
            
            resp = st.radio("Sua resposta:", [a[0].upper() for a in alt] if alt else ["A","B","C","D","E"], key=f"resp_{idx}")
            
            if st.button("Confirmar e ir para próxima", key=f"prox_{idx}"):
                st.session_state['respostas'].append(resp)
                st.session_state['gabaritos'].append(gab_letra)
                if idx+1 < len(st.session_state['quiz']):
                    st.session_state['q_idx'] += 1
                else:
                    st.session_state['quiz_fim'] = True
                st.rerun()
                
        elif st.session_state.get('quiz_fim'):
            st.success("Quiz finalizado! Veja seu desempenho.")
            acertos = 0
            for i, q in enumerate(st.session_state['quiz']):
                r_user = st.session_state['respostas'][i] if i < len(st.session_state['respostas']) else None
                gab = st.session_state['gabaritos'][i]
                if r_user and gab and r_user == gab:
                    acertos += 1
            
            total_q = len(st.session_state['quiz'])
            st.metric("Acertos", f"{acertos}/{total_q}", f"{(acertos/total_q)*100:.0f}%")
            if acertos < total_q:
                st.session_state['topicos_revisar'] = topicos[:1] 
                st.info("Alguns erros detectados. Vá para a aba 'Revisão'.")
            
            if st.button("Limpar e Tentar Novamente"):
                del st.session_state['quiz']
                st.rerun()

with tab4:
    st.subheader("Revisão Inteligente dos Erros")
    if st.button("Gerar material de revisão"):
        if not texto_atual:
            st.warning("Carregue um texto primeiro.")
        else:
            erros = st.session_state.get('topicos_revisar', st.session_state.notebooks[active].get('topicos', ['Geral'])[:1])
            with st.spinner("Criando resumo de reforço com o Gemini..."):
                for top in erros:
                    st.markdown(f"### 📌 Reforço de Conteúdo: {top}")
                    prompt = f"Crie um resumo rápido e focado apenas no assunto '{top}'. Texto base: {texto_atual}"
                    st.markdown(llm_generate(prompt))
            st.success("Material de revisão gerado!")
