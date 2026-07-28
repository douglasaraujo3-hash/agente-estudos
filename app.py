import streamlit as st
import fitz  # PyMuPDF
import re
import google.generativeai as genai
from collections import defaultdict
import random
import json
import time

# ==================== CONFIGURAÇÃO DA PÁGINA ====================
st.set_page_config(
    page_title="Agente de Estudos Pro",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== MODO ESCURO ====================
if 'dark_mode' not in st.session_state:
    st.session_state.dark_mode = False

def apply_theme():
    if st.session_state.dark_mode:
        dark_css = """
        <style>
        .stApp {
            background-color: #1e1e1e;
            color: #e0e0e0;
        }
        .stTextInput, .stTextArea, .stNumberInput, .stSlider, .stFileUploader, .stSelectbox {
            background-color: #2d2d2d;
            color: #e0e0e0;
        }
        .stMarkdown, .stCaption, .stInfo, .stSuccess, .stWarning, .stError, .stException {
            color: #e0e0e0;
        }
        .stButton button {
            background-color: #4a4a4a;
            color: #ffffff;
        }
        .stTabs [data-baseweb="tab"] {
            color: #e0e0e0;
        }
        .stExpander {
            background-color: #2d2d2d;
        }
        </style>
        """
        st.markdown(dark_css, unsafe_allow_html=True)

apply_theme()

# ==================== CONEXÃO GOOGLE GEMINI ====================
def get_gemini_model():
    api_key = st.session_state.get("gemini_api_key", "")
    if not api_key:
        api_key = st.secrets.get("GEMINI_API_KEY", "")
    if not api_key:
        st.error("⚠️ Chave da API Gemini não configurada. Insira na barra lateral.")
        st.stop()
    genai.configure(api_key=api_key)
    # Usa Gemini 1.5 Flash (rápido e gratuito)
    return genai.GenerativeModel('gemini-1.5-flash')

def llm_generate(prompt, max_tokens=2000, temperature=0.1):
    model = get_gemini_model()
    try:
        # A API Gemini usa 'max_output_tokens' e 'temperature' no generation_config
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=temperature
            )
        )
        return response.text
    except Exception as e:
        st.error(f"Erro na API Gemini: {e}")
        return ""

# ==================== FUNÇÕES DE EXTRAÇÃO E IA ====================
def extract_text_from_pdf(file_bytes):
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text

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
        resumo = llm_generate(prompt, max_tokens=3000)
        summaries.append(resumo)
    return "\n\n".join(summaries)

def generate_flashcards(text, num_cards=70, check_coverage=False):
    # Etapa 1: extrair pontos
    prompt_extract = f"Liste TODOS os pontos importantes do texto abaixo que podem cair em prova (definições, prazos, exceções, etc.). Seja exaustivo.\n\nTexto:\n{text[:120000]}\n\nLista:"
    pontos = llm_generate(prompt_extract, max_tokens=3000)

    # Etapa 2: criar flashcards estilo Certo ou Errado
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
        frente = match[0].strip()
        verso = match[1].strip()
        if not (verso.startswith("Certo") or verso.startswith("Errado")):
            if "certo" in verso.lower() or "errado" in verso.lower():
                pass
            else:
                verso = "⚠️ " + verso
        cards.append({"frente": frente, "verso": verso})

    # Ajuste de quantidade
    if len(cards) > num_cards:
        cards = cards[:num_cards]
    elif len(cards) < num_cards:
        extra_prompt = f"Ainda faltam {num_cards - len(cards)} flashcards. Gere-os com base no texto original."
        extra = llm_generate(extra_prompt, max_tokens=1000)
        for match in re.findall(pattern, extra, re.DOTALL):
            cards.append({"frente": match[0].strip(), "verso": match[1].strip()})
        cards = cards[:num_cards]

    # Verificação de cobertura
    if check_coverage and cards:
        with st.spinner("Verificando cobertura dos flashcards..."):
            prompt_verify = f"""
Analise o texto original e a lista de flashcards abaixo.
Identifique se ALGUM ponto importante do texto NÃO foi abordado nos flashcards.
Se houver omissões, crie flashcards adicionais (estilo Certo/Errado, Frente: ... Verso: ...) para cada ponto faltante (até 20).

Texto original:
{text[:120000]}

Flashcards atuais:
{json.dumps(cards, ensure_ascii=False, indent=2)}

Pontos faltantes (flashcards adicionais, se necessário):"""
            verification = llm_generate(prompt_verify, max_tokens=1000)
            extra_pattern = r"Frente:\s*(.*?)\nVerso:\s*(.*?)(?=\nFrente:|\Z)"
            for match in re.findall(extra_pattern, verification, re.DOTALL):
                cards.append({"frente": match[0].strip(), "verso": match[1].strip()})
            max_total = int(num_cards * 1.2)
            if len(cards) > max_total:
                cards = cards[:max_total]
    return cards

