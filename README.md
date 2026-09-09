# montador-uch

## What it is

`montador-uch` builds the DESSEM hydraulic unit commitment input file `uch.csv` from a base
workbook and writes it into a DESSEM deck directory. It reads the plant / unit-group / generating
-unit registry from the `UCH` sheet of `UCH.xlsx`, adjusts that unit structure to the deck's
cadastral changes (the `entdados.dat` `AC` records), derives the minimum and maximum generation
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

`UCH.xlsx` is versioned in this repository and ships with a clone. The `*.xlsx` rule in
`.gitignore` was added after the workbook was already tracked, so it only hides *new* workbooks --
edits to `UCH.xlsx` itself are still picked up by `git add`. Point `spreadsheet_path` in
`settings.json` at a different workbook, or pass `--spreadsheet`, to use another one.

## Configuration

By default the tool reads `settings.json` **from the current working directory** (the repository
ships one at its root); `--settings PATH` points it elsewhere. If the file is absent the run does
not fail -- it logs a warning and continues on the built-in defaults below, resolved against the
current working directory. Pass `--settings` explicitly when launching from another directory, on
a study server or from a scheduled job, so a configured path is never silently replaced by a
default.

Every key is optional; omitted keys fall back to the defaults below. An unknown key, a value of
the wrong type, or a value outside the usable range aborts the run with a message naming the key
and the file. Relative `spreadsheet_path` and `log_dir` values resolve against the directory
holding the settings file.

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
| `log_level`                  | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`    | `INFO`                      |
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

The run prints one summary line to stdout; everything else goes to the log. `N plants omitted
(...)` only appears when a cadastral change left at least one plant without generating units --
its groups all zeroed, or `AC NUMCON 0` leaving it no groups at all (see "Deck cadastral changes
(AC records)" below):

```text
uch.csv: /path/to/deck/uch.csv | 150 plants, 201 groups, 725 units | horizon end 2/23/1 | 36 AC changes applied | 2 plants omitted (87, 112) | dessem.arq updated | 0.22 s
```

Exit codes:

| Code | Meaning                                                                                         |
| ---- | ----------------------------------------------------------------------------------------------- |
| `0`  | `uch.csv` written and `dessem.arq` checked                                                      |
| `1`  | bad settings, malformed/infeasible spreadsheet row or AC change, missing input, bad study stage |
| `2`  | command-line usage error                                                                        |

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

### Minimum must not exceed maximum

A `Potencia_de_acionamento` greater than the maximum it is paired with -- the group total for a
group register, or `Potencia_maxima / Nmaqs` for a unit register -- would be written as an
infeasible `Gmin > Gmax` register. The reader rejects it instead:

```text
SpreadsheetError: Row 129, plant 195: Unit 1 minimum power 40.5 exceeds its maximum 39.3;
the register would be infeasible
```

The workbook must be corrected before the run can produce `uch.csv`; the tool deliberately does
not clamp or drop the offending plant, because choosing a replacement value is a physical
judgement, not a formatting one.

The same guard applies after a deck cadastral change: a `POTEFE` cut that lowers a group's
per-unit maximum below its start-up power raises the same `ValueError`, wrapped as a
`CadastreChangeError` naming the row and plant (see "Deck cadastral changes (AC records)" below).

## Deck cadastral changes (AC records)

The workbook is the plant registry of record for the run; the deck's `entdados.dat` can carry
`AC` records that change the unit structure for the study, and those changes are applied on top of
the workbook, in file order, one plant at a time, before the Gmin/Gmax registers are built. Three
mnemonics are read (DESSEM User Manual v22.4.0, section III.5.4.7):

| Mnemonic | Meaning                                        | Fields                  |
| -------- | ---------------------------------------------- | ----------------------- |
| `NUMCON` | Number of unit groups (conjuntos) of the plant | group count             |
| `NUMMAQ` | Unit count of one group                        | group index, unit count |
| `POTEFE` | Effective power per unit, in MW, of one group  | group index, power (MW) |

Every other `AC` mnemonic, and every other register type in `entdados.dat`, is ignored.

Changes are applied sequentially in file order. A `NUMMAQ`/`POTEFE` group index is checked
against the plant's *current* number of groups at the point it is applied, not its original
`N_conjuntos` -- so `AC NUMCON` must precede any `NUMMAQ`/`POTEFE` that relies on the group it
adds; the reverse order raises `CadastreChangeError`. For plant 287 below, whose workbook
`N_conjuntos` is 2, applying its `NUMMAQ 3` before its `NUMCON 3` would raise:

```text
Row 161, plant 287 (STO ANTONIO): AC NUMMAQ group 3 exceeds the plant's current 2 group(s)
(DESSEM manual III.5.4.7: the group index must be at most the plant's number of groups)
```

A group's total maximum power is recomputed as `units × per-unit power` whenever `NUMMAQ` or
`POTEFE` touched that group (even to reaffirm its current values); otherwise the workbook's
`Potencia_maxima` total is kept verbatim. This matters because the workbook total is the cadastral
power rounded to one decimal, not always the exact product of its own `Nmaqs` and per-unit power.

The start-up power (Gmin) of a group always comes from the workbook column at that group index
(`Potencia_de_acionamento` at the 0-based position `group index - 1`), whatever `Nmaqs` says there
-- including a group `AC NUMCON` newly activates. There is no inheritance from another group and
no fallback to zero: a blank cell aborts the run naming it. Plant 287's group 3 happens to have
one filled in already (see the worked example below), so if it were blank instead the run would
abort with:

```text
Row 161, plant 287 (STO ANTONIO): group 3 has no start-up power; fill workbook column
'Potencia_de_acionamento.2'
```

A group whose per-unit power cannot be derived also aborts the run, with a message that
distinguishes two causes: the workbook's `Potencia_maxima` cell for that group index being blank,
versus the workbook giving that group no units so its own total yields no per-unit power to fall
back on. Had plant 287's `AC POTEFE 3` been missing and its `Potencia_maxima.2` cell blank too,
the run would abort with:

```text
Row 161, plant 287 (STO ANTONIO): group 3 has no per-unit power: workbook column
'Potencia_maxima.2' is blank, and no AC POTEFE sets one
```

A plant whose changes leave every one of its unit groups at zero units is omitted from `uch.csv`
with a `WARNING` and listed in the CLI summary line, rather than modelled with an invented
zero-unit group:

```text
Row 81, plant 112 (JACUI): all unit groups have zero units after AC changes; omitted from the
output
```

An `AC NUMCON` of 0 declares the plant with no unit groups at all, which omits it the same way but
under its own reason -- the groups there keep the machines the workbook gives them, so reporting
them as zeroed would be false. No plant in the reference deck takes this path (its eight `NUMCON`
records are all at least 1); had plant 112's been `AC 112 NUMCON 0` instead, the warning would
read:

```text
Row 81, plant 112 (JACUI): AC NUMCON set the plant to zero unit groups; omitted from the output
```

A change whose plant code matches no workbook row is ignored (logged at `DEBUG`), never raised --
a deck without a plant the workbook does not model produces the same `uch.csv` it would without
that change.

`entdados.dat` is read as `latin-1` text and cross-checked against `idessem`'s own parse: `idessem`
can silently drop an `AC` line that fails to match any registered mnemonic pattern (confirmed on
the reference deck's `AC  118  DESVIO ...` lines, an unrelated mnemonic), falling back to an
untyped `DefaultRegister` instead of raising. `read_cadastre_changes` counts the raw
`NUMCON`/`NUMMAQ`/`POTEFE` lines independently and raises if the two counts disagree, so a change
`idessem` fails to surface is never silently lost.

**`hidr.dat` is not read.** This is a deliberate decision, not an oversight: the workbook's
`Potencia_maxima` totals -- themselves the cadastral power rounded to one decimal -- are trusted
as given, and a group `AC` creates or activates must already carry a start-up power on the
workbook, because there is no cadastral source left to fall back on.

### Worked example

The reference deck carries, for plant 287 (`STO ANTONIO`, `Tipo` `Conjunto`, originally 2 groups
of 24 and 26 units):

```text
AC  287  NUMCON        3
AC  287  NUMMAQ        1   24
AC  287  POTEFE        1      73.3
AC  287  NUMMAQ        2   20
AC  287  POTEFE        2      69.6
AC  287  NUMMAQ        3    6
AC  287  POTEFE        3      69.6
```

`NUMCON 3` opens group 3, a position the workbook already carries a start-up power for
(`Potencia_de_acionamento.2` = 21.0 MW) despite `Nmaqs.2` being 0. `NUMMAQ`/`POTEFE` then reaffirm
group 1 at 24 units, and split the original 26-unit group 2 into a 20-unit group 2 and the newly
opened 6-unit group 3, both at 69.6 MW per unit. The resulting `uch.csv` lines for plant 287 are:

```text
UCH-OPCAO-PADRAO-USINA;287;1;2
UCH-GERACAO-MINIMA-MAXIMA-CONJUNTO;287;1;21.000;1759.200
UCH-GERACAO-MINIMA-MAXIMA-CONJUNTO;287;2;11.000;1392.000
UCH-GERACAO-MINIMA-MAXIMA-CONJUNTO;287;3;21.000;417.600
```

Plant 112 (`JACUI`, one group of 6 units) instead carries `AC 112 NUMMAQ 1 0`: its only group
drops to zero units, so the plant is omitted from `uch.csv` with the `WARNING` shown above and
reported in the CLI summary line, rather than a plant with no groups.

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

The plant set and the group totals in step 3 are the deck's, not the raw workbook's: a plant
omitted by the cadastral overlay contributes no lines, and a group `NUMMAQ`/`POTEFE` touched
carries its recomputed total rather than the workbook's `Potencia_maxima`. Spreadsheet order
itself is unaffected by the overlay.

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
  cadastre_changes.py   NUMCON/NUMMAQ/POTEFE AC record reader, CadastreChangeError
  cadastre_overlay.py   applies AC changes on the workbook records, before HydroPlant is built
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

Each applied cadastral change also logs one `INFO` line naming the plant, the group and the
before/after value (`NUMCON %d -> %d`, `group %d units %d -> %d` or `group %d unit power %s ->
%s MW`), and a plant the overlay omits logs a `WARNING` naming the row and the plant before it is
dropped from the output.

## Reference

DESSEM User Manual, version 22.4.0:

- Section III.32 ("Dados de Unit Commitment Hidraulico"), which defines the register layout, the
  field order and the aggregation codes used here.
- Section III.5.4.7 (`AC` cadastral changes), which defines the `NUMCON`, `NUMMAQ` and `POTEFE`
  mnemonics applied by the overlay above.
