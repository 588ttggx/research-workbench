"""Bounded-memory backup container using cryptography GCM and native DPAPI.

Keys are random per archive and protected by Windows; no password is invented.
The complete header is authenticated. Decrypted ZIPs are exposed only after GCM
finalization succeeds. Legacy whole-blob DPAPI backups remain readable.
See https://cryptography.io/en/latest/hazmat/primitives/symmetric-encryption/
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import struct
import tempfile
import win32crypt
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes

MAGIC=b'RESEARCH-BACKUP\x04\r\n'
CHUNK=1024*1024


def file_digest(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(CHUNK),b''):digest.update(block)
    return digest.hexdigest()


def protect(source,target):
    """Publish one new authenticated archive, preserving any existing backup."""
    target=Path(target)
    if target.exists():raise ValueError('同名备份已存在，未覆盖旧备份')
    key=os.urandom(32);nonce=os.urandom(12)
    wrapped=win32crypt.CryptProtectData(key,'Research Workspace Backup Key',None,None,None,4)
    header=MAGIC+struct.pack('>I',len(wrapped))+nonce+wrapped
    encryptor=Cipher(algorithms.AES256(key),modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header)
    created=False
    try:
        with Path(source).open('rb') as raw,target.open('xb') as encrypted:
            created=True;encrypted.write(header)
            for block in iter(lambda:raw.read(CHUNK),b''):encrypted.write(encryptor.update(block))
            encrypted.write(encryptor.finalize());encrypted.write(encryptor.tag)
            encrypted.flush();os.fsync(encrypted.fileno())
    except Exception:
        if created:target.unlink(missing_ok=True)
        raise


@contextmanager
def opened(path,temporary_root):
    """Yield a verified seekable ZIP; remove temporary plaintext on every exit."""
    path=Path(path);temporary_root=Path(temporary_root);temporary_root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='backup-decrypt-',dir=temporary_root) as directory:
        output=Path(directory)/'verified.zip'
        with path.open('rb') as encrypted:
            magic=encrypted.read(len(MAGIC))
            if magic!=MAGIC:
                # Original DPAPI archives require the native whole-blob API.
                output.write_bytes(win32crypt.CryptUnprotectData(path.read_bytes(),None,None,None,0)[1])
            else:
                size_raw=encrypted.read(4)
                if len(size_raw)!=4:raise ValueError('备份头不完整')
                size=struct.unpack('>I',size_raw)[0]
                if not 1<=size<=65536:raise ValueError('备份头无效')
                nonce=encrypted.read(12);wrapped=encrypted.read(size)
                if len(nonce)!=12 or len(wrapped)!=size:raise ValueError('备份头不完整')
                header=magic+size_raw+nonce+wrapped;start=encrypted.tell();end=path.stat().st_size-16
                if end<start:raise ValueError('备份内容不完整')
                encrypted.seek(end);tag=encrypted.read(16);encrypted.seek(start)
                key=win32crypt.CryptUnprotectData(wrapped,None,None,None,0)[1]
                decryptor=Cipher(algorithms.AES256(key),modes.GCM(nonce,tag)).decryptor()
                decryptor.authenticate_additional_data(header)
                remaining=end-start
                try:
                    with output.open('xb') as raw:
                        while remaining:
                            block=encrypted.read(min(CHUNK,remaining))
                            if not block:raise ValueError('备份内容不完整')
                            remaining-=len(block);raw.write(decryptor.update(block))
                        raw.write(decryptor.finalize())
                except InvalidTag:raise ValueError('备份认证失败；未使用未通过认证的内容') from None
        yield output
