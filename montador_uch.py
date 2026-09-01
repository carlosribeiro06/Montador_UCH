from idessem.dessem import DessemArq
from idessem.dessem import Uch
from idessem.dessem import Entdados
from idessem.dessem.modelos.dessemarq import RegistroUch
from idessem.dessem.modelos.uch import UchOpcaoPadraoUsina, UchOpcaoPadrao, UchPadraoData, UchGminGmaxUnidade, UchGminGmaxConjunto, UchGminGmaxUsina
from idessem.dessem.modelos.entdados import ACNUMCON, ACNUMMAQ, ACPOTEFE, TM
import pandas as pd

caminho_caso = "DS_ONS_092026_RV0D02"
df_hidreletricas = pd.read_excel('UCH.xlsx', sheet_name='UCH', header=1)

class hidreletrica:
    def __init__(self, nome, codigo, conjuntos, agregacao):
        self.nome = nome
        self.codigo = codigo
        self.conjuntos = conjuntos
        self.agregacao = agregacao

class uch_unidade:
    def __init__(self, nome, codigo, nunidade, pmin):
        self.nome = nome
        self.codigo = codigo
        self.nunidade = nunidade
        self.pmin = pmin

class uch_conjunto:
    def __init__(self, nome, codigo, nconjunto, unidades, pmax):
        self.nome = nome
        self.codigo = codigo
        self.nconjunto = nconjunto
        self.unidades = unidades
        self.pmax = pmax


def cadastra_hidreletrica(df):
    lista_hidreletricas = []
    for _, row in df.iterrows():
        tipo = row['Tipo']
        if tipo == "Sem UCH":
            continue
        else:
            lista_conjuntos = []

            nome = row['Nome']
            codigo = row['Código']
            N_conjuntos = row['N_conjuntos']
            for conj in range(int(N_conjuntos)):
                lista_unidades = []
                if conj == 0:
                    N_maquinas = row['Nmaqs']
                    pmax = row['Potencia_maxima']
                else:
                    N_maquinas = row[f'Nmaqs.{conj}']
                    pmax = row[f'Potencia_maxima.{conj}']
                if N_maquinas > 0:
                    for maq in range(int(N_maquinas)):
                        if conj == 0:
                            pmin = row['Potencia_de_acionamento']
                        else:
                            pmin = row[f'Potencia_de_acionamento.{conj}']
                        unidade = uch_unidade(
                            nome,
                            codigo,
                            maq,
                            pmin
                        )          
                        lista_unidades.append(unidade)

                    conjunto = uch_conjunto(
                        nome,
                        codigo,
                        conj,
                        lista_unidades,
                        pmax
                    )
                    lista_conjuntos.append(conjunto)

            hidreletrica_obj = hidreletrica(
                nome,
                codigo,
                lista_conjuntos,
                tipo
            )
            lista_hidreletricas.append(hidreletrica_obj)

    return lista_hidreletricas


def escreve_uch_dessemarq(caminho_caso):

    dessemarq = DessemArq.read(f"{caminho_caso}/dessem.arq")
    registro_uch = RegistroUch()

    if dessemarq.uch is None:
        registro_uch.descricao = "UNIT COMMITMENT HIDRAULICO"
        registro_uch.valor = "uch.csv"
        dessemarq.data.preppend(registro_uch)
        dessemarq.write(f"{caminho_caso}/dessem.arq")


def escreve_uch(caminho_caso, lista_hidreletricas):
    uch = Uch()
    entdados = Entdados.read(f"{caminho_caso}/entdados.dat")
    df_tm = entdados.tm(df=True)

    registro_opcao_padrao = UchOpcaoPadrao()
    registro_opcao_padrao.considera_uch = 1
    uch.data.append(registro_opcao_padrao)

    registro_uch_padrao_data = UchPadraoData()
    df_tm_filtrado = df_tm[df_tm["duracao"] == 0.5]
    registro_uch_padrao_data.dia_final = df_tm_filtrado.iloc[-1]["dia_inicial"]
    registro_uch_padrao_data.hora_final = df_tm_filtrado.iloc[-1]["hora_inicial"]
    registro_uch_padrao_data.meia_hora_final = df_tm_filtrado.iloc[-1]["meia_hora_inicial"]
    uch.data.append(registro_uch_padrao_data)

    for hidreletrica in lista_hidreletricas:
        registro_opcao_padrao_usina = UchOpcaoPadraoUsina()
        registro_gmin_gmax_unidade = UchGminGmaxUnidade()
        registro_gmin_gmax_conjunto = UchGminGmaxConjunto()
        registro_gmin_gmax_usina = UchGminGmaxUsina()
        
        codigo = hidreletrica.codigo
        if hidreletrica.agregacao == "Unidade":
            tipo_agregacao = 1
        elif hidreletrica.agregacao == "Conjunto":
            tipo_agregacao = 2
        elif hidreletrica.agregacao == "Usina":
            tipo_agregacao = 3
        registro_opcao_padrao_usina.codigo_usina = codigo
        registro_opcao_padrao_usina.considera_uch_usina = 1
        registro_opcao_padrao_usina.tipo_agregacao = tipo_agregacao
        uch.data.append(registro_opcao_padrao_usina)
        if tipo_agregacao == 1:
            for hidreletrica_conjunto in hidreletrica.conjuntos:
                nconjunto = hidreletrica_conjunto.nconjunto
                if hidreletrica.agregacao == "Unidade":
                    for unidade in hidreletrica_conjunto.unidades:
                        nunidade = unidade.nunidade
                        registro_gmin_gmax_unidade.codigo_usina = codigo
                        registro_gmin_gmax_unidade.codigo_conjunto = nconjunto+1
                        registro_gmin_gmax_unidade.condigo_unidade = nunidade+1
                        registro_gmin_gmax_unidade.geracao_minima_unidade = unidade.pmin
                        registro_gmin_gmax_unidade.geracao_maxima_unidade = unidade.pmax/len(hidreletrica_conjunto.unidades)
                        uch.data.append(registro_gmin_gmax_unidade)
        elif tipo_agregacao == 2:
            for hidreletrica_conjunto in hidreletrica.conjuntos:
                nconjunto = hidreletrica_conjunto.nconjunto
                registro_gmin_gmax_conjunto.codigo_usina = codigo
                registro_gmin_gmax_conjunto.codigo_conjunto = nconjunto+1
                registro_gmin_gmax_conjunto.geracao_minima_conjunto = hidreletrica_conjunto.unidades[0].pmin
                registro_gmin_gmax_conjunto.geracao_maxima_conjunto = hidreletrica_conjunto.pmax
                uch.data.append(registro_gmin_gmax_conjunto)
        elif tipo_agregacao == 3:
            pmin_usina = min(unidade.pmin for conjunto in hidreletrica.conjuntos for unidade in conjunto.unidades)
            pmax_usina = 0
            for conjunto in hidreletrica.conjuntos:
                for unidade in conjunto.unidades:
                    pmax_usina += conjunto.pmax
            registro_gmin_gmax_usina.codigo_usina = codigo
            registro_gmin_gmax_usina.geracao_minima_usina = pmin_usina
            registro_gmin_gmax_usina.geracao_maxima_usina = pmax_usina
            uch.data.append(registro_gmin_gmax_usina)

    uch.write(f"{caminho_caso}/uch.csv")


lista_hidreletricas = cadastra_hidreletrica(df_hidreletricas)
escreve_uch_dessemarq(caminho_caso)
escreve_uch(caminho_caso, lista_hidreletricas)