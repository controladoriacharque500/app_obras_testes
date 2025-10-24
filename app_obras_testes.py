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

        # =========================================================================
        # CORREÇÃO CRÍTICA PARA TRATAMENTO DE TIPOS E GARANTIA DE CONSISTÊNCIA
        # =========================================================================
        
        if not df_info.empty:
            if 'Obra_ID' in df_info.columns: 
                 # Converte para INT (para encontrar o máximo) e DEPOIS para STR
                 df_info['Obra_ID'] = pd.to_numeric(df_info['Obra_ID'], errors='coerce').fillna(0).astype(int).astype(str)
            if 'Valor_Total_Inicial' in df_info.columns: df_info['Valor_Total_Inicial'] = pd.to_numeric(df_info['Valor_Total_Inicial'], errors='coerce')
            if 'Data_Inicio' in df_info.columns: df_info['Data_Inicio'] = pd.to_datetime(df_info['Data_Inicio'], errors='coerce')
            
            # Garante que as colunas importantes para cálculo existam e tenham valores numéricos
            if 'Valor_Total_Inicial' not in df_info.columns:
                df_info['Valor_Total_Inicial'] = 0.0

        if not df_despesas.empty:
            if 'Obra_ID' in df_despesas.columns: 
                # Converte para INT e DEPOIS para STR
                df_despesas['Obra_ID'] = pd.to_numeric(df_despesas['Obra_ID'], errors='coerce').fillna(0).astype(int).astype(str)
            if 'Gasto_Semana' in df_despesas.columns: 
                df_despesas['Gasto_Semana'] = pd.to_numeric(df_despesas['Gasto_Semana'], errors='coerce')
            if 'Semana_Ref' in df_despesas.columns:
                 df_despesas['Semana_Ref'] = pd.to_numeric(df_despesas['Semana_Ref'], errors='coerce').fillna(0).astype(int)
                 
            # Garante que as colunas importantes para cálculo existam e tenham valores numéricos
            if 'Gasto_Semana' not in df_despesas.columns:
                 df_despesas['Gasto_Semana'] = 0.0
            
        return df_info, df_despesas

    except WorksheetNotFound as e:
        st.error(f"Erro: A aba '{ABA_INFO}' ou '{ABA_DESPESAS}' não foi encontrada na planilha '{PLANILHA_NOME}'. Verifique os nomes.")
        return pd.DataFrame(), pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao carregar dados: {e}")
        return pd.DataFrame(), pd.DataFrame()


# --- Funções de Escrita de Dados (INSERT E UPDATE) ---

def insert_new_obra(data):
    """Insere uma nova obra na aba Obras_Info, como número inteiro."""
    gc = get_gspread_client() # Obtém o cliente GSpread aqui
    if not gc: return 
    
    try:
        planilha = gc.open(PLANILHA_NOME)
        aba_info = planilha.worksheet(ABA_INFO)
        
        # O ID é passado como INT para que o Sheets o salve como NÚMERO
        data[0] = int(data[0]) 
        
        aba_info.append_row(data, insert_data_option='INSERT_ROWS')
        
        st.toast("✅ Nova obra cadastrada com sucesso!")
        load_data.clear()
    except Exception as e:
        st.error(f"Erro ao inserir nova obra: {e}")

def update_obra_info(obra_id, new_nome, new_valor, new_data_inicio):
    """Atualiza a obra buscando o ID como número inteiro no Sheets."""
    gc = get_gspread_client() # Obtém o cliente GSpread aqui
    if not gc: return 
    
    try:
        planilha = gc.open(PLANILHA_NOME)
        aba_info = planilha.worksheet(ABA_INFO)
        
        data = aba_info.get_all_values()
        sheets_row_index = -1
        id_int_para_buscar = int(obra_id)
        
        for i, row in enumerate(data[1:]):
            try:
                if int(row[0].strip() if row[0] else 0) == id_int_para_buscar: 
                    sheets_row_index = i + 2
                    break
            except ValueError:
                continue
        
        if sheets_row_index == -1:
            st.warning(f"Obra ID {obra_id} não encontrada para atualização.")
            return

        new_row_data = [
            id_int_para_buscar, 
            str(new_nome),
            float(new_valor), 
            new_data_inicio.strftime('%Y-%m-%d') 
        ]
        
        range_to_update = f'A{sheets_row_index}:D{sheets_row_index}'
        aba_info.update(range_to_update, [new_row_data]) 
        
        st.toast(f"✅ Obra {obra_id} ({new_nome}) atualizada com sucesso!")
        load_data.clear()
        
    except Exception as e:
        st.error(f"Erro ao atualizar obra: {e}. Verifique se a coluna 'Obra_ID' é a primeira coluna na aba 'Obras_Info'.")


