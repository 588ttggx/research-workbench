"""Bounded-memory AES-GCM backup containers for local and portable use.

Local keys are random per archive and protected by Windows DPAPI. Portable
keys are derived from a user-supplied passphrase using a fresh random salt.
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
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC=b'RESEARCH-BACKUP\x04\r\n'
PORTABLE_MAGIC = b'RESEARCH-PORTABLE\x01\r\n'
CHUNK=1024*1024
GCM_MAX_BYTES = (1 << 36) - 32


def file_digest(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(CHUNK),b''):digest.update(block)
    return digest.hexdigest()


def _portable_key(passphrase, salt):
    if not isinstance(passphrase, str) or not 16 <= len(passphrase) <= 1024:
        raise ValueError('迁移口令须为 16 至 1024 个字符')
    # These cost parameters are fixed by the portable container version.
    return Scrypt(salt=salt, length=32, n=1 << 17, r=8, p=1).derive(passphrase.encode('utf-8'))


def protect(source,target, *, passphrase=None):
    """Publish one new authenticated archive, preserving any existing backup."""
    target=Path(target)
    if target.exists():raise ValueError('同名备份已存在，未覆盖旧备份')
    nonce=os.urandom(12)
    if passphrase is None:
        key=os.urandom(32)
        wrapped=win32crypt.CryptProtectData(key,'Research Workspace Backup Key',None,None,None,4)
        header=MAGIC+struct.pack('>I',len(wrapped))+nonce+wrapped
    else:
        salt=os.urandom(16)
        key=_portable_key(passphrase, salt)
        header=PORTABLE_MAGIC+nonce+salt
    encryptor=Cipher(algorithms.AES256(key),modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header)
    created=False
    try:
        with Path(source).open('rb') as raw,target.open('xb') as encrypted:
            created=True
            if passphrase is not None and os.fstat(raw.fileno()).st_size > GCM_MAX_BYTES:
                raise ValueError('备份超过此迁移格式支持的大小')
            encrypted.write(header)
            for block in iter(lambda:raw.read(CHUNK),b''):encrypted.write(encryptor.update(block))
            encrypted.write(encryptor.finalize());encrypted.write(encryptor.tag)
            encrypted.flush();os.fsync(encrypted.fileno())
    except Exception:
        if created:target.unlink(missing_ok=True)
        raise


def _decrypt(encrypted, output, header, nonce, key, *, portable=False):
    start=encrypted.tell();end=os.fstat(encrypted.fileno()).st_size-16
    if end<start:raise ValueError('备份内容不完整')
    if portable and end-start>GCM_MAX_BYTES:raise ValueError('备份超过此迁移格式支持的大小')
    encrypted.seek(end);tag=encrypted.read(16);encrypted.seek(start)
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


@contextmanager
def opened(path,temporary_root, *, passphrase=None):
    """Yield a verified seekable ZIP; remove temporary plaintext on every exit."""
    path=Path(path);temporary_root=Path(temporary_root);temporary_root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='backup-decrypt-',dir=temporary_root) as directory:
        output=Path(directory)/'verified.zip'
        with path.open('rb') as encrypted:
            if passphrase is not None:
                if encrypted.read(len(PORTABLE_MAGIC))!=PORTABLE_MAGIC:
                    raise ValueError('无法识别此迁移备份格式')
                nonce=encrypted.read(12);salt=encrypted.read(16)
                if len(nonce)!=12 or len(salt)!=16:raise ValueError('备份头不完整')
                _decrypt(encrypted,output,PORTABLE_MAGIC+nonce+salt,nonce,
                         _portable_key(passphrase,salt),portable=True)
            elif encrypted.read(len(MAGIC))==MAGIC:
                size_raw=encrypted.read(4)
                if len(size_raw)!=4:raise ValueError('备份头不完整')
                size=struct.unpack('>I',size_raw)[0]
                if not 1<=size<=65536:raise ValueError('备份头无效')
                nonce=encrypted.read(12);wrapped=encrypted.read(size)
                if len(nonce)!=12 or len(wrapped)!=size:raise ValueError('备份头不完整')
                key=win32crypt.CryptUnprotectData(wrapped,None,None,None,0)[1]
                _decrypt(encrypted,output,MAGIC+size_raw+nonce+wrapped,nonce,key)
            else:
                # Original DPAPI archives require the native whole-blob API.
                output.write_bytes(win32crypt.CryptUnprotectData(path.read_bytes(),None,None,None,0)[1])
        yield output
