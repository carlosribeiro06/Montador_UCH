# Montador UCH

Ferramenta em Python para geração automatizada de arquivos de entrada do **Unit Commitment Hidráulico (UCH)** a partir de dados estruturados em planilhas Excel.

## 🎯 Objetivo

O **Montador_UCH** tem como objetivo automatizar a preparação dos dados necessários para a representação de usinas hidrelétricas no UCH.

A partir de uma planilha contendo as características das usinas, o programa realiza:

* leitura dos dados de entrada;
* identificação das usinas que possuem UCH;
* cadastro das usinas, conjuntos e unidades;
* determinação da forma de agregação da usina;
* cálculo dos limites de geração;
* geração automática do arquivo de entrada `uch.dat`.

## ⚙️ Funcionamento

O fluxo de processamento é:

```text
Planilha Excel
      │
      ▼
Leitura dos dados
      │
      ▼
Cadastro das usinas
      │
      ├── Usina
      │    └── Conjuntos
      │         └── Unidades
      │
      ▼
Definição da agregação
      │
      ▼
Cálculo de GMin / GMax
      │
      ▼
Geração do uch.dat
```

## 📥 Entrada

O programa utiliza uma planilha Excel contendo as informações das usinas e suas respectivas unidades e conjuntos.

Arquivo de entrada:

```text
UCH.xlsx
```

A planilha deve conter as informações necessárias para identificação das usinas, número de conjuntos, número de máquinas, potência máxima e potência de acionamento.

## 📤 Saída

Ao executar o programa, é gerado:

```text
uch.dat
```

O arquivo contém os registros necessários para a configuração do UCH, incluindo, entre outros:

```text
UCH-OPCAO-PADRAO
UCH-PADRAO-USINA
UCH-GERACAO-MINIMA-MAXIMA-UNIDADE
UCH-GERACAO-MINIMA-MAXIMA-CONJUNTO
UCH-GERACAO-MINIMA-MAXIMA-USINA
```

## 🧩 Agregação

O programa permite representar uma usina utilizando diferentes níveis de agregação:

| Agregação  | Descrição                                       |
| ---------- | ----------------------------------------------- |
| `Unidade`  | Representação individual das unidades geradoras |
| `Conjunto` | Representação por conjunto de unidades          |
| `Usina`    | Representação agregada da usina                 |

A forma de agregação é definida na planilha de entrada.

## 🚀 Como executar

### 1. Clone o repositório

```bash
git clone git@github.com:carlosribeiro06/Montador_UCH.git
cd Montador_UCH
```

### 2. Crie o ambiente virtual

```bash
python3 -m venv .venv
```

### 3. Ative o ambiente virtual

No Linux/WSL:

```bash
source .venv/bin/activate
```

### 4. Instale as dependências

```bash
pip install -r requirements.txt
```

### 5. Execute

```bash
python main.py
```

O arquivo `uch.dat` será gerado no diretório do projeto.

## 📁 Estrutura

```text
Montador_UCH/
│
├── .gitignore
├── README.md
├── LICENSE
├── UCH.xlsx
├── main.py
│
└── ...
```

## 🛠️ Tecnologias

* Python
* Pandas
* NumPy
* OpenPyXL

## 📌 Observações

Os arquivos gerados pelo programa não precisam ser versionados no Git. O ambiente virtual `.venv` também é ignorado pelo `.gitignore`.

---

**Montador_UCH**
Ferramenta para automatização da montagem de dados de entrada do Unit Commitment Hidráulico.
