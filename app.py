import os
import random
import uuid
import logging
import grpc

logging.basicConfig(level=logging.WARNING)

from flask import Flask, json, render_template, request, redirect, url_for, session, flash
# 🚨 NOVA IMPORTAÇÃO: werkzeug.utils para nomes de arquivo seguros
from werkzeug.utils import secure_filename 
import firebase_admin
from firebase_admin import credentials, firestore, auth
from datetime import datetime, timedelta
from functools import wraps 
# Importação necessária para usar o filtro moderno no Firestore
from google.cloud.firestore_v1.base_query import FieldFilter 

# ==========================================================
# 1. INICIALIZAÇÃO DO FLASK E FIREBASE
# ==========================================================

app = Flask(__name__)
# Chave Secreta para Sessões do Flask (MUITO IMPORTANTE)
# Chave Secreta para Sessões do Flask (MUITO IMPORTANTE)
# Deve ser lida de uma variável de ambiente em produção.
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'default_fallback_for_dev_only')

# === CORREÇÃO DE CHECAGEM DO AMBIENTE ===
# Se o app.secret_key for o fallback E estivermos em um ambiente Render (verificado por RENDER_EXTERNAL_HOSTNAME), force o erro.
if app.secret_key == 'default_fallback_for_dev_only' and os.environ.get('RENDER_EXTERNAL_HOSTNAME'):
    raise Exception("ERRO CRÍTICO: FLASK_SECRET_KEY não configurada no Render! A sessão não é segura.")

# === FIM DA CORREÇÃO ===
# !!! TROQUE POR UMA CHAVE MAIS SEGURA NA PRODUÇÃO !!!
# 1. Verifica se o aplicativo Firebase Padrão já existe
if not firebase_admin._apps:
    FIREBASE_CREDENTIALS_JSON = os.environ.get('FIREBASE_CREDENTIALS_JSON')
    
    if FIREBASE_CREDENTIALS_JSON:
        # Opção A: Credenciais de ambiente (para Produção/Render)
        try:
            # Carrega o JSON da variável de ambiente como um dicionário
            cred_dict = json.loads(FIREBASE_CREDENTIALS_JSON)
            cred = credentials.Certificate(cred_dict)
            firebase_app = firebase_admin.initialize_app(cred)
            print("✅ Firebase inicializado com sucesso via Variável de Ambiente.")
        except Exception as e:
            print(f"❌ ERRO CRÍTICO ao inicializar Firebase via Variável de Ambiente: {e}")
            raise
    else:
        # Opção B: Credenciais do arquivo local (para Desenvolvimento)
        CRED_PATH = 'firebase-admin-sdk.json'
        if os.path.exists(CRED_PATH):
            try:
                cred = credentials.Certificate(CRED_PATH)
                firebase_app = firebase_admin.initialize_app(cred)
                print("⏳ Firebase inicializado com sucesso via Arquivo Local.")
            except Exception as e:
                print(f"❌ ERRO CRÍTICO ao inicializar Firebase via Arquivo Local: {e}")
                raise
        else:
            # Nenhuma credencial encontrada
            print("❌ ERRO CRÍTICO: Credenciais Firebase não encontradas.")
            raise Exception("Credenciais Firebase ausentes. Configure a variável de ambiente.")
else:
    # Se já existir (caso o Gunicorn tenha feito a inicialização), usa a instância existente.
    firebase_app = firebase_admin.get_app()
    print("⚠️ Firebase já estava inicializado. Usando a instância existente.")

# Configuração da conexão com o banco de dados
db = firestore.client()

# ==========================================================
# 2. CONFIGURAÇÃO DE UPLOAD
# ==========================================================

# Caminho para o arquivo de credenciais (mantido apenas para referência de dev)
CRED_PATH = 'firebase-admin-sdk.json' 

UPLOAD_FOLDER = 'static/img/avatares' 
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Cria a pasta se ela não existir (MUITO IMPORTANTE)
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
# FIM CONFIGURAÇÃO DE UPLOAD

    # Decida se o app deve parar aqui ou continuar com funcionalidade limitada
    # Se parar, é útil para o deploy falhar e avisar você.
    # firebase_app = None # Descomente se o app puder rodar sem Firebase

# ==========================================================
# 2. CONFIGURAÇÃO DE ADMIN (FIXO NO CÓDIGO)
# ==========================================================

ADMIN_EMAIL_FIXO = "psicoadm@gmail.com"
ADMIN_SENHA_FIXA = "33529710" 

# ==========================================================
# 3. CONTEXT PROCESSOR E FILTROS JINJA
# ==========================================================

@app.context_processor
def inject_global_variables():
    """Torna o ano atual disponível como 'current_year' em todos os templates."""
    return {
        'current_year': datetime.now().year
    }

# FILTRO DE TRADUÇÃO PARA DIAS
DIAS_PTBR = {
    'Monday': 'Segunda-feira',
    'Tuesday': 'Terça-feira',
    'Wednesday': 'Quarta-feira',
    'Thursday': 'Quinta-feira',
    'Friday': 'Sexta-feira',
    'Saturday': 'Sábado',
    'Sunday': 'Domingo'
}

@app.template_filter('translate_day')
def translate_day_filter(value):
    """Traduz o nome do dia da semana para Português."""
    if ',' in value:
        dia_en = value.split(',')[0].strip()
        data = value.split(',')[1].strip()
        
        dia_pt = DIAS_PTBR.get(dia_en, dia_en)
        return f"{dia_pt}, {data}"
        
    return DIAS_PTBR.get(value, value)


# ==========================================================
# 4. MOCK DATA E FUNÇÕES UTILITÁRIAS
# ==========================================================

