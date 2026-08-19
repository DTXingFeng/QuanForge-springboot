#!/usr/bin/env python3
"""从生产库解密 LLM key 写入 tools/.backtest_llm_key（chmod 600，仅供本机回测用）。
复现 AesEncryptor：AES-256-GCM，Base64(IV[12] + ciphertext+tag[16])。"""
import base64, os, re, sqlite3, stat, sys

LOCAL_YAML = "/mnt/nvme/quanforge/application-local.yaml"
KEY_OUT = "/mnt/nvme/quanforge/tools/.backtest_llm_key"
DB = "/mnt/nvme/quanforge/data/quanforge.db"

def main():
    key_b64 = os.environ.get("APP_CRYPTO_KEY")
    if not key_b64:
        txt = open(LOCAL_YAML).read()
        m = re.search(r"key:\s*\$?\{?APP_CRYPTO_KEY:([^}]*)\}?|key:\s*([A-Za-z0-9+/=]{40,})",
                      txt)
        key_b64 = (m.group(1) or m.group(2)) if m else None
    if not key_b64:
        sys.exit("找不到 AES key（application-local.yaml / 环境变量）")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = base64.b64decode(key_b64)
    con = sqlite3.connect(DB)
    blob = con.execute("select api_key from ai_config where id=1").fetchone()[0]
    con.close()
    raw = base64.b64decode(blob)
    plain = AESGCM(key).decrypt(raw[:12], raw[12:], None).decode()
    fd = os.open(KEY_OUT, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    os.write(fd, plain.encode())
    os.close(fd)
    print(f"key written -> {KEY_OUT} ({len(plain)} chars, 600)")

if __name__ == "__main__":
    main()