def extract_topics(text):
    prompt = "Identifique os principais tópicos/assuntos do texto. Retorne uma lista, um por linha, no máximo 8.\n\nTexto:\n" + text[:80000] + "\n\nTópicos:"
    resposta = llm_generate(prompt, max_tokens=300)
    topicos = [t.strip() for t in resposta.split('\n') if t.strip()]
    return topicos[:8]

def extract_questions_by_topic(text, topic, num_questions, banca=None):
    filtro_banca = f"Filtrar apenas questões da banca {banca}. " if banca else ""
    prompt = f"""
Do texto abaixo, extraia EXATAMENTE {num_questions} questões de concurso sobre "{topic}". {filtro_banca}As questões devem ser CÓPIAS FIÉIS do texto, sem invenções.
Formato para cada questão:
---
Enunciado: (copiado literalmente do texto)
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
    questoes = []
    for bloco in result.split('---'):
        if 'Enunciado:' in bloco:
            questoes.append(bloco.strip())
    return questoes[:num_questions]

# ==================== ESTADO DA SESSÃO ====================
if 'notebooks' not in st.session_state:
    st.session_state.notebooks = {}
if 'active_notebook' not in st.session_state:
    st.session_state.active_notebook = None
if 'show_delete_confirm' not in st.session_state:
    st.session_state.show_delete_confirm = None

# ==================== INTERFACE ====================
st.title("📚 Agente de Estudos Pro — Flashcards Certo/Errado (Gemini)")

with st.sidebar:
    st.header("🎨 Aparência")
    dark = st.checkbox("Modo escuro", value=st.session_state.dark_mode)
    if dark != st.session_state.dark_mode:
        st.session_state.dark_mode = dark
        st.rerun()

    st.markdown("---")
    st.header("🔑 API Gemini (Google)")
    api_key = st.text_input("Chave da API Gemini", type="password", key="api_key_input")
    if api_key:
        st.session_state.gemini_api_key = api_key
    if st.button("Salvar chave"):
        st.success("Chave salva para esta sessão.")
    st.info("Obtenha sua chave gratuita em makersuite.google.com/app/apikey")
    st.markdown("---")

    st.header("📓 Notebooks")
    novo_nome = st.text_input("Nome do novo notebook")
    if st.button("➕ Criar") and novo_nome:
        if novo_nome not in st.session_state.notebooks:
            st.session_state.notebooks[novo_nome] = {"pdfs": [], "texto": "", "topicos": []}
            st.success(f"Notebook '{novo_nome}' criado.")
            st.rerun()
        else:
            st.error("Já existe um notebook com esse nome.")

    nomes = list(st.session_state.notebooks.keys())
    if nomes:
        if st.session_state.active_notebook not in nomes:
            st.session_state.active_notebook = nomes[0]
        active = st.selectbox("Notebook ativo", nomes, key="active_notebook_selector")
        st.session_state.active_notebook = active
        st.markdown("---")

        with st.expander("⚙️ Gerenciar este notebook"):
            novo_nome = st.text_input("Novo nome", value=active, key="rename_input")
            if st.button("✏️ Renomear") and novo_nome and novo_nome != active:
                if novo_nome not in st.session_state.notebooks:
                    st.session_state.notebooks[novo_nome] = st.session_state.notebooks.pop(active)
                    if st.session_state.active_notebook == active:
                        st.session_state.active_notebook = novo_nome
                    st.success(f"Renomeado para '{novo_nome}'.")
                    st.rerun()
                else:
                    st.error("Nome já existe.")

            if st.button("📋 Duplicar"):
                copia_nome = f"Cópia de {active}"
                i = 1
                while copia_nome in st.session_state.notebooks:
                    copia_nome = f"Cópia ({i}) de {active}"
                    i += 1
                st.session_state.notebooks[copia_nome] = json.loads(json.dumps(st.session_state.notebooks[active]))
                st.success(f"Duplicado como '{copia_nome}'.")
                st.rerun()

            if st.button("🗑️ Apagar notebook"):
                if st.session_state.show_delete_confirm != active:
                    st.session_state.show_delete_confirm = active
                    st.warning(f"Clique novamente para confirmar exclusão de '{active}'.")
                else:
                    del st.session_state.notebooks[active]
                    st.session_state.show_delete_confirm = None
                    if st.session_state.active_notebook == active:
                        st.session_state.active_notebook = None
                    st.success("Notebook apagado.")
                    st.rerun()
    else:
        st.info("Crie um notebook para começar.")
        st.stop()

if not st.session_state.active_notebook:
    st.stop()

active = st.session_state.active_notebook
st.subheader(f"📖 {active}")

# Upload de PDF
uploaded_files = st.file_uploader("Arraste PDFs para este notebook", type="pdf", accept_multiple_files=True, key=f"upload_{active}")
if uploaded_files:
    for uploaded in uploaded_files:
        if uploaded.name not in st.session_state.notebooks[active]['pdfs']:
            st.session_state.notebooks[active]['pdfs'].append(uploaded.name)
            texto_extraido = extract_text_from_pdf(uploaded.getvalue())
            st.session_state.notebooks[active]['texto'] += texto_extraido + "\n\n"
    if st.session_state.notebooks[active]['texto']:
        topicos = extract_topics(st.session_state.notebooks[active]['texto'])
        st.session_state.notebooks[active]['topicos'] = topicos
    st.success(f"PDFs adicionados: {', '.join(st.session_state.notebooks[active]['pdfs'])}")

if st.session_state.notebooks[active]['pdfs']:
    st.caption(f"PDFs: {', '.join(st.session_state.notebooks[active]['pdfs'])}")
    if st.button("🗑️ Remover todos os PDFs"):
        st.session_state.notebooks[active] = {"pdfs": [], "texto": "", "topicos": []}
        st.rerun()

texto_atual = st.session_state.notebooks[active]['texto']

# Tabs principais
tab_resumo, tab_flash, tab_questoes, tab_revisao = st.tabs(
    ["📝 Resumo Esquematizado", "🃏 Flashcards Certo/Errado", "❓ Questões dos PDFs", "🎯 Revisão Inteligente"]
)

with tab_resumo:
    st.header("📝 Resumo Esquematizado (Personalizável)")
    # CAMPO PARA DIGITAR O QUE QUER NO RESUMO
    custom_resumo = st.text_area(
        "✨ Instruções para o resumo (opcional):",
        placeholder="Ex: Dê destaque a prazos, inclua jurisprudência do STF, explique como se fosse para um leigo...",
        key="custom_resumo"
    )
    if st.button("🚀 Gerar Resumo Completo"):
        if texto_atual:
            with st.spinner("Gerando resumo..."):
                resumo = generate_structured_summary(texto_atual, custom_instruction=custom_resumo)
                st.session_state['resumo'] = resumo
            st.success("Resumo gerado!")
        else:
            st.error("Nenhum PDF carregado.")
    if 'resumo' in st.session_state:
        st.markdown(st.session_state['resumo'])

with tab_flash:
    st.header("🃏 Flashcards Certo ou Errado")
    st.markdown("Cada flashcard apresenta uma **afirmação**. Tente responder se está **Certa** ou **Errada**. Depois, vire para ver a explicação completa e uma mini revisão.")
    num_flash = st.slider("Número de flashcards", 10, 300, 70, 10, key="num_flash")
    verificar = st.checkbox("Verificar cobertura (adiciona cards extras se faltar conteúdo)", value=True, key="check_cov")
    if st.button("Gerar Flashcards"):
        if texto_atual:
            with st.spinner(f"Criando {num_flash} flashcards..."):
                cards = generate_flashcards(texto_atual, num_flash, check_coverage=verificar)
                st.session_state['flashcards'] = cards
                st.session_state['card_idx'] = 0
            st.success(f"{len(cards)} flashcards gerados.")
        else:
            st.error("Nenhum PDF carregado.")
    if 'flashcards' in st.session_state and st.session_state['flashcards']:
        cards = st.session_state['flashcards']
        idx = st.session_state.get('card_idx', 0)
        card = cards[idx]
        st.markdown(f"### Card {idx+1} de {len(cards)}")
        with st.expander("📌 Afirmação", expanded=True):
            st.write(card['frente'])
        with st.expander("🔍 Ver resposta"):
            verso = card['verso']
            if verso.startswith("Certo"):
                st.success(verso)
            elif verso.startswith("Errado"):
                st.error(verso)
            else:
                st.write(verso)
        c1, c2, c3 = st.columns([1,2,1])
        with c1:
            if st.button("⬅️") and idx > 0:
                st.session_state['card_idx'] -= 1
                st.rerun()
        with c3:
            if st.button("➡️") and idx < len(cards)-1:
                st.session_state['card_idx'] += 1
                st.rerun()

with tab_questoes:
    st.header("❓ Questões dos PDFs")
    if not texto_atual:
        st.error("Carregue PDFs primeiro.")
    else:
        topicos = st.session_state.notebooks[active].get('topicos', [])
        if not topicos:
            topicos = ["Geral"]
        filtro_banca = st.text_input("Filtrar por banca (ex.: CESPE) ou palavra-chave", value="")
        total_questoes = st.number_input("Total de questões no quiz", min_value=1, max_value=50, value=10)
        st.write("Distribua as questões entre os tópicos:")
        sliders = {}
        cols = st.columns(len(topicos))
        for i, topico in enumerate(topicos):
            with cols[i]:
                sliders[topico] = st.slider(topico, 0, total_questoes, 0, key=f"slider_{active}_{topico}")
        if sum(sliders.values()) != total_questoes:
            st.warning(f"A soma deve ser exatamente {total_questoes}.")
        else:
            if st.button("Iniciar Quiz"):
                questoes_quiz = []
                for topico, qtd in sliders.items():
                    if qtd > 0:
                        extraidas = extract_questions_by_topic(texto_atual, topico, qtd, banca=filtro_banca)
                        questoes_quiz.extend(extraidas)
                random.shuffle(questoes_quiz)
                st.session_state['quiz_questoes'] = questoes_quiz
                st.session_state['quiz_idx'] = 0
                st.session_state['quiz_respostas'] = []
                st.session_state['quiz_gabaritos'] = []
                st.session_state['quiz_finalizado'] = False
                st.rerun()
        if 'quiz_questoes' in st.session_state and st.session_state['quiz_questoes']:
            idx = st.session_state['quiz_idx']
            questao = st.session_state['quiz_questoes'][idx]
            st.markdown(f"### Questão {idx+1} de {len(st.session_state['quiz_questoes'])}")
            st.markdown(questao)
            alternativas = re.findall(r'([a-e])\)\s*(.*)', questao)
            gabarito_match = re.search(r'Gabarito:\s*([a-eA-E])', questao)
            gabarito = gabarito_match.group(1).upper() if gabarito_match else None
            resposta_usuario = st.radio("Sua resposta", [a[0].upper() for a in alternativas], key=f"resp_{idx}")
            if st.button("Confirmar e próxima", key=f"prox_{idx}"):
                st.session_state['quiz_respostas'].append(resposta_usuario)
                st.session_state['quiz_gabaritos'].append(gabarito)
                if idx + 1 < len(st.session_state['quiz_questoes']):
                    st.session_state['quiz_idx'] += 1
                else:
                    st.session_state['quiz_finalizado'] = True
                st.rerun()
        if st.session_state.get('quiz_finalizado'):
            st.success("Quiz finalizado!")
            resultados = defaultdict(lambda: {"acertos": 0, "total": 0})
            for i, questao in enumerate(st.session_state['quiz_questoes']):
                topico = "Geral"
                resp = st.session_state['quiz_respostas'][i] if i < len(st.session_state['quiz_respostas']) else None
                gab = st.session_state['quiz_gabaritos'][i]
                if resp and gab and resp.upper() == gab.upper():
                    resultados[topico]["acertos"] += 1
                resultados[topico]["total"] += 1
            st.write("### Desempenho")
            topicos_erro = []
            for topico, data in resultados.items():
                perc = data["acertos"]/data["total"]*100 if data["total"] else 0
                st.write(f"{topico}: {data['acertos']}/{data['total']} ({perc:.0f}%)")
                if data["acertos"] < data["total"]:
                    topicos_erro.append(topico)
            if topicos_erro:
                st.session_state['topicos_para_revisar'] = topicos_erro
                st.info("Vá para a aba 'Revisão Inteligente' para estudar o que errou.")
            else:
                st.balloons()
                st.success("Parabéns! 100% de acerto.")

with tab_revisao:
    st.header("🎯 Revisão Inteligente")
    if st.button("Gerar revisão dos meus erros"):
        topicos_erro = st.session_state.get('topicos_para_revisar', [])
        if not topicos_erro:
            st.warning("Nenhum erro detectado. Faça o quiz primeiro.")
        else:
            with st.spinner("Gerando material de revisão..."):
                for topico in topicos_erro:
                    st.subheader(f"📌 {topico}")
                    prompt_resumo = f"Crie um resumo denso sobre '{topico}' do texto abaixo. Inclua definições, prazos e exceções.\n\nTexto:\n{texto_atual[:120000]}\n\nResumo:"
                    resumo_topico = llm_generate(prompt_resumo, max_tokens=500)
                    st.markdown(resumo_topico)
                    prompt_flash = f"Gere 10 flashcards (estilo Certo/Errado) sobre '{topico}' do texto. Frente: afirmação / Verso: Certo/Errado + explicação.\n\nTexto:\n{texto_atual[:120000]}\n\nFlashcards:"
                    flashcards_topico = llm_generate(prompt_flash, max_tokens=500)
                    st.markdown(flashcards_topico)
            st.success("Material de revisão gerado!")
