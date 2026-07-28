import streamlit as st
import fitz  # PyMuPDF
import re
from groq import Groq  # pip install groq
from collections import defaultdict
import random
import json

# ==================== CONFIGURAÇÃO DA PÁGINA ====================
st.set_page_config(page_title="Agente de Estudos Pro", layout="wide", initial_sidebar_state="expanded")

# ==================== MODO ESCURO ====================
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

# ==================== CONEXÃO GROQ ====================
def get_groq_client():
    api_key = st.session_state.get("groq_api_key", "")
    if not api_key:
        api_key = st.secrets.get("GROQ_API_KEY", "")
    if not api_key:
        st.error("⚠️ Chave da API Groq não configurada. Insira na barra lateral.")
        st.stop()
    return Groq(api_key=api_key)

def llm_generate(prompt, max_tokens=2000, temperature=0.1, model="llama-3.1-8b-instant"):
    try:
        client = get_groq_client()
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"Erro na API Groq: {e}")
        return ""

# ==================== EXTRAÇÃO DE PDF ====================
def extract_text_from_pdf(file_bytes):
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text

# ==================== FUNÇÕES DE IA ====================
def generate_structured_summary(text, custom_instruction=""):
    chunk_size = 60000
    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    summaries = []
    for i, chunk in enumerate(chunks):
        extra = f"\n\nInstrução adicional do usuário: {custom_instruction}" if custom_instruction else ""
        prompt = f"""
Crie um resumo ESQUEMATIZADO e COMPLETO do texto a seguir.
- Organize em tópicos e subtópicos.
- NÃO omita detalhes importantes (datas, prazos, fórmulas, exceções, exemplos).
- Destaque **atualizações jurídicas recentes** e 💡 **dicas de professores**.{extra}
- Seja fiel ao texto original.

Texto (parte {i+1} de {len(chunks)}):
{chunk}

Resumo Esquematizado:"""
        summaries.append(llm_generate(prompt, max_tokens=3000))
    return "\n\n".join(summaries)

def generate_flashcards(text, num_cards=70, check_coverage=False):
    prompt_extract = f"Liste TODOS os pontos importantes do texto abaixo que podem cair em prova. Seja exaustivo.\n\nTexto:\n{text[:120000]}\n\nLista:"
    pontos = llm_generate(prompt_extract, max_tokens=3000)

    prompt_cards = f"""A partir da lista de pontos abaixo, crie EXATAMENTE {num_cards} flashcards no formato:
Frente: [afirmação clara que pode ser verdadeira ou falsa]
Verso: [Certo ou Errado] + explicação completa + uma mini revisão do assunto (2-3 frases resumindo o conceito)

Regras:
- Mescle pontos relacionados, mas NÃO omita informações.
- Garanta que o total seja exatamente {num_cards}.
- Apenas os flashcards, sem texto adicional.

Lista de pontos:
{pontos}

Flashcards ({num_cards}):"""
    result = llm_generate(prompt_cards, max_tokens=4000)

    cards = []
    pattern = r"Frente:\s*(.*?)\nVerso:\s*(.*?)(?=\nFrente:|\Z)"
    for match in re.findall(pattern, result, re.DOTALL):
        frente, verso = match[0].strip(), match[1].strip()
        if not (verso.startswith("Certo") or verso.startswith("Errado")):
            if "certo" in verso.lower():
                verso = "Certo " + verso
            elif "errado" in verso.lower():
                verso = "Errado " + verso
        cards.append({"frente": frente, "verso": verso})

    if len(cards) > num_cards:
        cards = cards[:num_cards]
    elif len(cards) < num_cards:
        extra = llm_generate(f"Ainda faltam {num_cards - len(cards)} flashcards. Gere-os.", max_tokens=1000)
        for match in re.findall(pattern, extra, re.DOTALL):
            cards.append({"frente": match[0].strip(), "verso": match[1].strip()})
        cards = cards[:num_cards]

    if check_coverage and cards:
        with st.spinner("Verificando cobertura..."):
            prompt_verify = f"""
Analise o texto original e a lista de flashcards abaixo.
Se algum ponto importante foi omitido, crie flashcards adicionais (até 20).

Texto original:
{text[:120000]}

Flashcards atuais:
{json.dumps(cards, ensure_ascii=False, indent=2)}

Flashcards adicionais (se necessário):"""
            verification = llm_generate(prompt_verify, max_tokens=1000)
            for match in re.findall(pattern, verification, re.DOTALL):
                cards.append({"frente": match[0].strip(), "verso": match[1].strip()})
            max_total = int(num_cards * 1.2)
            if len(cards) > max_total:
                cards = cards[:max_total]
    return cards

