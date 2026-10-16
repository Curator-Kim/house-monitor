"""Web 访问登录门禁；密码只以 PBKDF2 哈希形式保存在本地 secrets。"""
import base64
import hashlib
import hmac
import os
import secrets

import streamlit as st

ITERATIONS = 260000


def hash_password(password, salt=None, iterations=ITERATIONS):
    if not password:
        raise ValueError("密码不能为空")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join(("pbkdf2_sha256", str(iterations),
                     base64.b64encode(salt).decode("ascii"),
                     base64.b64encode(digest).decode("ascii")))


def verify_password(password, encoded):
    try:
        algorithm, iterations, salt, digest = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                        base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(candidate, base64.b64decode(digest))
    except (AttributeError, TypeError, ValueError):
        return False


def _credentials():
    try:
        section = st.secrets.get("web_auth", {})
    except Exception:
        section = {}
    username = section.get("username") or os.environ.get("HOUSE_WEB_USERNAME")
    password_hash = section.get("password_hash") or os.environ.get("HOUSE_WEB_PASSWORD_HASH")
    return username, password_hash


def require_login():
    username, password_hash = _credentials()
    if not username or not password_hash:
        st.error("Web 登录凭据尚未配置，已停止显示数据。")
        st.stop()
    if st.session_state.get("web_authenticated"):
        if st.sidebar.button("退出登录"):
            st.session_state.pop("web_authenticated", None)
            st.rerun()
        return
    st.title("住宅价格观察 · 登录")
    with st.form("web_login"):
        input_user = st.text_input("账号")
        input_password = st.text_input("密码", type="password")
        submitted = st.form_submit_button("登录", type="primary")
    if submitted:
        if hmac.compare_digest(input_user or "", username) and verify_password(input_password or "", password_hash):
            st.session_state["web_authenticated"] = True
            st.rerun()
        st.error("账号或密码错误")
    st.stop()