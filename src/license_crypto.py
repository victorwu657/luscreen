import base64
import re
import hashlib
from typing import Tuple


_B64_ALLOWED_RE = re.compile(r"[A-Za-z0-9+/=_-]+")


def normalize_license_key(key: str) -> str:
    if key is None:
        return ""
    key = key.replace("\ufeff", "").replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    parts = _B64_ALLOWED_RE.findall(key)
    key = "".join(parts).strip()
    if not key:
        return ""
    pad_len = (-len(key)) % 4
    if pad_len:
        key = key + ("=" * pad_len)
    return key


def decode_license_signature(key: str) -> bytes:
    key = normalize_license_key(key)
    if not key:
        raise ValueError("激活码为空或格式无效")
    try:
        if "-" in key or "_" in key:
            return base64.urlsafe_b64decode(key.encode("utf-8"))
        return base64.b64decode(key.encode("utf-8"))
    except Exception as e:
        raise ValueError(f"激活码 Base64 解码失败: {e}") from e


def verify_rsa_pkcs1v15_sha256(public_key_pem: bytes, message: bytes, signature: bytes) -> bool:
    n, e = _load_rsa_public_numbers_from_spki_pem(public_key_pem)
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    sig_int = int.from_bytes(signature, "big", signed=False)
    em_int = pow(sig_int, e, n)
    em = em_int.to_bytes(k, "big", signed=False)
    if len(em) < 11 or em[0:2] != b"\x00\x01":
        return False
    try:
        sep_index = em.index(b"\x00", 2)
    except ValueError:
        return False
    ps = em[2:sep_index]
    if len(ps) < 8 or any(b != 0xFF for b in ps):
        return False
    digest = hashlib.sha256(message).digest()
    expected = _sha256_digest_info(digest)
    return em[sep_index + 1 :] == expected


def _sha256_digest_info(digest: bytes) -> bytes:
    if len(digest) != 32:
        raise ValueError("SHA256 摘要长度不正确")
    return bytes.fromhex("3031300d060960864801650304020105000420") + digest


def _load_rsa_public_numbers_from_spki_pem(pem: bytes) -> Tuple[int, int]:
    der = _pem_to_der(pem)
    tag, spki, _ = _read_tlv(der, 0)
    if tag != 0x30:
        raise ValueError("SPKI 格式不正确")
    idx = 0
    _, _, idx = _read_tlv(spki, idx)
    tag, bitstring, idx = _read_tlv(spki, idx)
    if tag != 0x03 or not bitstring:
        raise ValueError("SPKI BIT STRING 缺失")
    if bitstring[0] != 0x00:
        raise ValueError("SPKI BIT STRING 未对齐")
    inner = bitstring[1:]
    tag, rsa_pub, _ = _read_tlv(inner, 0)
    if tag != 0x30:
        raise ValueError("RSA 公钥序列缺失")
    tag_n, n_bytes, idx2 = _read_tlv(rsa_pub, 0)
    if tag_n != 0x02:
        raise ValueError("RSA modulus 缺失")
    tag_e, e_bytes, idx2 = _read_tlv(rsa_pub, idx2)
    if tag_e != 0x02:
        raise ValueError("RSA exponent 缺失")
    n = _decode_asn1_integer(n_bytes)
    e = _decode_asn1_integer(e_bytes)
    if n <= 0 or e <= 0:
        raise ValueError("RSA 公钥数值非法")
    return n, e


def _pem_to_der(pem: bytes) -> bytes:
    if not pem:
        raise ValueError("PEM 为空")
    text = pem.decode("utf-8", errors="ignore")
    lines = [line.strip() for line in text.splitlines() if line and "BEGIN" not in line and "END" not in line]
    if not lines:
        raise ValueError("PEM 内容缺失")
    b64 = "".join(lines)
    return base64.b64decode(b64.encode("ascii"))


def _decode_asn1_integer(data: bytes) -> int:
    if not data:
        return 0
    if data[0] == 0x00:
        data = data[1:]
    if not data:
        return 0
    return int.from_bytes(data, "big", signed=False)


def _read_len(data: bytes, idx: int) -> Tuple[int, int]:
    if idx >= len(data):
        raise ValueError("DER 越界")
    first = data[idx]
    idx += 1
    if first < 0x80:
        return first, idx
    nbytes = first & 0x7F
    if nbytes == 0 or nbytes > 4:
        raise ValueError("DER 长度字段非法")
    if idx + nbytes > len(data):
        raise ValueError("DER 长度越界")
    length = int.from_bytes(data[idx : idx + nbytes], "big", signed=False)
    idx += nbytes
    return length, idx


def _read_tlv(data: bytes, idx: int) -> Tuple[int, bytes, int]:
    if idx >= len(data):
        raise ValueError("DER 越界")
    tag = data[idx]
    idx += 1
    length, idx = _read_len(data, idx)
    end = idx + length
    if end > len(data):
        raise ValueError("DER 长度越界")
    return tag, data[idx:end], end
