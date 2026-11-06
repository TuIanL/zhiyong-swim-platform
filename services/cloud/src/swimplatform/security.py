import hashlib
import hmac
import secrets

# OWASP Password Storage Cheat Sheet 的 scrypt 最低配置之一。
# https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html#scrypt
N, R, P = 2**15, 8, 3


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, maxmem=64 * 1024 * 1024, dklen=32)
    return f"scrypt${N}${R}${P}${salt.hex()}${derived.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        # 配置只接受本版本生成的参数，避免损坏记录导致无界资源消耗。
        if algorithm != "scrypt" or (int(n), int(r), int(p)) != (N, R, P):
            return False
        derived = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=N, r=R, p=P, maxmem=64 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(derived, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


DUMMY_PASSWORD = password_hash("unused-placeholder-password")