def insert_new_despesa(data):
    """Insere uma nova despesa semanal na aba Despesas_Semanas."""
    gc = get_gspread_client() # Obtém o cliente GSpread aqui
    if not gc: return
    
    try:
        planilha = gc.open(PLANILHA_NOME)
        aba_despesas = planilha.worksheet(ABA_DESPESAS)
        
        # O ID de obra e Semana devem ser INT. Gasto deve ser FLOAT.
        data_nativa = [int(data[0]), int(data[1]), data[2], float(data[3])]

        aba_despesas.append_row(data_nativa, insert_data_option='INSERT_ROWS')
        st.toast("✅ Despesa semanal registrada com sucesso!")
        load_data.clear()
    except Exception as e:
        # Erro de serialização: "Object of type int64 is not JSON serializable"
        # Isso não deve mais ocorrer, pois convertemos para tipos nativos do Python
        st.error(f"Erro ao registrar despesa: {e}")

def update_despesa(obra_id, semana_ref, novo_gasto, nova_data):
    """Atualiza o gasto e a data de uma semana de referência específica."""
    gc = get_gspread_client() # Obtém o cliente GSpread aqui
    if not gc: return
    
    try:
        planilha = gc.open(PLANILHA_NOME)
        aba_despesas = planilha.worksheet(ABA_DESPESAS)
        data = aba_despesas.get_all_values()
        
        sheets_row_index = -1
        id_int_para_buscar = int(obra_id) 

        for i, row in enumerate(data[1:]):
            try:
                if int(row[0].strip() if row[0] else 0) == id_int_para_buscar and int(row[1]) == int(semana_ref):
                    sheets_row_index = i + 2 
                    break
            except ValueError:
                 continue
        
        if sheets_row_index == -1:
            st.warning("Linha de despesa não encontrada para atualização.")
            return

        new_row_data = [
            id_int_para_buscar, 
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
    
    # CORREÇÃO: Verificação robusta para evitar KeyError no groupby
    if (not df_despesas.empty and 
        'Obra_ID' in df_despesas.columns and 
        'Gasto_Semana' in df_despesas.columns and
        len(df_despesas['Obra_ID'].unique()) > 0 # Garante que há algo para agrupar
       ):
        try:
            # Garante que Gasto_Semana é numérico antes de somar
            df_despesas['Gasto_Semana'] = pd.to_numeric(df_despesas['Gasto_Semana'], errors='coerce').fillna(0)
            
            gastos_totais = df_despesas.groupby('Obra_ID', dropna=False)['Gasto_Semana'].sum().reset_index()
            gastos_totais.rename(columns={'Gasto_Semana': 'Gasto_Total_Acumulado'}, inplace=True)
            
        except Exception as e:
            # Caso o groupby falhe por algum motivo (estrutura inesperada, por exemplo)
            st.warning(f"Erro ao calcular gastos acumulados. Detalhe: {e}")
            gastos_totais = pd.DataFrame({'Obra_ID': df_info['Obra_ID'].unique(), 'Gasto_Total_Acumulado': 0.0})
    else:
        # Cria um DF zerado para evitar merge com erro
        if 'Obra_ID' in df_info.columns:
            gastos_totais = pd.DataFrame({'Obra_ID': df_info['Obra_ID'].unique(), 'Gasto_Total_Acumulado': 0.0})
        else:
            gastos_totais = pd.DataFrame({'Obra_ID': [], 'Gasto_Total_Acumulado': []})


    # Garante que 'Valor_Total_Inicial' é numérico para o cálculo
    df_info['Valor_Total_Inicial'] = pd.to_numeric(df_info.get('Valor_Total_Inicial', 0.0), errors='coerce').fillna(0)
    
    df_final = df_info.merge(gastos_totais, on='Obra_ID', how='left').fillna(0)
    
    # Garante que o merge trouxe a coluna, se não, cria com 0
    if 'Gasto_Total_Acumulado' not in df_final.columns:
        df_final['Gasto_Total_Acumulado'] = 0.0
        
    df_final['Gasto_Total_Acumulado'] = df_final['Gasto_Total_Acumulado'].round(2)
    df_final['Sobrando_Financeiro'] = df_final['Valor_Total_Inicial'] - df_final['Gasto_Total_Acumulado']
    
    return df_final


# --- Funções das "Páginas" ---

def show_cadastro_obra(df_info): 
    st.title(PAGINAS_REVERSO["CADASTRO"])

    col_new, col_edit = st.columns(2)

    # --- Coluna 1: Cadastrar Nova Obra ---
    with col_new:
        st.subheader("Cadastrar Nova Obra")
        
        next_id = 1
        if not df_info.empty and 'Obra_ID' in df_info.columns:
            try:
                # O ID é tratado como int no dataframe para encontrar o máximo
                max_id = df_info['Obra_ID'].astype(str).str.extract(r'(\d+)').astype(float).max()
                next_id = int(max_id) + 1 if pd.notna(max_id) else 1
            except:
                next_id = len(df_info) + 1
        
        st.info(f"O próximo ID da Obra será: **{next_id}**")

        with st.form("form_nova_obra"):
            nome = st.text_input("Nome da Obra", placeholder="Ex: Casa Alpha")
            valor = st.number_input("Valor Total Inicial (R$)", min_value=0.0, format="%.2f")
            data_inicio = st.date_input("Data de Início da Obra")
            
            submitted = st.form_submit_button("Cadastrar Obra")
            
            if submitted:
                if nome and valor > 0:
                    data_list = [next_id, nome, valor, data_inicio.strftime('%Y-%m-%d')]
                    insert_new_obra(data_list)
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
                
                data_inicio_actual = obra_data['Data_Inicio'].date() if pd.notna(obra_data['Data_Inicio']) and isinstance(obra_data['Data_Inicio'], datetime) else datetime.today().date()
                
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
                                                      value=data_inicio_actual,
                                                      key="edit_data_inicio")
                    
                    submitted_edit = st.form_submit_button("Salvar Edição da Obra")
                    
                    if submitted_edit:
                        if novo_nome and novo_valor >= 0:
                            update_obra_info(obra_id_para_editar, novo_nome, novo_valor, nova_data_inicio) 
                        else:
                            st.warning("Preencha o nome e um valor inicial válido.")