MOCK_PSICOLOGOS = [
    {
        "id": "psi1", 
        "nome": "Dr. Lucas Mendes",
        "genero": "M",
        "valorSessao": 180.00,
        "descricaoCurta": "Especialista em Ansiedade e Terapia Cognitivo-Comportamental (TCC) e Estresse.",
        "tags": ["TCC", "Ansiedade", "Estresse"],
        "fotoURL": 'default_avatar.jpg', # Nome do arquivo que estará no DB/Mock
        "email": "lucas@psi.com" 
    },
    {
        "id": "psi2", 
        "nome": "Dra. Ana Silveira",
        "genero": "F",
        "valorSessao": 150.00,
        "descricaoCurta": "Foco em Luto, Trauma, Depressão e Psicanálise. Mais de 10 anos de experiência.",
        "tags": ["Psicanálise", "Luto", "Depressão"],
        "fotoURL": 'default_avatar.jpg',
        "email": "ana@psi.com"
    },
    {
        "id": "psi3", 
        "nome": "Dr. Pedro Costa",
        "genero": "M",
        "valorSessao": 200.00,
        "descricaoCurta": "Terapia de Casal, Relacionamentos e Abordagem Humanista.",
        "tags": ["Humanista", "Casal", "Relacionamento"],
        "fotoURL": 'default_avatar.jpg',
        "email": "pedro@psi.com"
    }
]

# Função para gerar horários simulados
def get_mock_horarios():
    horarios = {}
    hoje = datetime.now()
    dias = [
        hoje + timedelta(days=i) for i in range(1, 5)
    ]
    
    for dia in dias:
        dia_str = dia.strftime("%A, %d/%m") 
        horarios[dia_str] = [
            f"{h:02d}:00" for h in range(9, 17, 2)
        ]
    return horarios

