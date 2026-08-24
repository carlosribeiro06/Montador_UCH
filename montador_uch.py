from pathlib import Path
import pandas as pd
import numpy as np

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


def escreve_uch(lista_hidreletricas):
    with open("uch.dat", "w") as arquivo:
        arquivo.write("============================================================\n"
            "ONS - Operador Nacional do Sistema Elétrico\n"
            "Diretoria de Planejamento\n"
            "Gerência Executiva de Ferramentas Eletroenergéticas\n"
            "Gerência de Ferramentas Energéticas\n"
            "============================================================\n")
        arquivo.write("UCH-OPCAO-PADRAO;1\n")
        arquivo.write("#------------------------------------------------------------------------------------------------------------------------\n")
        arquivo.write("\n")
        for hidreletrica in lista_hidreletricas:
            codigo = hidreletrica.codigo
            hidreletrica_nome = hidreletrica.nome 
            arquivo.write("#------------------------------------------------------------------------------------------------------------------------\n")
            arquivo.write(f"#USINA {codigo}: {hidreletrica_nome.strip()}\n")
            arquivo.write("#------------------------------------------------------------------------------------------------------------------------\n")
            if hidreletrica.agregacao == "Unidade":
                agregacao = 1
            elif hidreletrica.agregacao == "Conjunto":
                agregacao = 2
            elif hidreletrica.agregacao == "Usina":
                agregacao = 3
            arquivo.write(f"UCH-PADRAO-USINA;{codigo};1;{agregacao}\n")
            if agregacao == 1:
                for hidreletrica_conjunto in hidreletrica.conjuntos:
                    nconjunto = hidreletrica_conjunto.nconjunto
                    if hidreletrica.agregacao == "Unidade":
                        for unidade in hidreletrica_conjunto.unidades:
                            nunidade = unidade.nunidade
                            arquivo.write(f"UCH-GERACAO-MINIMA-MAXIMA-UNIDADE;{codigo};{nconjunto+1};{nunidade+1};{unidade.pmin};{hidreletrica_conjunto.pmax/len(hidreletrica_conjunto.unidades)}\n")
            elif agregacao == 2:
                for hidreletrica_conjunto in hidreletrica.conjuntos:
                    nconjunto = hidreletrica_conjunto.nconjunto
                    arquivo.write(f"UCH-GERACAO-MINIMA-MAXIMA-CONJUNTO;{codigo};{nconjunto+1};{hidreletrica_conjunto.unidades[0].pmin};{hidreletrica_conjunto.pmax}\n")
            elif agregacao == 3:
                pmin_usina = min(unidade.pmin for conjunto in hidreletrica.conjuntos for unidade in conjunto.unidades)
                pmax_usina = sum(conjunto.pmax for conjunto in hidreletrica.conjuntos)
                arquivo.write(f"UCH-GERACAO-MINIMA-MAXIMA-USINA;{codigo};{pmin_usina};{pmax_usina}\n")
            arquivo.write("\n")

def transforma_dat_para_csv():
    Path("uch.dat").rename("uch.csv")

hidros = cadastra_hidreletrica(df_hidreletricas)
escreve_uch(hidros)
transforma_dat_para_csv()