def show_registro_despesa(df_info, df_despesas):
    st.title(PAGINAS_REVERSO["REGISTRO_DESPESA"])

    if df_info.empty:
        st.warning("Cadastre pelo menos uma obra para registrar despesas.")
        return

    opcoes_obras = {f"{row['Nome_Obra']} ({row['Obra_ID']})": row['Obra_ID']
                    for index, row in df_info.iterrows()}

    obra_selecionada_str = st.selectbox("Selecione a Obra:", list(opcoes_obras.keys()), key="select_obra_registro")

    if obra_selecionada_str:
        obra_id = opcoes_obras[obra_selecionada_str]
        
        # CORREÇÃO: Filtro robusto para evitar KeyError (Obra_ID como STR)
        if not df_despesas.empty and 'Obra_ID' in df_despesas.columns:
            despesas_obra = df_despesas[df_despesas['Obra_ID'].astype(str) == str(obra_id)].copy()
        else:
            despesas_obra = pd.DataFrame()
        
        col1_reg, col2_edit = st.columns([1, 1.2]) 

        with col1_reg:
            st.subheader(f"Novo Gasto (Obra: {obra_id})")
            
            if despesas_obra.empty or 'Semana_Ref' not in despesas_obra.columns:
                proxima_semana = 1
            else:
                proxima_semana = despesas_obra['Semana_Ref'].max() + 1
                
            st.info(f"Próxima semana de referência a ser registrada: **Semana {proxima_semana}**")

            with st.form("form_despesa"):
                gasto = st.number_input("Gasto Total na Semana (R$)", min_value=0.0, format="%.2f", key="new_gasto")
                data_semana = st.date_input("Data de Referência da Semana", key="new_data")
                
                submitted = st.form_submit_button("Registrar Novo Gasto")
                
                if submitted:
                    if gasto >= 0:
                        data_list = [obra_id, proxima_semana, data_semana.strftime('%Y-%m-%d'), gasto]
                        insert_new_despesa(data_list)
                    else:
                        st.warning("O valor do gasto não pode ser negativo.")


        with col2_edit:
            st.subheader(f"Detalhes e Edição ({len(despesas_obra)} Semanas)")
            
            if despesas_obra.empty or 'Semana_Ref' not in despesas_obra.columns:
                st.info("Nenhum gasto registrado para esta obra.")
            else:
                despesas_display = despesas_obra.sort_values('Semana_Ref', ascending=False).copy()
                despesas_display['Gasto_Semana'] = despesas_display['Gasto_Semana'].apply(lambda x: formatar_moeda(x))
                despesas_display = despesas_display.rename(columns={'Semana_Ref': 'Semana', 'Data_Semana': 'Data Ref.', 'Gasto_Semana': 'Gasto'})
                
                semanas_opcoes = despesas_obra['Semana_Ref'].sort_values(ascending=False).tolist()
                
                # Se o DataFrame não estiver vazio, seleciona a última semana como padrão
                default_index = 0 if semanas_opcoes else None
                
                semana_selecionada = st.selectbox(
                    "Selecione a Semana para Detalhar/Editar:", 
                    semanas_opcoes,
                    index=default_index,
                    format_func=lambda x: f"Semana {x}",
                    key="select_semana_edicao"
                )
                
                if semana_selecionada:
                    linha_edicao = despesas_obra[despesas_obra['Semana_Ref'] == semana_selecionada].iloc[0]
                    # Garante que a data é tratada corretamente, seja str ou datetime
                    try:
                        data_atual = datetime.strptime(str(linha_edicao['Data_Semana']), '%Y-%m-%d').date()
                    except:
                         data_atual = datetime.today().date()
                         
                    gasto_atual = float(linha_edicao['Gasto_Semana'])

                    with st.expander(f"Editar Detalhes da Semana {semana_selecionada}", expanded=True):
                        with st.form(f"form_edicao_semana_{semana_selecionada}"):
                            
                            st.markdown(f"**Editando: Obra {obra_id} - Semana {semana_selecionada}**")
                            
                            novo_gasto = st.number_input("Novo Gasto Total (R$)", min_value=0.0, value=gasto_atual, format="%.2f", key="edit_gasto")
                            nova_data = st.date_input("Nova Data de Referência", value=data_atual, key="edit_data")
                            
                            submitted_edit = st.form_submit_button("Salvar Alterações")
                            
                            if submitted_edit:
                                if novo_gasto >= 0:
                                    update_despesa(obra_id, semana_selecionada, novo_gasto, nova_data) 
                                else:
                                    st.warning("O valor do gasto não pode ser negativo.")
                            
                        st.markdown("---")
                        st.markdown("**Histórico de Gastos:**")
                        st.dataframe(
                            despesas_display[['Semana', 'Data Ref.', 'Gasto']], 
                            use_container_width=True,
                            hide_index=True
                        )