# 🚨 FUNÇÃO ADICIONADA: Validação de Arquivo
def allowed_file(filename):
    """Verifica se a extensão do arquivo é permitida."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# FUNÇÃO UTILITÁRIA CORRIGIDA: PRIORIZA FIREBASE E MAPEIA CAMPOS
def get_all_psicologos():
    """Busca a lista de psicólogos do Firestore (prioridade) ou usa o Mock (fallback)."""
    psicologos_list = []
    
    # Mapeamento dos campos do Firestore para os campos esperados no Flask 
    FIELD_MAP = {
        'bio': 'descricaoCurta', # Bio no DB vira descricaoCurta no App
        'especialidades': 'tags', # Especialidades no DB vira tags no App
        'fotoURL': 'avatar_filename', # fotoURL no DB vira avatar_filename no App
        'genero': 'genero',
        'nome': 'nome',
        'email': 'email',
        'valorSessao': 'valorSessao',
        'cadastradoEm': 'cadastradoEm'
    }
    
    # 1. Tenta buscar do Firestore
    if db:
        try:
            # Busca todos os documentos na coleção 'psicologos'
            docs = db.collection('psicologos').stream()
            
            # Converte os documentos e adiciona à lista
            for doc in docs:
                db_data = doc.to_dict()
                mapped_data = {}

                # Mapeia e sanitiza os dados
                for db_field, app_field in FIELD_MAP.items():
                    # Mapeia o valor, lidando com tags (que podem ser None se o doc for antigo)
                    if app_field == 'tags':
                         mapped_data[app_field] = db_data.get(db_field, []) or []
                    else:
                         mapped_data[app_field] = db_data.get(db_field)
                
                # É crucial garantir que o ID do documento esteja no dicionário para as rotas
                mapped_data['id'] = doc.id 
                
                # Define um padrão se não houver foto (usa o nome do arquivo, não o caminho completo)
                if not mapped_data.get('avatar_filename') or mapped_data.get('avatar_filename') == '':
                     mapped_data['avatar_filename'] = 'default_avatar.jpg'

                psicologos_list.append(mapped_data)

            # Se o Firestore retornou dados, use eles.
            if psicologos_list:
                return psicologos_list

        except Exception as e:
            print(f"Aviso: Erro ao carregar psicólogos do Firestore: {e}. Usando MOCK.")
            
    # 2. Fallback: Se DB falhou ou está offline, usa o MOCK
    global MOCK_PSICOLOGOS
    print("Aviso: Carregando psicólogos do MOCK_PSICOLOGOS.")
    # Converte o campo 'fotoURL' do mock para 'avatar_filename' esperado pelo template
    mock_ajustado = []
    for p in MOCK_PSICOLOGOS:
        p_copy = p.copy()
        p_copy['avatar_filename'] = p.get('fotoURL', 'default_avatar.jpg')
        mock_ajustado.append(p_copy)
    
    return mock_ajustado

# 🚨 FUNÇÃO CORRIGIDA: Adiciona o URL do avatar ao template, considerando o caminho de upload
def process_psicologos_for_template(psicologos_list):
    """Adiciona o campo 'avatar' usando url_for, tratando o caminho do upload."""
    processed_list = []
    for psi in psicologos_list:
        psi_com_url = psi.copy() 
        # O valor aqui é o nome do arquivo (ex: 'unique_id_foto.jpg' ou 'default_avatar.jpg')
        avatar_filename = psi_com_url.get('avatar_filename', 'default_avatar.jpg')
        
        # Lógica para montar o URL correto:
        if avatar_filename == 'default_avatar.jpg':
            # Arquivo de mock default está em 'static/img/default_avatar.jpg'
            psi_com_url['avatar'] = url_for('static', filename='img/default_avatar.jpg')
        else:
            # Arquivos próprios estão dentro de 'static/img/avatares/nome_unico.jpg'
            # UPLOAD_FOLDER é 'static/img/avatares'
            upload_dir_name = UPLOAD_FOLDER.replace("static/", "") # 'img/avatares'
            psi_com_url['avatar'] = url_for('static', filename=f'{upload_dir_name}/{avatar_filename}')
            
        processed_list.append(psi_com_url)
    return processed_list

# ==========================================================
# 5. ROTAS DE AUTENTICAÇÃO (PSICÓLOGO E ADMIN) - CORRIGIDA
# ==========================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_role' in session:
        if session['user_role'] == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form.get('email')
        # A senha não é validada nesta versão do código, apenas a existência do email no Auth
        # password = request.form.get('senha')
        
        # 1. VERIFICAÇÃO DE ADMIN (Credenciais Fixas)
        if email == ADMIN_EMAIL_FIXO and request.form.get('senha') == ADMIN_SENHA_FIXA:
            session['psicologo_uid'] = 'admin_master_uid' 
            session['user_role'] = 'admin'
            flash("Bem-vindo, Administrador Geral!", 'success')
            return redirect(url_for('admin_dashboard'))

        # 2. TENTA LOGIN VIA FIREBASE AUTH E FIREBASE FIRESTORE (PSICÓLOGO)
        psicologo_data = None
        psicologo_uid = None
        
        if db:
            try:
                # 2.1. Tenta autenticar o usuário no Firebase Auth (verifica a existência do email)
                user = auth.get_user_by_email(email)
                psicologo_uid = user.uid

                # 2.2. BUSCA O PERFIL COMPLETO DO PSICÓLOGO NO FIRESTORE (Busca Persistente!)
                # O ID do documento é o UID do Auth, garantindo a unicidade.
                psicologo_doc = db.collection('psicologos').document(psicologo_uid).get()
                
                if psicologo_doc.exists:
                    # Usamos a função get_all_psicologos para garantir que os campos sejam mapeados corretamente
                    todos_psicologos = get_all_psicologos()
                    psicologo_data = next((p for p in todos_psicologos if p['id'] == psicologo_uid), None)

                    if not psicologo_data:
                        flash("Erro de mapeamento de perfil de psicólogo.", 'error')
                        return render_template('login.html', page_title='Login PsicoAPP')
                        
                else:
                    # Usuário existe no Auth, mas não tem perfil de psicólogo
                    flash("Perfil de psicólogo não encontrado no banco de dados.", 'error')
                    return render_template('login.html', page_title='Login PsicoAPP')

            except firebase_admin.exceptions.FirebaseError:
                # O usuário não existe no Auth ou a busca falhou
                flash("E-mail ou senha inválidos.", 'error')
                return render_template('login.html', page_title='Login PsicoAPP')
            
        
        # 3. VERIFICA E CONCLUI O LOGIN
        if psicologo_data:
            session['psicologo_uid'] = psicologo_uid
            session['user_role'] = 'psicologo'
            flash(f"Bem-vindo(a), {psicologo_data.get('nome', 'Psicólogo(a)')}!", 'info')
            return redirect(url_for('dashboard'))
        
        # 4. Fallback (Se o DB estava offline ou a lógica acima falhou)
        flash("Falha ao conectar com o banco de dados ou erro de login. Tente novamente.", 'error')
            
    return render_template('login.html', page_title='Login PsicoAPP')

@app.route('/logout')
def logout():
    session.pop('psicologo_uid', None)
    session.pop('user_role', None)
    flash("Você saiu da sua conta.", 'info')
    return redirect(url_for('index'))

# ==========================================================
# 6. ROTA PROTEGIDA (DASHBOARD PSICÓLOGO) - CORRIGIDA DEFINITIVAMENTE
# ==========================================================

@app.route('/dashboard')
def dashboard():
    if session.get('user_role') != 'psicologo':
        flash("Acesso negado. Você precisa ser um Psicólogo para acessar esta área.", 'error')
        return redirect(url_for('login'))
        
    psicologo_uid = session.get('psicologo_uid')
    
    # Tenta buscar dados do psicólogo do DB para ter o nome correto
    psicologo_data = next((p for p in get_all_psicologos() if p['id'] == psicologo_uid), 
                          {"nome": "Psicólogo(a) Teste", "id": psicologo_uid})
                          
    agendamentos = [] # Inicializa vazio

    # 1. TENTA BUSCAR DADOS REAIS NO FIREBASE
    if db:
        try:
            # 🚨 PONTO CRÍTICO CORRIGIDO: Busca agendamentos com FieldFilter e o ID correto
            # O campo no DB é 'psicologo_id', e o valor é o 'psicologo_uid' da sessão
            agendamento_docs = db.collection('agendamentos').where(
                filter=FieldFilter('psicologo_id', '==', psicologo_uid)
            ).stream()
            
            # Converte os documentos encontrados para uma lista de dicionários
            for doc in agendamento_docs:
                agendamento = doc.to_dict()
                agendamento['doc_id'] = doc.id # Adiciona o ID do documento
                agendamentos.append(agendamento)
            
            # DEBUG: Checagem de carregamento (Aparecerá no console)
            print(f"\n--- DEBUG: Carregamento do Dashboard ---")
            print(f"ID do Psicólogo Logado: {psicologo_uid}")
            print(f"Agendamentos carregados do DB: {len(agendamentos)}")
            print("------------------------------------------\n")

        except Exception as e:
            print(f"ERRO CRÍTICO ao buscar agendamentos no Firebase: {e}")
            flash("Erro ao carregar seus agendamentos. Tente novamente mais tarde.", 'error')
    
    # 2. FALLBACK: Se não encontrou agendamentos reais, usa o Mock
    if not agendamentos and not db: # Somente usa o mock se o DB estiver offline
        agendamentos = [
            {
                "doc_id": "mock_ag1",
                "dataHoraSessao": "Terça-feira, 15/10 às 14:00",
                "usuarioEmail": "cliente.teste@mail.com",
                "sessaoTipo": "Individual (50 min)",
                "status": "Confirmado",
                "linkSessao": f"https://psicoapp.com/sessao/{str(uuid.uuid4())}"
            }
        ]
        
    # Se o DB carregou, mas a lista está vazia, isso significa que não há agendamentos para esse ID.
    if not agendamentos and db:
        flash("Você não possui agendamentos confirmados no momento.", 'info')

    return render_template('dashboard.html', 
                            page_title='Dashboard', 
                            psicologo=psicologo_data, 
                            agendamentos=agendamentos)

# Coloque esta rota no seu app.py (Seção 6, após a rota /dashboard)


@app.route('/psicologo/consulta/<doc_id>/finalizar', methods=['POST'])
def finalizar_consulta(doc_id):
    # 1. VERIFICAÇÃO DE SEGURANÇA BÁSICA
    if session.get('user_role') != 'psicologo':
        flash("Acesso negado. Você precisa ser um Psicólogo para realizar esta ação.", 'error')
        return redirect(url_for('login'))
        
    psicologo_uid = session.get('psicologo_uid')
    
    # Pega os dados do formulário: prontuário
    prontuario = request.form.get('prontuario') 

    if not db:
        flash("Erro: Conexão com o Banco de Dados indisponível.", 'error')
        return redirect(url_for('dashboard'))

    try:
        consulta_ref = db.collection('agendamentos').document(doc_id)
        consulta_doc = consulta_ref.get()

        if not consulta_doc.exists:
            flash("Erro: Consulta não encontrada.", 'error')
            return redirect(url_for('dashboard'))
        
        # 2. VERIFICAÇÃO DE AUTORIZAÇÃO (DONO DA CONSULTA)
        if consulta_doc.to_dict().get('psicologo_id') != psicologo_uid:
            flash("Você não tem permissão para finalizar esta consulta.", 'error')
            return redirect(url_for('dashboard'))

        # 3. ATUALIZAÇÃO DO FIRESTORE
        consulta_ref.update({
            'status': 'Realizada',
            'prontuario': prontuario, # NOVO CAMPO
            'dataFinalizacao': firestore.SERVER_TIMESTAMP # Para histórico
        })
        
        flash("Registro da consulta e prontuário salvos com sucesso! Status: Realizada.", 'success')

    except Exception as e:
        flash(f"Erro ao finalizar a consulta: {e}", 'error')

    return redirect(url_for('dashboard'))

# Coloque esta rota no seu app.py (Seção 6, após a rota de Finalizar)

@app.route('/psicologo/consulta/<doc_id>/cancelar', methods=['POST'])
def cancelar_consulta(doc_id):
    # 1. VERIFICAÇÃO DE SEGURANÇA BÁSICA
    if session.get('user_role') != 'psicologo':
        flash("Acesso negado.", 'error')
        return redirect(url_for('login'))
        
    psicologo_uid = session.get('psicologo_uid')
    
    # Pega os dados do formulário: motivo
    motivo = request.form.get('motivo_cancelamento', 'Cancelado pelo psicólogo sem motivo especificado.')

    if not db:
        flash("Erro: Conexão com o Banco de Dados indisponível.", 'error')
        return redirect(url_for('dashboard'))

    try:
        consulta_ref = db.collection('agendamentos').document(doc_id)
        consulta_doc = consulta_ref.get()
        
        # 2. VERIFICAÇÃO DE AUTORIZAÇÃO (DONO DA CONSULTA)
        if consulta_doc.exists and consulta_doc.to_dict().get('psicologo_id') != psicologo_uid:
            flash("Você não tem permissão para cancelar esta consulta.", 'error')
            return redirect(url_for('dashboard'))
        
        # 3. ATUALIZAÇÃO DO FIRESTORE
        consulta_ref.update({
            'status': 'Cancelada',
            'motivo_cancelamento': motivo, # NOVO CAMPO
            'dataCancelamento': firestore.SERVER_TIMESTAMP
        })
        
        flash("Consulta alterada para Cancelada com sucesso.", 'info')

    except Exception as e:
        flash(f"Erro ao cancelar a consulta: {e}", 'error')

    return redirect(url_for('dashboard'))

# ==========================================================
# 6. ROTA PROTEGIDA (DASHBOARD PSICÓLOGO) - CONTINUAÇÃO
# ==========================================================

# --- NOVA ROTA PARA MUDAR O STATUS DO AGENDAMENTO ---
@app.route('/dashboard/agendamento/<doc_id>/<action>', methods=['POST'])
def mudar_status_agendamento(doc_id, action):
    # Verifica se o usuário é um psicólogo (ou admin) para ter acesso à funcionalidade
    if session.get('user_role') not in ['psicologo', 'admin']:
        flash("Acesso negado. Você não tem permissão para alterar agendamentos.", 'error')
        return redirect(url_for('login'))
        
    if not db:
        flash("Erro: Conexão com o Banco de Dados (Firebase) indisponível. Status não alterado.", 'error')
        return redirect(url_for('dashboard'))

    # Mapeia a ação para o status final
    if action == 'concluir':
        novo_status = 'Concluída'
        mensagem = 'Agendamento marcado como CONCLUÍDO.'
    elif action == 'cancelar':
        novo_status = 'Cancelada'
        mensagem = 'Agendamento CANCELADO com sucesso.'
    else:
        flash("Ação inválida.", 'error')
        return redirect(url_for('dashboard'))
        
    try:
        # 1. Referência ao documento de agendamento no Firestore
        # O 'doc_id' é o ID do documento da coleção 'agendamentos'
        agendamento_ref = db.collection('agendamentos').document(doc_id)
        
        # 2. Atualiza o campo 'status' no Firestore
        agendamento_ref.update({'status': novo_status})
        
        flash(mensagem, 'success')
        
    except Exception as e:
        flash(f"Erro ao atualizar o status do agendamento: {e}", 'error')
    
    # Redireciona de volta para o dashboard
    return redirect(url_for('dashboard'))

# Coloque este código no seu app.py, junto das outras rotas protegidas (Seção 6)

@app.route('/psicologo/historico')
def historico_consultas():
    # 1. VERIFICAÇÃO DE SEGURANÇA
    if session.get('user_role') != 'psicologo':
        flash("Acesso negado. Você precisa ser um Psicólogo para acessar o histórico.", 'error')
        return redirect(url_for('login'))
        
    psicologo_uid = session.get('psicologo_uid')
    
    if not db:
        flash("Erro: Conexão com o Banco de Dados indisponível.", 'error')
        return redirect(url_for('dashboard'))

    historico_list = []
    
    try:
        # 2. BUSCA NO FIRESTORE
        # Filtra por 'psicologo_id' e status 'Realizada' ou 'Cancelada'
        # Nota: O filtro 'in' é a forma mais eficiente de buscar múltiplos status
        historico_docs = db.collection('agendamentos') \
            .where(filter=FieldFilter('psicologo_id', '==', psicologo_uid)) \
            .where(filter=FieldFilter('status', 'in', ['Realizada', 'Cancelada'])) \
            .order_by('dataHoraSessao', direction='DESCENDING') \
            .stream()

        # 3. PROCESSAMENTO DOS DADOS
        for doc in historico_docs:
            consulta = doc.to_dict()
            consulta['doc_id'] = doc.id
            
            # Formatação da data (apenas para exibição no template)
            if isinstance(consulta.get('dataHoraSessao'), str):
                # Tentativa de converter string para objeto datetime para formatação
                try:
                    dt_obj = datetime.strptime(consulta['dataHoraSessao'], '%Y-%m-%dT%H:%M')
                    consulta['data_formatada'] = dt_obj.strftime('%d/%m/%Y às %H:%M')
                except ValueError:
                    consulta['data_formatada'] = consulta['dataHoraSessao']
            else:
                 consulta['data_formatada'] = 'Data indisponível'
                
            historico_list.append(consulta)
        
        # 4. RENDERIZAÇÃO
        return render_template('historico.html', 
                               page_title='Histórico de Consultas',
                               historico=historico_list)

    except Exception as e:
        flash(f"Erro ao carregar o histórico: {e}", 'error')
        return redirect(url_for('dashboard'))

# ==========================================================
# 7. ROTAS DE ADMINISTRAÇÃO GERAL (CRUD COMPLETO)
# ==========================================================

def admin_required(f):
    """Verifica se o usuário logado é o administrador (pela role na session)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('user_role') != 'admin':
            flash("Acesso negado. Você precisa ser o Administrador para acessar esta área.", 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    # Usa a função corrigida para exibir todos os psicólogos cadastrados
    psicologos_cadastrados = process_psicologos_for_template(get_all_psicologos())
    
    return render_template('admin/dashboard.html', 
                            page_title='Admin | Painel Geral',
                            psicologos=psicologos_cadastrados)

@app.route('/admin/cadastro_psicologo', methods=['GET', 'POST'])
@admin_required
def cadastro_psicologo():
    
    if request.method == 'POST':
        email = request.form.get('email')
        senha = request.form.get('senha')
        nome = request.form.get('nome')
        genero = request.form.get('genero')
        
        try:
            valorSessao = float(request.form.get('valorSessao'))
        except ValueError:
            flash("O valor da sessão deve ser um número válido.", 'error')
            return redirect(url_for('cadastro_psicologo'))

        tags = [tag.strip() for tag in request.form.get('tags').split(',') if tag.strip()]
        descricaoCurta = request.form.get('descricaoCurta')
        
        # 🚨 Lógica de Upload da Foto
        file = request.files.get('foto_perfil')
        avatar_filename = '' # Nome do arquivo que será salvo no DB (padrão é vazio)
        
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            # Gera um nome de arquivo único para evitar colisões
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            try:
                # Salva o arquivo no sistema de arquivos
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                avatar_filename = unique_filename # Salva APENAS o nome único
            except Exception as e:
                flash(f"Aviso: Erro ao salvar o arquivo de foto: {e}. O cadastro continuará sem a foto.", 'warning')
                avatar_filename = 'default_avatar.jpg' # Usa o default em caso de erro de I/O
        else:
             # Se nenhum arquivo foi enviado ou a extensão é inválida
             avatar_filename = 'default_avatar.jpg'


        if not db:
            flash("Erro: Conexão com o Banco de Dados (Firebase) indisponível. Não foi possível cadastrar.", 'error')
            return redirect(url_for('cadastro_psicologo'))

        try:
            # 1. Cria o Usuário no Firebase Authentication (Login)
            user = auth.create_user(
                email=email,
                password=senha,
                display_name=nome,
                disabled=False
            )
            psicologo_uid = user.uid

            # 2. Salva o Perfil no Firestore
            db_data_to_save = {
                'nome': nome,
                'email': email,
                'genero': genero,
                'valorSessao': valorSessao,
                # Armazenamos as tags/especialidades como uma lista no DB
                'especialidades': tags, 
                'bio': descricaoCurta,   
                'fotoURL': avatar_filename, # 🚨 Nome do arquivo salvo no DB
                'cadastradoEm': firestore.SERVER_TIMESTAMP
            }
            
            # Usa o UID do Auth como ID do documento no Firestore
            db.collection('psicologos').document(psicologo_uid).set(db_data_to_save)
            
            flash(f"Psicólogo {nome} cadastrado com sucesso! ID: {psicologo_uid}", 'success')
            return redirect(url_for('admin_dashboard'))

        except firebase_admin.exceptions.FirebaseError as e:
            # Em caso de erro do Firebase (ex: e-mail já existe), tentamos limpar o arquivo salvo
            if avatar_filename != 'default_avatar.jpg' and os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], avatar_filename)):
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], avatar_filename))
                
            flash(f"Erro no Firebase (Auth/DB): {e}", 'error')
        except Exception as e:
            flash(f"Erro inesperado durante o cadastro: {e}", 'error')
            
    return render_template('admin/cadastro_psicologo.html', page_title='Admin | Novo Psicólogo')

