import hmac

from auth.users import get_user, hash_password


def login(email, password):
    user = get_user(email)
    if user is None:
        return False
    return hmac.compare_digest(user["password_hash"], hash_password(password))
