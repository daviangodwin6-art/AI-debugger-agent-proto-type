import hashlib

_users = {}


def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def register(email, password):
    email = email.strip().lower()
    if "@" not in email:
        raise ValueError("invalid email")
    if email in _users:
        raise ValueError("user already exists")
    _users[email] = {"email": email, "password_hash": hash_password(password)}
    return _users[email]


def get_user(email):
    return _users.get(email)


def clear():
    _users.clear()