# ROTA DE EDIÇÃO (Corrigida)
@app.route('/admin/psicologo/<psicologo_uid>/editar', methods=['GET', 'POST'])
@admin_required
def editar_psicologo(psicologo_uid):
    
    psicologo_ref = db.collection('psicologos').document(psicologo_uid)
    
    if request.method == 'POST':
        try:
            valorSessao = float(request.form.get('valorSessao'))
        except ValueError:
            flash("O valor da sessão deve ser um número válido.", 'error')
            return redirect(url_for('editar_psicologo', psicologo_uid=psicologo_uid))

        tags = [tag.strip() for tag in request.form.get('tags').split(',') if tag.strip()]
        
        # 🚨 Lógica de Upload/Atualização da Foto (Simplificada para edição)
        file = request.files.get('foto_perfil')
        avatar_filename = None # Inicia como None para não alterar se nenhum arquivo for enviado
        
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            try:
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                avatar_filename = unique_filename
                flash("Nova foto de perfil enviada com sucesso.", 'info')
            except Exception as e:
                flash(f"Aviso: Erro ao salvar a nova foto: {e}. A foto antiga será mantida.", 'warning')
        
        
        dados_atualizados = {
            'nome': request.form.get('nome'),
            'genero': request.form.get('genero'),
            'valorSessao': valorSessao,
            'especialidades': tags, # Usa 'especialidades' para salvar no DB
            'bio': request.form.get('descricaoCurta'), # Usa 'bio' para salvar no DB
            'email': request.form.get('email')
        }

        # Adiciona o novo nome do arquivo APENAS se um novo arquivo foi enviado
        if avatar_filename:
             dados_atualizados['fotoURL'] = avatar_filename

        try:
            # 1. Atualiza o Firestore
            psicologo_ref.update(dados_atualizados)
            
            # Não precisamos mais atualizar o MOCK aqui
            
            flash(f"Psicólogo {dados_atualizados['nome']} atualizado com sucesso!", 'success')
            return redirect(url_for('admin_dashboard'))

        except Exception as e:
            flash(f"Erro ao atualizar o psicólogo: {e}", 'error')
            return redirect(url_for('editar_psicologo', psicologo_uid=psicologo_uid))

    else:
        # GET: Carrega os dados atuais (Prioriza DB)
        psicologo = None
        
        if db:
            try:
                # Usa get_all_psicologos para garantir o mapeamento de campos (bio->descricaoCurta, etc)
                todos_psicologos = get_all_psicologos()
                psicologo = next((p for p in todos_psicologos if p['id'] == psicologo_uid), None)

            except Exception:
                pass 

        if not psicologo:
             # Se não encontrou no DB ou o DB está offline, busca no MOCK (get_all_psicologos já retorna o mock se DB falhar)
             psicologo = next((p for p in get_all_psicologos() if p['id'] == psicologo_uid), None)

        if not psicologo:
             flash("Erro ao carregar dados do psicólogo. Não encontrado no DB ou MOCK.", 'error')
             return redirect(url_for('admin_dashboard'))

        if not isinstance(psicologo.get('tags'), list):
             psicologo['tags'] = []
        
        # Para exibir a foto atual no template de edição, precisamos do URL
        psicologo = process_psicologos_for_template([psicologo])[0]

        return render_template('admin/editar_psicologo.html', 
                                page_title='Admin | Editar Profissional',
                                psicologo=psicologo)

