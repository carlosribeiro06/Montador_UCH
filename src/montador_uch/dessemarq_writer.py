"""Registration of `uch.csv` in the deck index file `dessem.arq`.

The `UCH` record tells DESSEM which file carries the hydraulic unit commitment data. Registration
is idempotent: the record is prepended when absent and the file is left byte-for-byte unchanged
when it is already there.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import cast

from idessem.dessem import DessemArq
from idessem.dessem.modelos.dessemarq import RegistroUch

logger = logging.getLogger(__name__)


def register_uch_file(dessemarq_path: Path, uch_filename: str, description: str) -> bool:
    """Ensure `dessem.arq` at `dessemarq_path` declares `uch_filename` as its `UCH` file.

    Returns `True` when the record was added (and the file rewritten), `False` when a `UCH`
    record was already present, in which case the file is not touched.
    """
    if not dessemarq_path.is_file():
        raise FileNotFoundError(f"DESSEM index file not found: {dessemarq_path}")

    # RegisterFile.read is annotated as returning the base class, which hides `uch`.
    dessemarq = cast(DessemArq, DessemArq.read(str(dessemarq_path)))

    existing = dessemarq.uch
    if existing is not None:
        logger.info(
            "%s already declares a UCH file (%r); leaving it unchanged",
            dessemarq_path,
            existing.valor,
        )
        return False

    record = RegistroUch()
    record.descricao = description
    record.valor = uch_filename
    dessemarq.data.preppend(record)
    dessemarq.write(str(dessemarq_path))

    logger.info("Registered UCH file %r in %s", uch_filename, dessemarq_path)
    return True
