# montador-uch

## What it is

`montador-uch` builds the DESSEM hydraulic unit commitment input file `uch.csv` from a base
workbook and writes it into a DESSEM deck directory. It reads the plant / unit-group / generating
-unit registry from the `UCH` sheet of `UCH.xlsx`, derives the minimum and maximum generation
limits for the aggregation level of each plant, writes `uch.csv` into the deck (overwriting any
existing file) and registers that file in the deck's `dessem.arq` index.

The deck directory is the only positional argument. Everything else -- the workbook path, the
file names, the log configuration -- comes from `settings.json`, so the same code runs unchanged
on a workstation and on a study server.

## Requirements

- Python 3.11 or newer.
- [`uv`](https://docs.astral.sh/uv/) for dependency resolution and running.
- The `idessem` fork `github.com/carlosribeiro06/idessem`, pinned to commit `da2118e`.

The fork is not optional. PyPI `idessem==1.3.0` does not expose the UCH registers this tool
writes: `UchGminGmaxConjunto`, `UchGminGmaxUsina`, `UchPadraoData` and `UchOpcaoPadraoUsina` are
absent from its `idessem.dessem.modelos.uch`, which offers `UchOpcaoUsina` and
`UchOpcaoPadraoData` instead. The dependency is therefore declared by commit hash in
`pyproject.toml` and locked in `uv.lock`.

`UCH.xlsx` is gitignored and must be supplied locally. Point `spreadsheet_path` in
`settings.json` at it, or pass `--spreadsheet`.

## Configuration

`settings.json` sits next to the code by default. Every key is optional; omitted keys fall back
to the defaults below. An unknown key, or a value of the wrong type, aborts the run with a
message naming the key and the file. Relative `spreadsheet_path` and `log_dir` values resolve
against the directory holding the settings file.

| Key                          | Meaning                                              | Default                     |
| ---------------------------- | ---------------------------------------------------- | --------------------------- |
| `spreadsheet_path`           | Base workbook to read                                | `UCH.xlsx`                  |
| `sheet_name`                 | Worksheet holding the registry                       | `UCH`                       |
| `header_row`                 | 0-based row carrying the column names                | `1`                         |
| `uch_filename`               | Output file name inside the deck                     | `uch.csv`                   |
| `dessemarq_filename`         | Deck index file to register the output in            | `dessem.arq`                |
| `entdados_filename`          | Deck file supplying the study stages (`TM` records)  | `entdados.dat`              |
| `dessemarq_uch_description`  | Description written in the `dessem.arq` `UCH` record | `UNIT COMMITMENT HIDRAULICO`|
| `half_hour_stage_duration_h` | Stage duration marking the half-hour horizon, in h   | `0.5`                       |
| `log_level`                  | Console and file log level                           | `INFO`                      |
| `log_dir`                    | Directory for the log file                           | `logs`                      |
| `log_filename`               | Log file name                                        | `montador_uch.log`          |
| `log_max_bytes`              | Size at which the log file rotates                   | `1000000`                   |
| `log_backup_count`           | Rotated log files kept                               | `5`                         |

## How to run

```bash
uv sync --all-groups
uv run montador-uch /path/to/DS_ONS_092026_RV0D02
```

Flags:

```text
--spreadsheet PATH   base workbook, overriding spreadsheet_path
--settings PATH      settings file (default: settings.json in the current directory)
--log-level LEVEL    DEBUG, INFO, WARNING, ERROR or CRITICAL
--version            print the version and exit
```

The run prints one summary line to stdout; everything else goes to the log:

```text
uch.csv: /path/to/deck/uch.csv | 156 plants, 207 groups, 750 units | horizon end 2/23/1 | dessem.arq updated | 0.22 s
```

Exit codes:

| Code | Meaning                                                                            |
| ---- | ---------------------------------------------------------------------------------- |
| `0`  | `uch.csv` written and `dessem.arq` checked                                          |
| `1`  | bad settings, malformed spreadsheet row, missing input file, or invalid study stage |
| `2`  | command-line usage error                                                           |

Running the tool twice on the same deck is safe: `uch.csv` is rewritten from scratch and the
`dessem.arq` record is added only if it is missing.

## Spreadsheet format

Sheet `UCH` has two header rows; the column names live on row index 1 (`header_row`), so the
data starts on spreadsheet row 3.

Per-plant columns:

| Column        | Meaning                                                        |
| ------------- | -------------------------------------------------------------- |
| `Código`      | DESSEM plant code, unique among the plants modelled with UCH    |
| `Nome`        | Plant name, used in logs and error messages only                |
| `Tipo`        | Aggregation label, or `Sem UCH` to exclude the plant            |
| `N_conjuntos` | Number of unit-group column blocks to read, between 1 and 5     |

Each unit group repeats three columns, suffixed `""`, `.1`, `.2`, `.3`, `.4` by pandas:

| Column                    | Meaning                                            |
| ------------------------- | -------------------------------------------------- |
| `Nmaqs`                   | Units in the group; `0` drops the group            |
| `Potencia_de_acionamento` | Per-unit minimum generation, in MW                 |
| `Potencia_maxima`         | Group total maximum generation, in MW              |

A unit's maximum is `Potencia_maxima / Nmaqs`; every unit of a group shares the group's
`Potencia_de_acionamento` as its minimum.

`Pmin_usina`, `Pmin_conjunto*` and `Regularização` are read by nobody: they are effectively empty
in the current workbook and are ignored, as the original script did.

Rows whose `Tipo` is `Sem UCH` are skipped without validation. Any other malformed row aborts the
run with the plant code and the spreadsheet row in the message.

## Aggregation levels

`Tipo` selects the granularity of the generation limits and the DESSEM aggregation code written
in field 4 of `UCH-OPCAO-PADRAO-USINA`.

| `Tipo`     | Code | Registers written             | Gmin                | Gmax                  |
| ---------- | ---- | ----------------------------- | ------------------- | --------------------- |
| `Unidade`  | `1`  | one per generating unit       | unit minimum        | group total / `Nmaqs` |
| `Conjunto` | `2`  | one per unit group            | group unit minimum  | group total           |
| `Usina`    | `3`  | one per plant                 | smallest unit min   | sum of group totals   |
| `Sem UCH`  | --   | none; the plant is skipped    | --                  | --                    |

## Output

`uch.csv` is a `;`-delimited register file written in this order:

1. `UCH-OPCAO-PADRAO;1` -- enable UCH for the study.
2. `UCH-PADRAO-DATA;<day>;<hour>;<half hour>` -- end of the UCH horizon, taken from the last `TM`
   record of `entdados.dat` whose duration equals `half_hour_stage_duration_h`.
3. Per plant, in spreadsheet order, `UCH-OPCAO-PADRAO-USINA;<code>;1;<level>` followed by its
   `UCH-GERACAO-MINIMA-MAXIMA-UNIDADE`, `-CONJUNTO` or `-USINA` registers.

The file is always rewritten in full, so a stale `uch.csv` in the deck is replaced rather than
merged.

In `dessem.arq`, a `UCH` record naming `uch_filename` is prepended when the file declares none.
If a `UCH` record is already present its value is left alone and the index file is not rewritten.

## Structure

```text
src/montador_uch/
  cli.py                argument parsing, logging setup, exit codes
  pipeline.py           one run end to end, returning a RunSummary
  settings.py           Settings dataclass, load_settings, SettingsError
  logging_setup.py      console and rotating-file handlers
  spreadsheet.py        UCH sheet reader, SpreadsheetError
  model.py              AggregationLevel, GeneratingUnit, UnitGroup, HydroPlant
  uch_writer.py         StudyEndStage, study_end_stage, build_uch, write_uch
  dessemarq_writer.py   register_uch_file
tests/                  pytest suite; helpers.py builds workbooks at run time
```

Tests in `test_*_real.py` exercise the repository workbook and a reference deck; they skip when
those are absent. Set `MONTADOR_UCH_SAMPLE_DECK` to point them at a deck elsewhere.

```bash
uv run pytest --cov=montador_uch --cov-report=term-missing
uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

## Logging

Every run logs to two places at `log_level`:

- the console, through `rich` when it is installed and a plain timestamped formatter otherwise;
- `log_dir/log_filename` (by default `logs/montador_uch.log`), rotating at `log_max_bytes` and
  keeping `log_backup_count` previous files.

The log records the workbook and deck paths, the rows read, the plants skipped as `Sem UCH`, the
plant/group/unit counts, the UCH horizon, the register count written, whether `dessem.arq` was
changed, and the elapsed time -- enough to reconstruct what an official run did.

## Reference

DESSEM User Manual, version 22.4.0, section III.32 ("Dados de Unit Commitment Hidraulico"),
which defines the register layout, the field order and the aggregation codes used here.