# ROTA DE EXCLUSÃO (Corrigida)
@app.route('/admin/psicologo/<psicologo_uid>/excluir', methods=['POST'])
@admin_required
def excluir_psicologo(psicologo_uid):
    
    if not db:
        flash("Erro: Conexão com o Banco de Dados (Firebase) indisponível. A exclusão não foi realizada.", 'error')
        return redirect(url_for('admin_dashboard'))
    
    # Tenta obter o nome da foto antes de excluir o registro
    foto_para_deletar = 'default_avatar.jpg'
    try:
        doc = db.collection('psicologos').document(psicologo_uid).get()
        if doc.exists:
             foto_para_deletar = doc.to_dict().get('fotoURL', 'default_avatar.jpg')
    except Exception as e:
        print(f"Aviso: Não foi possível obter o nome da foto antes de excluir: {e}")


    try:
        # 1. Exclui do Firebase Authentication
        auth.delete_user(psicologo_uid)
        
        # 2. Exclui do Firestore
        db.collection('psicologos').document(psicologo_uid).delete()
        
        # 3. Exclui a imagem física (se não for o default)
        if foto_para_deletar != 'default_avatar.jpg':
             caminho_foto = os.path.join(app.config['UPLOAD_FOLDER'], foto_para_deletar)
             if os.path.exists(caminho_foto):
                 os.remove(caminho_foto)
                 print(f"Foto excluída do sistema de arquivos: {foto_para_deletar}")
                 
        flash(f"Psicólogo (ID: {psicologo_uid}) foi excluído com sucesso do Auth, DB e arquivos.", 'success')

    except auth.UserNotFoundError:
        # A conta Auth não existia, apenas exclui do DB/Mock
        db.collection('psicologos').document(psicologo_uid).delete()
        flash(f"Psicólogo (ID: {psicologo_uid}) excluído apenas do DB (Não estava no Auth).", 'info')
        
    except Exception as e:
        flash(f"Erro ao tentar excluir o psicólogo: {e}", 'error')

    return redirect(url_for('admin_dashboard'))

