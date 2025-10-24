import streamlit as st
import pandas as pd
from gspread import service_account_from_dict
from datetime import datetime, timedelta
import json
from gspread.exceptions import WorksheetNotFound
# NOVO: Importa a biblioteca de autenticação
import streamlit_authenticator as stauth 
import yaml
from yaml.loader import SafeLoader

# --- Configurações da Nova Planilha ---
PLANILHA_NOME = "Controle_Obras_testes" # O nome da sua nova planilha
ABA_INFO = "Obras_Info"
ABA_DESPESAS = "Despesas_Semanas"

# --- Constantes para Navegação ---
PAGINAS = {
    "1. Cadastrar Nova Obra": "CADASTRO",
    "2. Registrar Despesa Semanal": "REGISTRO_DESPESA",
    "3. Status Financeiro das Obras": "CONSULTA_STATUS",
    "4. Gerar Relatório Detalhado": "RELATORIO"
}
PAGINAS_REVERSO = {v: k for k, v in PAGINAS.items()}

# --- Funções de Autenticação e Conexão ---

@st.cache_resource(ttl=None) # Cache eterno para o objeto de conexão
def get_gspread_client():
    """Conecta e retorna o cliente GSpread usando st.secrets."""
    try:
        if "gcp_service_account" not in st.secrets:
             raise ValueError("Nenhuma seção [gcp_service_account] encontrada no st.secrets.")

        secrets_dict = dict(st.secrets["gcp_service_account"])
        private_key_corrompida = secrets_dict["private_key"]

        # Lógica de limpeza da chave (necessária para chaves quebradas)
        private_key_limpa = private_key_corrompida.replace('\n', '').replace(' ', '')
        private_key_limpa = private_key_limpa.replace('-----BEGINPRIVATEKEY-----', '').replace('-----ENDPRIVATEKEY-----', '')
        padding_necessario = len(private_key_limpa) % 4
        if padding_necessario != 0:
            private_key_limpa += '=' * (4 - padding_necessario)
        secrets_dict["private_key"] = f"-----BEGIN PRIVATE KEY-----\n{private_key_limpa}\n-----END PRIVATE KEY-----\n"

        gc = service_account_from_dict(secrets_dict)
        return gc
    except Exception as e:
        st.error(f"Erro de autenticação/acesso: Verifique se a chave no secrets.toml está correta. Detalhe: {e}")
        return None

# --- Funções de Leitura de Dados (Banco de Dados) ---

@st.cache_data(ttl=600)
def load_data():
    """Carrega dados de ambas as abas e retorna dois DataFrames."""
    gc = get_gspread_client()
    
    if not gc:
        return pd.DataFrame(), pd.DataFrame()

    try:
        planilha = gc.open(PLANILHA_NOME)

        aba_info = planilha.worksheet(ABA_INFO)
        df_info = pd.DataFrame(aba_info.get_all_records())

        aba_despesas = planilha.worksheet(ABA_DESPESAS)
        df_despesas = pd.DataFrame(aba_despesas.get_all_records())

        # Limpeza e Conversão de Tipos (Checa se a coluna existe antes de tentar converter)
        if not df_info.empty:
            if 'Obra_ID' in df_info.columns: 
                 # Converte para INT e depois para STR (ex: 1 -> '1')
                 df_info['Obra_ID'] = pd.to_numeric(df_info['Obra_ID'], errors='coerce').fillna(0).astype(int).astype(str)
            if 'Valor_Total_Inicial' in df_info.columns: df_info['Valor_Total_Inicial'] = pd.to_numeric(df_info['Valor_Total_Inicial'], errors='coerce')
            if 'Data_Inicio' in df_info.columns: df_info['Data_Inicio'] = pd.to_datetime(df_info['Data_Inicio'], errors='coerce')

        if not df_despesas.empty:
            if 'Obra_ID' in df_despesas.columns: 
                # Converte para INT e depois para STR (ex: 1 -> '1')
                df_despesas['Obra_ID'] = pd.to_numeric(df_despesas['Obra_ID'], errors='coerce').fillna(0).astype(int).astype(str)
            if 'Gasto_Semana' in df_despesas.columns: df_despesas['Gasto_Semana'] = pd.to_numeric(df_despesas['Gasto_Semana'], errors='coerce')
            if 'Semana_Ref' in df_despesas.columns:
                 df_despesas['Semana_Ref'] = pd.to_numeric(df_despesas['Semana_Ref'], errors='coerce').fillna(0).astype(int)

        return df_info, df_despesas

    except WorksheetNotFound as e:
        st.error(f"Erro: A aba '{ABA_INFO}' ou '{ABA_DESPESAS}' não foi encontrada na planilha '{PLANILHA_NOME}'. Verifique os nomes.")
        return pd.DataFrame(), pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao carregar dados: {e}")
        return pd.DataFrame(), pd.DataFrame()


