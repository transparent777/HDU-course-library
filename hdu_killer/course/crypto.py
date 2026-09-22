"""统一认证 AES 与教务 RSA 加密。"""

from __future__ import annotations

import base64
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA


def pkcs7_pad(data: bytes, block_size: int) -> bytes:
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len] * pad_len)


def aes_encrypt_cas(key_b64: str, plain_text: str) -> str:
    key = base64.b64decode(key_b64)
    cipher = AES.new(key, AES.MODE_ECB)
    padded = pkcs7_pad(plain_text.encode("utf-8"), cipher.block_size)
    return base64.b64encode(cipher.encrypt(padded)).decode("ascii")


def rsa_encrypt_jw(modulus_b64: str, data: str) -> str:
    mod_bytes = base64.b64decode(modulus_b64)
    n = int.from_bytes(mod_bytes, "big")
    key = RSA.construct((n, 65537))
    cipher = PKCS1_v1_5.new(key)
    encrypted = cipher.encrypt(data.encode("utf-8"))
    return base64.b64encode(encrypted).decode("ascii")