# Adicione na Seção 6 (Rotas do Psicólogo) do seu app.py

@app.route('/psicologo/agendamento/excluir/<doc_id>', methods=['POST'])

def excluir_agendamento(doc_id):
    # O decorator @psicologo_required ou a verificação de segurança (session.get('user_role'))
    # já deve garantir que apenas o psicólogo acesse.
        
    try:
        # Assumindo 'db' é o seu objeto firestore.client()
        db.collection('agendamentos').document(doc_id).delete()
        
        flash("Registro excluído com sucesso.", 'success')
        
    except Exception as e:
        print(f"Erro ao excluir agendamento {doc_id}: {e}")
        flash(f"Erro ao excluir o registro. Tente novamente.", 'error')
        
    # Redireciona de volta para o Dashboard, mantendo o usuário na página de gestão
    return redirect(url_for('dashboard'))

# Adicione na Seção 6 (Rotas Protegidas do Psicólogo) do seu app.py

@app.route('/psicologo/agendamento/confirmar/<doc_id>', methods=['POST'])
def confirmar_agendamento(doc_id):
    # Verificação básica de segurança
    if session.get('user_role') != 'psicologo':
        flash("Acesso negado.", 'error')
        return redirect(url_for('login'))
        
    if not db:
        flash("Erro de conexão com o Banco de Dados.", 'error')
        return redirect(url_for('dashboard'))

    try:
        # Atualiza apenas o campo 'status'
        db.collection('agendamentos').document(doc_id).update({
            'status': 'Confirmado'
        })
        
        flash("Agendamento confirmado e movido para 'Sessões Confirmadas'.", 'success')
        
    except Exception as e:
        print(f"Erro ao confirmar agendamento {doc_id}: {e}")
        flash(f"Erro ao confirmar o agendamento. Tente novamente.", 'error')
        
    # Redireciona de volta para o Dashboard
    return redirect(url_for('dashboard'))