# --- Funções de Escrita de Dados (INSERT E UPDATE) ---

def insert_new_obra(gc, data):
    """Insere uma nova obra na aba Obras_Info, como número inteiro."""
    try:
        planilha = gc.open(PLANILHA_NOME)
        aba_info = planilha.worksheet(ABA_INFO)
        
        # O ID é passado como INT para que o Sheets o salve como NÚMERO
        data[0] = int(data[0]) 
        
        # CORREÇÃO: Removido 'raw=False'
        aba_info.append_row(data, insert_data_option='INSERT_ROWS')
        
        st.toast("✅ Nova obra cadastrada com sucesso!")
        load_data.clear()
    except Exception as e:
        # Apresenta o erro específico
        st.error(f"Erro ao inserir nova obra: {e}")

def update_obra_info(gc, obra_id, new_nome, new_valor, new_data_inicio):
    """Atualiza a obra buscando o ID como número inteiro no Sheets."""
    try:
        planilha = gc.open(PLANILHA_NOME)
        aba_info = planilha.worksheet(ABA_INFO)
        
        # Lemos todos os valores para fazer a busca manual (mais confiável com IDs numéricos)
        data = aba_info.get_all_values()
        
        sheets_row_index = -1
        # O ID deve ser tratado como número inteiro para a busca
        id_int_para_buscar = int(obra_id)
        
        # Procura a linha da Obra_ID
        for i, row in enumerate(data[1:]):
            try:
                # Compara o ID da linha como número inteiro (coluna 0)
                if int(row[0].strip() if row[0] else 0) == id_int_para_buscar: 
                    sheets_row_index = i + 2 # Índice da linha no Sheets é i + 2
                    break
            except ValueError:
                # Ignora linhas com IDs não numéricos
                continue
        
        if sheets_row_index == -1:
            st.warning(f"Obra ID {obra_id} não encontrada para atualização.")
            return

        # Novas colunas de dados na ordem: Obra_ID (como INT), Nome_Obra, Valor_Total_Inicial, Data_Inicio
        new_row_data = [
            id_int_para_buscar, # Passa o ID como INT
            str(new_nome),
            float(new_valor), 
            new_data_inicio.strftime('%Y-%m-%d') 
        ]
        
        # O intervalo é da coluna A até a D (assumindo 4 colunas)
        range_to_update = f'A{sheets_row_index}:D{sheets_row_index}'
        # Apenas passamos a lista de listas, sem value_input_option se não for estritamente necessário.
        aba_info.update(range_to_update, [new_row_data]) 
        
        st.toast(f"✅ Obra {obra_id} ({new_nome}) atualizada com sucesso!")
        load_data.clear()
        
    except Exception as e:
        st.error(f"Erro ao atualizar obra: {e}. Verifique se a coluna 'Obra_ID' é a primeira coluna na aba 'Obras_Info'.")


