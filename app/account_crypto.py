# -*- coding: utf-8 -*-
"""纯标准库的账号文件加解密(无第三方依赖)。
格式: MAGIC | salt(16) | nonce(16) | ciphertext | mac(32)
- KDF: PBKDF2-HMAC-SHA256, 20万次 -> 32字节(拆 enc_key/mac_key)
- 加密: HMAC-SHA256(enc_key, nonce||ctr) 作密钥流与明文异或(Encrypt-then-MAC)
- 校验: HMAC-SHA256(mac_key, MAGIC|salt|nonce|ciphertext), 错密码/被改都失败
"""
import hashlib, hmac, os, struct

MAGIC = b"ACCENC1\n"
_ITER = 200000


def _keys(password: str, salt: bytes):
    k = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITER, dklen=32)
    return k[:16], k[16:32]


def _stream(enc_key: bytes, nonce: bytes, n: int):
    out = b""
    ctr = 0
    while len(out) < n:
        block = hmac.new(enc_key, nonce + struct.pack(">I", ctr), hashlib.sha256).digest()
        out += block
        ctr += 1
    return out[:n]


def encrypt_bytes(plaintext: bytes, password: str) -> bytes:
    salt = os.urandom(16)
    nonce = os.urandom(16)
    enc_key, mac_key = _keys(password, salt)
    ks = _stream(enc_key, nonce, len(plaintext))
    ct = bytes(a ^ b for a, b in zip(plaintext, ks))
    blob = MAGIC + salt + nonce + ct
    mac = hmac.new(mac_key, blob, hashlib.sha256).digest()
    return blob + mac


def decrypt_bytes(blob: bytes, password: str) -> bytes:
    if not blob.startswith(MAGIC):
        raise ValueError("不是加密文件")
    body = blob[len(MAGIC):]
    salt, nonce, ct, mac = body[:16], body[16:32], body[32:-32], body[-32:]
    enc_key, mac_key = _keys(password, salt)
    expect = hmac.new(mac_key, MAGIC + salt + nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(expect, mac):
        raise ValueError("密码错误或文件被篡改")
    ks = _stream(enc_key, nonce, len(ct))
    return bytes(a ^ b for a, b in zip(ct, ks))