# ==========================================================
# 8. ROTAS PÚBLICAS (FLUXO DO CLIENTE)
# ==========================================================

@app.route('/')
def index():
    # USA A FUNÇÃO CORRIGIDA PARA OBTER OS DADOS DO FIREBASE
    psicologos = get_all_psicologos() 
    
    psicologos_com_url = process_psicologos_for_template(psicologos)
    return render_template('index.html', page_title='Home', psicologos=psicologos_com_url)

@app.route('/triagem', methods=['GET', 'POST'])
def triagem():
    if request.method == 'POST':
        nivel_ansiedade = request.form.get('ansiedade')
        nivel_depressao = request.form.get('depressao')
        problema_principal = request.form.get('foco_principal')
        preferencia_genero = request.form.get('genero')
        
        focos_recomendados = []
        if problema_principal:
            focos_recomendados.append(problema_principal)

        if nivel_ansiedade and int(nivel_ansiedade) >= 4:
            focos_recomendados.append("Ansiedade")
        
        if nivel_depressao and int(nivel_depressao) >= 4:
            focos_recomendados.append("Depressão")

        if "Ansiedade" in focos_recomendados or "Estresse" in focos_recomendados:
              linha_recomendada = "TCC"
        elif "Depressão" in focos_recomendados or "Luto" in focos_recomendados:
              linha_recomendada = "Psicanálise"
        else:
              linha_recomendada = ""

        session['triagem_filtros'] = {
            'genero': preferencia_genero,
            'foco': " ".join(list(set(focos_recomendados))), 
            'linha': linha_recomendada
        }

        flash("Excelente! Com base nas suas respostas, encontramos os profissionais mais adequados. Role para baixo para ver a lista.", 'success')
        return redirect(url_for('psicologos_list'))

    return render_template('triagem.html', page_title='Avaliação Rápida')

@app.route('/psicologos', methods=['GET', 'POST'])
def psicologos_list():
    # USA A FUNÇÃO CORRIGIDA PARA OBTER OS DADOS DO FIREBASE
    psicologos_base = get_all_psicologos() 
    psicologos_filtrados = psicologos_base # Começa a filtragem com todos os dados
    
    filtros = {}
    
    triagem_filtros = session.pop('triagem_filtros', None)
    if triagem_filtros:
        filtros = triagem_filtros
    
    elif request.method == 'POST':
        filtros = {
            'foco': request.form.get('foco'),
            'genero': request.form.get('genero'),
            'linha': request.form.get('linha')
        }

    if filtros:
        genero = filtros.get('genero')
        foco = filtros.get('foco')
        linha = filtros.get('linha')

        if genero and genero != "Indiferente":
            psicologos_filtrados = [p for p in psicologos_filtrados if p['genero'] == genero]
        
        if foco:
            foco_lower = foco.lower().strip()
            # Filtra pelos campos 'tags' e 'descricaoCurta'
            psicologos_filtrados = [p for p in psicologos_filtrados if any(foco_lower in tag.lower() for tag in p['tags']) or foco_lower in p['descricaoCurta'].lower()]
            
        if linha:
            linha_lower = linha.lower().strip()
            # Filtra pelo campo 'tags'
            psicologos_filtrados = [p for p in psicologos_filtrados if any(linha_lower in tag.lower() for tag in p['tags'])]


    psicologos_com_url = process_psicologos_for_template(psicologos_filtrados)
    return render_template('psicologos_list.html', 
                            page_title='Escolha o Profissional', 
                            psicologos=psicologos_com_url, 
                            filtros=filtros) 

@app.route('/agendamento/<psicologo_doc_id>', methods=['GET'])
def agendamento(psicologo_doc_id):
    # Busca a lista completa do DB/Mock
    psicologo = next((p for p in get_all_psicologos() if p['id'] == psicologo_doc_id), None)
        
    if not psicologo:
        flash("Psicólogo não encontrado.", 'error')
        return redirect(url_for('psicologos_list'))

    # Processa o URL do avatar
    psicologo_com_url = process_psicologos_for_template([psicologo])[0]
    
    return render_template('agendamento.html', 
                            page_title='Agendar', 
                            psicologo=psicologo_com_url, 
                            horarios=get_mock_horarios())