def insert_new_despesa(gc, data):
    """Insere uma nova despesa semanal na aba Despesas_Semanas."""
    try:
        planilha = gc.open(PLANILHA_NOME)
        aba_despesas = planilha.worksheet(ABA_DESPESAS)
        
        # O ID de obra deve ser INT para salvar corretamente no Sheets
        data_nativa = [int(data[0]), int(data[1]), data[2], float(data[3])]

        # CORREÇÃO: Removido 'raw=False'
        aba_despesas.append_row(data_nativa, insert_data_option='INSERT_ROWS')
        st.toast("✅ Despesa semanal registrada com sucesso!")
        load_data.clear()
    except Exception as e:
        # Apresenta o erro específico
        st.error(f"Erro ao registrar despesa: {e}")

def update_despesa(gc, obra_id, semana_ref, novo_gasto, nova_data):
    """Atualiza o gasto e a data de uma semana de referência específica."""
    try:
        planilha = gc.open(PLANILHA_NOME)
        aba_despesas = planilha.worksheet(ABA_DESPESAS)
        data = aba_despesas.get_all_values()
        
        sheets_row_index = -1
        # ID como INT para a comparação
        id_int_para_buscar = int(obra_id) 

        for i, row in enumerate(data[1:]):
            try:
                # Compara o ID da linha como número inteiro (coluna 0) e a semana
                if int(row[0].strip() if row[0] else 0) == id_int_para_buscar and int(row[1]) == int(semana_ref):
                    sheets_row_index = i + 2 
                    break
            except ValueError:
                 continue
        
        if sheets_row_index == -1:
            st.warning("Linha de despesa não encontrada para atualização.")
            return

        new_row_data = [
            id_int_para_buscar, # ID como INT
            int(semana_ref),
            nova_data.strftime('%Y-%m-%d'),
            float(novo_gasto)
        ]
        
        range_to_update = f'A{sheets_row_index}:D{sheets_row_index}'
        aba_despesas.update(range_to_update, [new_row_data])
        
        st.toast(f"✅ Semana {semana_ref} da Obra {obra_id} atualizada com sucesso!")
        load_data.clear()
        
    except Exception as e:
        st.error(f"Erro ao atualizar despesa: {e}")

# --- Funções Auxiliares de Formatação e Cálculo ---

def formatar_moeda(x):
    """Formata um número para o padrão de moeda R$"""
    if pd.isna(x):
        return "R$ 0,00"
    return f"R$ {float(x):,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")

def calcular_status_financeiro(df_info, df_despesas):
    """Função auxiliar para calcular o status financeiro (reutilizada no relatório)"""
    if not df_despesas.empty and 'Obra_ID' in df_despesas.columns and 'Gasto_Semana' in df_despesas.columns:
        df_despesas['Gasto_Semana'] = pd.to_numeric(df_despesas['Gasto_Semana'], errors='coerce').fillna(0)
        
        try:
            gastos_totais = df_despesas.groupby('Obra_ID')['Gasto_Semana'].sum().reset_index()
            gastos_totais.rename(columns={'Gasto_Semana': 'Gasto_Total_Acumulado'}, inplace=True)
        except:
            gastos_totais = pd.DataFrame({'Obra_ID': df_info['Obra_ID'].unique(), 'Gasto_Total_Acumulado': 0.0})
    else:
        gastos_totais = pd.DataFrame({'Obra_ID': df_info['Obra_ID'].unique(), 'Gasto_Total_Acumulado': 0.0})

    df_final = df_info.merge(gastos_totais, on='Obra_ID', how='left').fillna(0)
    df_final['Gasto_Total_Acumulado'] = df_final['Gasto_Total_Acumulado'].round(2)
    df_final['Sobrando_Financeiro'] = df_final['Valor_Total_Inicial'] - df_final['Gasto_Total_Acumulado']
    
    return df_final


# --- Funções das "Páginas" ---