def extract_topics(text):
    prompt = "Identifique os principais tópicos/assuntos do texto. Retorne uma lista, um por linha, no máximo 8.\n\nTexto:\n" + text[:80000] + "\n\nTópicos:"
    resposta = llm_generate(prompt, max_tokens=300)
    topicos = [t.strip() for t in resposta.split('\n') if t.strip()]
    return topicos[:8] if topicos else ["Geral"]

def extract_questions_by_topic(text, topic, num_questions, banca=None):
    filtro = f"Filtrar apenas questões da banca {banca}. " if banca else ""
    prompt = f"""
Do texto abaixo, extraia EXATAMENTE {num_questions} questões de concurso sobre "{topic}". {filtro}As questões devem ser CÓPIAS FIÉIS do texto.
Formato para cada questão:
---
Enunciado: (copiado literalmente)
Alternativas:
a) ...
b) ...
c) ...
d) ...
e) ...
Gabarito: (letra correta)
---

Texto:
{text[:120000]}

Questões:"""
    result = llm_generate(prompt, max_tokens=2000)
    questoes = [bloco.strip() for bloco in result.split('---') if 'Enunciado:' in bloco]
    return questoes[:num_questions]

# ==================== ESTADO ====================
if 'notebooks' not in st.session_state:
    st.session_state.notebooks = {}
if 'active_notebook' not in st.session_state:
    st.session_state.active_notebook = None
if 'show_delete_confirm' not in st.session_state:
    st.session_state.show_delete_confirm = None

# ==================== INTERFACE ====================
st.title("📚 Agente de Estudos Pro — Online (Groq, gratuito)")

with st.sidebar:
    st.header("🎨 Aparência")
    dark = st.checkbox("Modo escuro", value=st.session_state.dark_mode)
    if dark != st.session_state.dark_mode:
        st.session_state.dark_mode = dark
        st.rerun()

    st.markdown("---")
    st.header("🔑 API Groq")
    api_key = st.text_input("Chave da API Groq", type="password")
    if api_key:
        st.session_state.groq_api_key = api_key
    if st.button("Salvar chave"):
        st.success("Chave salva para esta sessão.")
    st.info("Obtenha sua chave gratuita em https://console.groq.com/keys (sem cartão)")
    st.markdown("---")

    st.header("📓 Notebooks")
    novo = st.text_input("Novo notebook")
    if st.button("➕ Criar") and novo:
        if novo not in st.session_state.notebooks:
            st.session_state.notebooks[novo] = {"pdfs": [], "texto": "", "topicos": []}
            st.success(f"'{novo}' criado!")
            st.rerun()
        else:
            st.error("Já existe.")

    nomes = list(st.session_state.notebooks.keys())
    if nomes:
        if st.session_state.active_notebook not in nomes:
            st.session_state.active_notebook = nomes[0]
        active = st.selectbox("Ativo", nomes, key="active_notebook_selector")
        st.session_state.active_notebook = active
        st.markdown("---")
        with st.expander("⚙️ Gerenciar"):
            novo_nome = st.text_input("Renomear", value=active, key="rename_input")
            if st.button("✏️ Renomear") and novo_nome != active:
                if novo_nome not in st.session_state.notebooks:
                    st.session_state.notebooks[novo_nome] = st.session_state.notebooks.pop(active)
                    if st.session_state.active_notebook == active:
                        st.session_state.active_notebook = novo_nome
                    st.success("Renomeado.")
                    st.rerun()
                else:
                    st.error("Nome já existe.")
            if st.button("📋 Duplicar"):
                copia = f"Cópia de {active}"
                i=1
                while copia in st.session_state.notebooks:
                    copia = f"Cópia ({i}) de {active}"
                    i+=1
                st.session_state.notebooks[copia] = json.loads(json.dumps(st.session_state.notebooks[active]))
                st.success(f"Duplicado: {copia}")
                st.rerun()
            if st.button("🗑️ Apagar"):
                if st.session_state.show_delete_confirm != active:
                    st.session_state.show_delete_confirm = active
                    st.warning("Clique novamente para confirmar.")
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
st.subheader(f"📖 {active}")

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
                    st.success(f"✅ {f.name} ({len(txt)} caracteres)")
                else:
                    st.error(f"❌ {f.name} não tem texto. Use um PDF com texto selecionável ou converta escaneados com OCR (ex: iLovePDF).")
    if st.session_state.notebooks[active]['texto']:
        with st.spinner("Identificando tópicos..."):
            st.session_state.notebooks[active]['topicos'] = extract_topics(st.session_state.notebooks[active]['texto'])