@st.cache_data(ttl=3600) 
def load_users():
    """Carrega usuários e hashes de senha da aba 'Usuarios'."""
    gc = get_gspread_client()
    if not gc:
        return None
    
    try:
        planilha = gc.open(PLANILHA_NOME)
        aba_usuarios = planilha.worksheet("Usuarios")
        df_users = pd.DataFrame(aba_usuarios.get_all_records())

        if df_users.empty:
            st.error("A aba 'Usuarios' está vazia ou não foi encontrada. Autenticação desabilitada.")
            return None
        
        required_cols = ['name', 'username', 'password']
        if not all(col in df_users.columns for col in required_cols):
             st.error(f"A aba 'Usuarios' deve conter as colunas: {required_cols}")
             return None

        usernames_dict = {
            row['username']: {
                'email': f"{row['username']}@app.com",
                'name': row['name'],
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
    
    # CORREÇÃO: Garante que as colunas existem antes de tentar selecioná-las
    cols_to_display = ['Obra_ID', 'Nome_Obra', 'Valor_Total_Inicial', 'Gasto_Total_Acumulado', 'Sobrando_Financeiro', 'Data_Inicio']
    df_display = df_final[[col for col in cols_to_display if col in df_final.columns]].copy()

    if 'Valor_Total_Inicial' in df_display.columns: 
        df_display['Valor_Total_Inicial'] = df_display['Valor_Total_Inicial'].apply(formatar_moeda)
    if 'Gasto_Total_Acumulado' in df_display.columns: 
        df_display['Gasto_Total_Acumulado'] = df_display['Gasto_Total_Acumulado'].apply(formatar_moeda)
    if 'Sobrando_Financeiro' in df_display.columns:
        df_display['Sobrando_Financeiro'] = df_display['Sobrando_Financeiro'].apply(formatar_moeda)

    st.dataframe(df_display, use_container_width=True, hide_index=True)


def show_relatorio_obra(df_info, df_despesas):
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
        # Filtro robusto para evitar KeyError (Obra_ID como STR)
        if not df_despesas.empty and 'Obra_ID' in df_despesas.columns:
            despesas_obra = df_despesas[df_despesas['Obra_ID'].astype(str) == str(obra_id)].copy()
        else:
            despesas_obra = pd.DataFrame()
        
        st.markdown("---")
        st.subheader(f"Relatório de Acompanhamento: {info_obra['Nome_Obra']}")
        
        col_det1, col_det2 = st.columns(2)
        
        with col_det1:
            st.metric("ID da Obra", info_obra.get('Obra_ID', 'N/A'))
            # Acessa a data de forma segura
            data_inicio_str = info_obra.get('Data_Inicio').strftime('%d/%m/%Y') if pd.notna(info_obra.get('Data_Inicio')) and isinstance(info_obra.get('Data_Inicio'), datetime) else "N/A"
            st.metric("Data de Início", data_inicio_str)
            
        with col_det2:
            st.metric("Orçamento Inicial", formatar_moeda(info_obra.get('Valor_Total_Inicial', 0.0)))
            st.metric("Gasto Total Acumulado", formatar_moeda(info_obra.get('Gasto_Total_Acumulado', 0.0)))
        
        st.markdown(f"### **Saldo Restante:** {formatar_moeda(info_obra.get('Sobrando_Financeiro', 0.0))}")
        
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

# --- Lógica de Autenticação ---

def get_authenticator():
    """Configura e retorna o objeto Authenticator LENDO DO SHEETS."""
    
    usernames_dict = load_users() 
    
    if not usernames_dict:
        return None, None, None

    config_data = {
        'credentials': {
            'usernames': usernames_dict
        },
        'cookie': {
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
    
    # Lógica de Autenticação
    try:
        authenticator, usernames, names = get_authenticator()
    except KeyError as e:
         st.error(f"Erro de autenticação: Verifique se a seção 'credentials' no secrets.toml está completa (cookie_name, cookie_key, cookie_expiry_days). Detalhe: {e}")
         return
    
    if not authenticator:
        return
        
    name, authentication_status, username = authenticator.login('Login', 'main')

    if authentication_status:
        # Usuário autenticado
        authenticator.logout('Logout', 'sidebar')
        st.sidebar.write(f'Bem-vindo(a), {name}')
        
        if 'current_page' not in st.session_state:
            st.session_state.current_page = PAGINAS["1. Cadastrar Nova Obra"]
        
        st.markdown("---")
        
        setup_navigation()
        
        st.markdown("---")

        df_info, df_despesas = load_data()
        
        # O código só continua se df_info não estiver vazio OU se houver sucesso na leitura
        if df_info.empty and not df_despesas.empty: # Garante que as colunas da aba info foram lidas
             st.warning("Nenhuma informação de obra foi carregada. Por favor, verifique a aba 'Obras_Info'.")
             
        
        current_page = st.session_state.current_page

        if current_page == "CADASTRO":
            show_cadastro_obra(df_info) 
        elif current_page == "REGISTRO_DESPESA":
            show_registro_despesa(df_info, df_despesas) 
        elif current_page == "CONSULTA_STATUS":
            show_consulta_dados(df_info, df_despesas)
        elif current_page == "RELATORIO":
            show_relatorio_obra(df_info, df_despesas) 

    elif authentication_status == False:
        st.error('Nome de usuário/senha incorretos.')
    elif authentication_status == None:
        st.info('Por favor, insira suas credenciais.')

if __name__ == "__main__":
    main()