def show_cadastro_obra(gc, df_info):
    st.title(PAGINAS_REVERSO["CADASTRO"])

    col_new, col_edit = st.columns(2)

    # --- Coluna 1: Cadastrar Nova Obra ---
    with col_new:
        st.subheader("Cadastrar Nova Obra")
        
        next_id = 1
        if not df_info.empty and 'Obra_ID' in df_info.columns:
            try:
                # O ID é tratado como int no dataframe para encontrar o máximo
                max_id = df_info['Obra_ID'].astype(int).max()
                next_id = max_id + 1
            except:
                next_id = len(df_info) + 1
        
        # O ID é o número inteiro, não a string formatada
        st.info(f"O próximo ID da Obra será: **{next_id}**")

        with st.form("form_nova_obra"):
            nome = st.text_input("Nome da Obra", placeholder="Ex: Casa Alpha")
            valor = st.number_input("Valor Total Inicial (R$)", min_value=0.0, format="%.2f")
            data_inicio = st.date_input("Data de Início da Obra")
            
            submitted = st.form_submit_button("Cadastrar Obra")
            
            if submitted:
                if nome and valor > 0:
                    # Passa o ID como o número inteiro
                    data_list = [next_id, nome, valor, data_inicio.strftime('%Y-%m-%d')]
                    insert_new_obra(gc, data_list)
                else:
                    st.warning("Preencha todos os campos corretamente.")

    # --- Coluna 2: Editar Obra Existente ---
    with col_edit:
        st.subheader("Editar Obra Existente")
        
        if df_info.empty:
            st.info("Nenhuma obra cadastrada para editar.")
        else:
            opcoes_obras = {f"{row['Nome_Obra']} ({row['Obra_ID']})": row['Obra_ID'] 
                            for index, row in df_info.iterrows()}
            
            obra_selecionada_str = st.selectbox("Selecione a Obra para Editar:", 
                                                list(opcoes_obras.keys()), 
                                                key="select_obra_edicao")

            if obra_selecionada_str:
                obra_id_para_editar = opcoes_obras[obra_selecionada_str]
                
                obra_data = df_info[df_info['Obra_ID'] == obra_id_para_editar].iloc[0]
                
                data_inicio_atual = obra_data['Data_Inicio'].date() if pd.notna(obra_data['Data_Inicio']) else datetime.today().date()
                
                with st.form("form_edicao_obra"):
                    st.markdown(f"**Editando: Obra {obra_id_para_editar}**")
                    
                    novo_nome = st.text_input("Novo Nome da Obra", 
                                              value=obra_data['Nome_Obra'], 
                                              key="edit_nome")
                                              
                    novo_valor = st.number_input("Novo Valor Total Inicial (R$)", 
                                                 min_value=0.0, 
                                                 value=float(obra_data['Valor_Total_Inicial']), 
                                                 format="%.2f", 
                                                 key="edit_valor")
                                                 
                    nova_data_inicio = st.date_input("Nova Data de Início", 
                                                      value=data_inicio_atual,
                                                      key="edit_data_inicio")
                    
                    submitted_edit = st.form_submit_button("Salvar Edição da Obra")
                    
                    if submitted_edit:
                        if novo_nome and novo_valor >= 0:
                            update_obra_info(gc, obra_id_para_editar, novo_nome, novo_valor, nova_data_inicio)
                        else:
                            st.warning("Preencha o nome e um valor inicial válido.")