# Rota POST para o agendamento (Redirecionamento para pagamento)
@app.route('/agendamento/<psicologo_doc_id>', methods=['POST'])
def pagamento_redirect(psicologo_doc_id):
    # Busca a lista completa do DB/Mock
    psicologo = next((p for p in get_all_psicologos() if p['id'] == psicologo_doc_id), None)
        
    if not psicologo:
        flash("Erro ao processar agendamento: Psicólogo não encontrado.", 'error')
        return redirect(url_for('psicologos_list'))

    # Pega os dados do formulário
    data_hora_sessao = request.form.get('dataHoraSessao')
    sessao_tipo = request.form.get('sessaoTipo')
    duracao = request.form.get('duracao') # Adicionado para completar a lógica do formulário

    if not data_hora_sessao or not sessao_tipo or not duracao:
        flash("Por favor, selecione o tipo, a duração e o horário da sessão.", 'error')
        return redirect(url_for('agendamento', psicologo_doc_id=psicologo_doc_id))

    valor_base = float(psicologo['valorSessao']) 
    
    # Lógica de cálculo de valor
    if 'Casal' in sessao_tipo:
        valor_final = valor_base * 1.5
    elif 'Pacote' in sessao_tipo:
        valor_final = valor_base * 3.5 
    else:
        valor_final = valor_base
        
    # Salva dados temporários na sessão
    session['agendamento_temp'] = {
        'psicologo_id': psicologo_doc_id, # ID do psicólogo, usado para filtrar no dashboard!
        'psicologo_nome': psicologo['nome'],
        'dataHoraSessao': data_hora_sessao,
        'sessaoTipo': sessao_tipo,
        'duracao': duracao,
        'valor': int(valor_final),
    }

    return redirect(url_for('pagamento'))

@app.route('/pagamento', methods=['GET', 'POST'])
def pagamento():
    agendamento_temp = session.get('agendamento_temp')

    if not agendamento_temp:
        flash("Nenhum agendamento pendente.", 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        usuario_email = request.form.get('email')
        
        session_uuid = str(uuid.uuid4())
        link_sessao = f"https://psicoapp.com/sessao/{session_uuid}" 

       # ... (por volta da linha 483 no seu arquivo)
        # 1. Dicionário para o Firestore (USA firestore.SERVER_TIMESTAMP)
        dados_para_db = {
            'psicologo_id': agendamento_temp['psicologo_id'],
            'psicologo_nome': agendamento_temp['psicologo_nome'],
            'usuarioEmail': usuario_email,
            'dataHoraSessao': agendamento_temp['dataHoraSessao'],
            'sessaoTipo': agendamento_temp['sessaoTipo'],
            'duracao': agendamento_temp['duracao'], 
            'valor': agendamento_temp['valor'],
            'linkSessao': link_sessao,
            'status': 'Pendente', # <-- MUDAR AQUI: De 'Confirmado' para 'Pendente'
            'criadoEm': firestore.SERVER_TIMESTAMP
        }
# ...
        
        # 2. Dicionário para a Sessão do Flask (USA STRING DE DATA - Evita TypeError Sentinel)
        dados_para_session = {
            'psicologo_id': agendamento_temp['psicologo_id'],
            'psicologo_nome': agendamento_temp['psicologo_nome'],
            'usuarioEmail': usuario_email,
            'dataHoraSessao': agendamento_temp['dataHoraSessao'],
            'sessaoTipo': agendamento_temp['sessaoTipo'],
            'duracao': agendamento_temp['duracao'],
            'valor': agendamento_temp['valor'],
            'linkSessao': link_sessao,
            'status': 'Confirmado',
            'criadoEm': datetime.now().strftime("%d/%m/%Y %H:%M:%S") 
        }

        if db:
            try:
                # Salva o Dicionário com o Sentinel no Firestore
                db.collection('agendamentos').add(dados_para_db)
                
                # Salva o Dicionário Limpo na Sessão do Flask (CORRETO)
                session['agendamento_confirmado'] = dados_para_session
                del session['agendamento_temp']
                
                return redirect(url_for('success'))
            except Exception as e:
                flash(f"Erro ao salvar agendamento: {e}", 'error')
                return redirect(url_for('pagamento'))
        else:
            # Se DB está offline, salva o Dicionário Limpo na Sessão
            session['agendamento_confirmado'] = dados_para_session
            del session['agendamento_temp']
            flash("Pagamento simulado com sucesso! (DB offline)", 'info')
            return redirect(url_for('success'))
            
    return render_template('pagamento.html', page_title='Pagamento', agendamento=agendamento_temp)

@app.route('/success')
def success():
    agendamento_confirmado = session.pop('agendamento_confirmado', None)
    
    if not agendamento_confirmado:
        flash("Página acessada diretamente ou confirmação expirada. Por favor, verifique seu e-mail.", 'info')
        return redirect(url_for('index'))
        
    return render_template('success.html', page_title='Sucesso!', agendamento=agendamento_confirmado)

@app.route('/ajuda')
def ajuda():
    return render_template('ajuda.html', page_title='Ajuda 24H em Crise')
    
@app.route('/sessao/<session_id>')
def sala_sessao(session_id):
    mock_session_data = {
        'link_sessao': f"https://psicoapp.com/sessao/{session_id}",
        'psicologo_data': {
            'nome': 'Profissional PsicoAPP' 
        }
    }
    return render_template('sala_sessao.html', 
                            page_title='Sua Sessão', 
                            session_id=session_id, 
                            session=mock_session_data)
                            

# ==========================================================
# 9. INICIALIZAÇÃO DO SERVIDOR
# ==========================================================

# Este bloco é apenas para desenvolvimento local.
# O Gunicorn (em produção) e o Render ignorarão este bloco.
if __name__ == '__main__':
    print("Iniciando Flask em modo de desenvolvimento...")
    app.run(host='0.0.0.0', debug=True)