"""Immutable original PDFs: reuse equal bytes and retain every different version."""
import os
from pathlib import Path
import tempfile
from filelock import FileLock
import workflow as w


def save_pdf(destination, raw):
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    sha=w.digest(raw)
    with FileLock(str(destination.parent/'.original-pdf.lock'),timeout=20):
        target=destination
        if target.exists():
            if w.digest(target.read_bytes())==sha:return target
            target=destination.with_name(destination.stem+'_'+sha[:16]+destination.suffix)
        if target.exists():
            if w.digest(target.read_bytes())==sha:return target
            raise ValueError('已有不同原稿占用此版本路径，未覆盖。')
        handle,name=tempfile.mkstemp(prefix='.download-',suffix='.partial',dir=destination.parent)
        temporary=Path(name)
        try:
            with os.fdopen(handle,'wb') as file:file.write(raw);file.flush();os.fsync(file.fileno())
            # Creating a hard link is atomic and refuses an existing destination.
            os.link(temporary,target)
        finally:temporary.unlink(missing_ok=True)  # Only our newly created partial copy.
        return target