def show_registro_despesa(gc, df_info, df_despesas):
    st.title(PAGINAS_REVERSO["REGISTRO_DESPESA"])

    if df_info.empty:
        st.warning("Cadastre pelo menos uma obra para registrar despesas.")
        return

    opcoes_obras = {f"{row['Nome_Obra']} ({row['Obra_ID']})": row['Obra_ID']
                    for index, row in df_info.iterrows()}

    obra_selecionada_str = st.selectbox("Selecione a Obra:", list(opcoes_obras.keys()), key="select_obra_registro")

    if obra_selecionada_str:
        obra_id = opcoes_obras[obra_selecionada_str]
        
        if df_despesas.empty or 'Obra_ID' not in df_despesas.columns or 'Semana_Ref' not in df_despesas.columns:
            despesas_obra = pd.DataFrame()
        else:
            despesas_obra = df_despesas[df_despesas['Obra_ID'].astype(str) == str(obra_id)].copy()
        
        col1_reg, col2_edit = st.columns([1, 1.2]) 

        with col1_reg:
            st.subheader(f"Novo Gasto (Obra: {obra_id})")
            
            if despesas_obra.empty:
                proxima_semana = 1
            else:
                proxima_semana = despesas_obra['Semana_Ref'].max() + 1
                
            st.info(f"Próxima semana de referência a ser registrada: **Semana {proxima_semana}**")

            with st.form("form_despesa"):
                gasto = st.number_input("Gasto Total na Semana (R$)", min_value=0.0, format="%.2f", key="new_gasto")
                data_semana = st.date_input("Data de Referência da Semana", key="new_data")
                
                submitted = st.form_submit_button("Registrar Novo Gasto")
                
                if submitted:
                    if gasto > 0:
                        # O ID está como string '1', '2', etc.
                        data_list = [obra_id, proxima_semana, data_semana.strftime('%Y-%m-%d'), gasto]
                        insert_new_despesa(gc, data_list)
                    else:
                        st.warning("O valor do gasto deve ser maior que R$ 0,00.")


        with col2_edit:
            st.subheader(f"Detalhes e Edição ({len(despesas_obra)} Semanas)")
            
            if despesas_obra.empty:
                st.info("Nenhum gasto registrado para esta obra.")
            else:
                despesas_display = despesas_obra.sort_values('Semana_Ref', ascending=False).copy()
                despesas_display['Gasto_Semana'] = despesas_display['Gasto_Semana'].apply(lambda x: formatar_moeda(x))
                despesas_display = despesas_display.rename(columns={'Semana_Ref': 'Semana', 'Data_Semana': 'Data Ref.', 'Gasto_Semana': 'Gasto'})
                
                semanas_opcoes = despesas_obra['Semana_Ref'].sort_values(ascending=False).tolist()
                semana_selecionada = st.selectbox(
                    "Selecione a Semana para Detalhar/Editar:", 
                    semanas_opcoes, 
                    format_func=lambda x: f"Semana {x}",
                    key="select_semana_edicao"
                )
                
                if semana_selecionada:
                    linha_edicao = despesas_obra[despesas_obra['Semana_Ref'] == semana_selecionada].iloc[0]
                    # Data lida como string, então precisa de conversão
                    data_atual = datetime.strptime(linha_edicao['Data_Semana'], '%Y-%m-%d').date()
                    gasto_atual = float(linha_edicao['Gasto_Semana'])

                    with st.expander(f"Editar Detalhes da Semana {semana_selecionada}", expanded=True):
                        with st.form(f"form_edicao_semana_{semana_selecionada}"):
                            
                            st.markdown(f"**Editando: Obra {obra_id} - Semana {semana_selecionada}**")
                            
                            novo_gasto = st.number_input("Novo Gasto Total (R$)", min_value=0.0, value=gasto_atual, format="%.2f", key="edit_gasto")
                            nova_data = st.date_input("Nova Data de Referência", value=data_atual, key="edit_data")
                            
                            submitted_edit = st.form_submit_button("Salvar Alterações")
                            
                            if submitted_edit:
                                if novo_gasto >= 0:
                                    update_despesa(gc, obra_id, semana_selecionada, novo_gasto, nova_data)
                                else:
                                    st.warning("O valor do gasto não pode ser negativo.")
                            
                    st.markdown("---")
                    st.markdown("**Histórico de Gastos:**")
                    st.dataframe(
                        despesas_display[['Semana', 'Data Ref.', 'Gasto', 'Obra_ID']], 
                        use_container_width=True,
                        hide_index=True
                    )