if st.session_state.notebooks[active]['pdfs']:
    st.caption(f"📚 PDFs: {', '.join(st.session_state.notebooks[active]['pdfs'])}")
    st.caption(f"📊 Caracteres: {len(st.session_state.notebooks[active]['texto'])}")
    if st.button("🗑️ Remover todos"):
        st.session_state.notebooks[active] = {"pdfs": [], "texto": "", "topicos": []}
        st.rerun()
else:
    st.warning("⬆️ Nenhum PDF carregado.")

texto_atual = st.session_state.notebooks[active]['texto']

# Tabs
tab1, tab2, tab3, tab4 = st.tabs(["📝 Resumo", "🃏 Flashcards", "❓ Questões", "🎯 Revisão"])

with tab1:
    custom = st.text_area("Instruções (opcional):", placeholder="Ex: Destaque prazos, inclua jurisprudência...", key="custom")
    if st.button("🚀 Gerar Resumo"):
        if texto_atual:
            with st.spinner("Gerando..."):
                st.session_state['resumo'] = generate_structured_summary(texto_atual, custom)
            st.success("Pronto!")
        else:
            st.error("Sem PDF.")
    if 'resumo' in st.session_state:
        st.markdown(st.session_state['resumo'])

with tab2:
    st.subheader("Flashcards Certo/Errado")
    n = st.slider("Quantidade", 10, 300, 70, 10)
    verif = st.checkbox("Verificar cobertura", True)
    if st.button("Gerar Flashcards"):
        if texto_atual:
            with st.spinner("Criando..."):
                st.session_state['flashcards'] = generate_flashcards(texto_atual, n, verif)
                st.session_state['card_idx'] = 0
            st.success(f"{len(st.session_state['flashcards'])} cards gerados.")
        else:
            st.error("Sem PDF.")
    if 'flashcards' in st.session_state:
        cards = st.session_state['flashcards']
        idx = st.session_state.get('card_idx', 0)
        card = cards[idx]
        st.markdown(f"### Card {idx+1}/{len(cards)}")
        with st.expander("Afirmação", expanded=True):
            st.write(card['frente'])
        with st.expander("Resposta"):
            if card['verso'].startswith("Certo"):
                st.success(card['verso'])
            elif card['verso'].startswith("Errado"):
                st.error(card['verso'])
            else:
                st.write(card['verso'])
        c1,_,c3 = st.columns([1,2,1])
        if c1.button("⬅️") and idx>0:
            st.session_state['card_idx']-=1; st.rerun()
        if c3.button("➡️") and idx<len(cards)-1:
            st.session_state['card_idx']+=1; st.rerun()