@st.cache_data(ttl=3600) # Cache para a lista de usuários
def load_users(gc):
    """Carrega usuários e hashes de senha da aba 'Usuarios'."""
    try:
        planilha = gc.open(PLANILHA_NOME)
        aba_usuarios = planilha.worksheet("Usuarios")
        df_users = pd.DataFrame(aba_usuarios.get_all_records())

        if df_users.empty:
            st.error("A aba 'Usuarios' está vazia ou não foi encontrada. Autenticação desabilitada.")
            return None
        
        # Garante que as colunas necessárias estão presentes
        required_cols = ['name', 'username', 'password']
        if not all(col in df_users.columns for col in required_cols):
             st.error(f"A aba 'Usuarios' deve conter as colunas: {required_cols}")
             return None

        # Formata os dados para o stauth, usando as senhas JÁ HASHED da planilha
        usernames_dict = {
            row['username']: {
                'email': f"{row['username']}@app.com",
                'name': row['name'],
                # A senha LIDA AQUI DEVE SER O HASH GERADO NO PASSO 2
                'password': row['password'] 
            }
            for index, row in df_users.iterrows()
        }
        return usernames_dict
        
    except WorksheetNotFound:
        st.error("Erro: Aba 'Usuarios' não encontrada na planilha. Crie a aba.")
        return None
    except Exception as e:
        st.error(f"Erro ao carregar usuários: {e}")
        return None

def show_consulta_dados(df_info, df_despesas):
    st.title(PAGINAS_REVERSO["CONSULTA_STATUS"])
    
    if df_info.empty:
        st.info("Nenhuma obra cadastrada para consultar.")
        return

    df_final = calcular_status_financeiro(df_info, df_despesas)
    
    df_display = df_final[[
        'Obra_ID', 'Nome_Obra', 'Valor_Total_Inicial', 'Gasto_Total_Acumulado', 'Sobrando_Financeiro', 'Data_Inicio'
    ]].copy()

    df_display['Valor_Total_Inicial'] = df_display['Valor_Total_Inicial'].apply(formatar_moeda)
    df_display['Gasto_Total_Acumulado'] = df_display['Gasto_Total_Acumulado'].apply(formatar_moeda)
    df_display['Sobrando_Financeiro'] = df_display['Sobrando_Financeiro'].apply(formatar_moeda)

    st.dataframe(df_display, use_container_width=True)


def show_relatorio_obra(gc, df_info, df_despesas):
    st.title(PAGINAS_REVERSO["RELATORIO"])

    if df_info.empty:
        st.info("Nenhuma obra cadastrada para gerar relatório.")
        return

    opcoes_obras = {f"{row['Nome_Obra']} ({row['Obra_ID']})": row['Obra_ID']
                    for index, row in df_info.iterrows()}

    obra_selecionada_str = st.selectbox("Selecione a Obra para Relatório:", list(opcoes_obras.keys()), key="select_obra_relatorio")

    if obra_selecionada_str:
        obra_id = opcoes_obras[obra_selecionada_str]
        df_status = calcular_status_financeiro(df_info, df_despesas)
        
        info_obra = df_status[df_status['Obra_ID'] == obra_id].iloc[0]
        despesas_obra = df_despesas[df_despesas['Obra_ID'].astype(str) == str(obra_id)].copy()
        
        st.markdown("---")
        st.subheader(f"Relatório de Acompanhamento: {info_obra['Nome_Obra']}")
        
        #st.markdown("""
        #**DICA PARA PDF/IMPRESSÃO:** Use a função de impressão do seu navegador (Ctrl+P ou Cmd+P) e escolha 'Salvar como PDF' para gerar o documento.
        #""")
        
        col_det1, col_det2 = st.columns(2)
        
        with col_det1:
            st.metric("ID da Obra", info_obra['Obra_ID'])
            st.metric("Data de Início", info_obra['Data_Inicio'].strftime('%d/%m/%Y') if pd.notna(info_obra['Data_Inicio']) else "N/A")
            
        with col_det2:
            st.metric("Orçamento Inicial", formatar_moeda(info_obra['Valor_Total_Inicial']))
            st.metric("Gasto Total Acumulado", formatar_moeda(info_obra['Gasto_Total_Acumulado']))
        
        st.markdown(f"### **Saldo Restante:** {formatar_moeda(info_obra['Sobrando_Financeiro'])}")
        
        st.markdown("---")
        st.markdown("#### Histórico de Despesas Semanais")

        
        
        if despesas_obra.empty:
            st.info("Nenhum registro de despesa semanal encontrado para esta obra.")
        else:
            despesas_display = despesas_obra.sort_values('Semana_Ref', ascending=True).copy()
            despesas_display['Gasto_Semana'] = despesas_display['Gasto_Semana'].apply(formatar_moeda)
            despesas_display['Data_Semana'] = pd.to_datetime(despesas_display['Data_Semana']).dt.strftime('%d/%m/%Y')
            
            df_relatorio = despesas_display[['Semana_Ref', 'Data_Semana', 'Gasto_Semana']].rename(columns={
                'Semana_Ref': 'Semana', 'Data_Semana': 'Data Referência', 'Gasto_Semana': 'Gasto da Semana'
            })

            st.dataframe(df_relatorio, use_container_width=True, hide_index=True)