with tab3:
    st.subheader("Questões dos PDFs")
    if not texto_atual:
        st.error("Sem PDF.")
    else:
        topicos = st.session_state.notebooks[active].get('topicos', ["Geral"])
        if not topicos:
            topicos = ["Geral"]
        banca = st.text_input("Filtrar banca (opcional)", "")
        total = st.number_input("Total questões", 1, 50, 10)
        st.write("Distribuição:")
        sliders = {}
        cols = st.columns(len(topicos))
        for i, t in enumerate(topicos):
            with cols[i]:
                sliders[t] = st.slider(t, 0, total, 0, key=f"sl_{t}")
        if sum(sliders.values()) != total:
            st.warning(f"Soma deve ser {total}.")
        else:
            if st.button("Iniciar Quiz"):
                quiz = []
                for t,q in sliders.items():
                    if q>0:
                        quiz += extract_questions_by_topic(texto_atual, t, q, banca if banca else None)
                random.shuffle(quiz)
                st.session_state['quiz'] = quiz
                st.session_state['q_idx'] = 0
                st.session_state['respostas'] = []
                st.session_state['gabaritos'] = []
                st.session_state['quiz_fim'] = False
                st.rerun()
        if 'quiz' in st.session_state and st.session_state['quiz']:
            idx = st.session_state['q_idx']
            q = st.session_state['quiz'][idx]
            st.markdown(f"### Questão {idx+1}/{len(st.session_state['quiz'])}")
            st.markdown(q)
            alt = re.findall(r'([a-e])\)\s*(.*)', q)
            gab = re.search(r'Gabarito:\s*([a-eA-E])', q)
            gab = gab.group(1).upper() if gab else None
            resp = st.radio("Sua resposta", [a[0].upper() for a in alt], key=f"resp_{idx}")
            if st.button("Confirmar e próxima", key=f"prox_{idx}"):
                st.session_state['respostas'].append(resp)
                st.session_state['gabaritos'].append(gab)
                if idx+1 < len(st.session_state['quiz']):
                    st.session_state['q_idx']+=1
                else:
                    st.session_state['quiz_fim'] = True
                st.rerun()
        if st.session_state.get('quiz_fim'):
            st.success("Quiz finalizado!")
            resultados = defaultdict(lambda: {"acertos":0, "total":0})
            for i,q in enumerate(st.session_state['quiz']):
                resp = st.session_state['respostas'][i] if i<len(st.session_state['respostas']) else None
                gab = st.session_state['gabaritos'][i]
                topico = "Geral"
                resultados[topico]["total"]+=1
                if resp and gab and resp.upper() == gab.upper():
                    resultados[topico]["acertos"]+=1
            st.write("### Desempenho")
            erros = []
            for top, dat in resultados.items():
                perc = dat["acertos"]/dat["total"]*100 if dat["total"] else 0
                st.write(f"{top}: {dat['acertos']}/{dat['total']} ({perc:.0f}%)")
                if dat["acertos"] < dat["total"]:
                    erros.append(top)
            if erros:
                st.session_state['topicos_revisar'] = erros
                st.info("Vá para a aba Revisão Inteligente.")

with tab4:
    st.subheader("Revisão Inteligente")
    if st.button("Gerar revisão dos erros"):
        erros = st.session_state.get('topicos_revisar', [])
        if not erros:
            st.warning("Nenhum erro detectado.")
        else:
            with st.spinner("Criando revisão..."):
                for top in erros:
                    st.markdown(f"### 📌 {top}")
                    prompt = f"Crie um resumo denso sobre '{top}' do texto.\n\nTexto:\n{texto_atual[:120000]}\n\nResumo:"
                    st.markdown(llm_generate(prompt, 500))
                    prompt_f = f"Gere 10 flashcards Certo/Errado sobre '{top}'.\n\nTexto:\n{texto_atual[:120000]}\n\nFlashcards:"
                    st.markdown(llm_generate(prompt_f, 500))
            st.success("Material gerado!")