# --- Lógica de Autenticação (MODIFICADA) ---

def get_authenticator():
    """Configura e retorna o objeto Authenticator LENDO DO SHEETS."""
    gc = get_gspread_client()
    if not gc:
        return None, None, None
        
    usernames_dict = load_users(gc)
    
    if not usernames_dict:
        return None, None, None

    # NOVO: Formata os dados para o stauth, que agora contém as senhas hashed do Sheets
    config_data = {
        'credentials': {
            'usernames': usernames_dict
        },
        'cookie': {
            # Manter as informações do secrets.toml para cookie
            'name': st.secrets['credentials']['cookie_name'],
            'key': st.secrets['credentials']['cookie_key'],
            'expiry_days': st.secrets['credentials']['cookie_expiry_days']
        },
        'preauthorized': {
            'emails': []
        }
    }
    
    authenticator = stauth.Authenticate(
        config_data['credentials'],
        config_data['cookie']['name'],
        config_data['cookie']['key'],
        config_data['cookie']['expiry_days']
    )
    
    # Retorna o autenticador e as listas de nomes de usuário e nomes reais
    return authenticator, list(usernames_dict.keys()), [d['name'] for d in usernames_dict.values()]
# --- Funções de Navegação e Layout ---

def navigate_to(page_key):
    """Função que altera a página no estado da sessão."""
    st.session_state.current_page = page_key

def setup_navigation():
    """Cria os botões de navegação no topo da página."""
    cols = st.columns(len(PAGINAS))
    
    for i, (label, key) in enumerate(PAGINAS.items()):
        is_active = st.session_state.current_page == key
        
        with cols[i]:
            if st.button(label, on_click=navigate_to, args=(key,), type="primary" if is_active else "secondary", use_container_width=True):
                pass


# --- Aplicação Principal ---

def main():
    st.set_page_config(page_title="Controle Financeiro de Obras", layout="wide")
    st.title("🚧 Sistema de Gerenciamento de Obras")
    
    # 1. Inicializar o estado da sessão (se não estiver definido)
    if 'current_page' not in st.session_state:
        st.session_state.current_page = PAGINAS["1. Cadastrar Nova Obra"]
    
    st.markdown("---")
    
    # 2. Configurar e mostrar os botões de navegação
    setup_navigation()
    
    st.markdown("---")

    gc = get_gspread_client()
    if not gc:
        st.error("Falha na conexão com o Google Sheets. Verifique a autenticação.")
        st.stop()
        
    df_info, df_despesas = load_data()
    
    # 3. Lógica principal para exibir a página correta
    current_page = st.session_state.current_page

    if current_page == "CADASTRO":
        show_cadastro_obra(gc, df_info)
    elif current_page == "REGISTRO_DESPESA":
        show_registro_despesa(gc, df_info, df_despesas)
    elif current_page == "CONSULTA_STATUS":
        show_consulta_dados(df_info, df_despesas)
    elif current_page == "RELATORIO":
        show_relatorio_obra(gc, df_info, df_despesas)

if __name__ == "__main__":
    main()
