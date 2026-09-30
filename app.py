import streamlit as st
import pandas as pd
import sqlite3
import os
import hmac
import hashlib
from io import BytesIO
from datetime import date

st.set_page_config(page_title="MyDesk", layout="wide")

DB = "mydesk.db"
CATEGORIES = ["Food", "Transport", "Airtime", "School", "Rent", "Other"]


# ---------- Database ----------
def init_db():
    conn = sqlite3.connect(DB)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE, salt TEXT, pw_hash TEXT)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, type TEXT, category TEXT,
            description TEXT, amount REAL)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT, done INTEGER DEFAULT 0)"""
    )
    # Ongeza user_id kama haipo
    for table in ["expenses", "todos"]:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        if "user_id" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER")
    conn.commit()
    conn.close()


def read(query, params=()):
    conn = sqlite3.connect(DB)
    try:
        return pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()


def run(query, params=()):
    conn = sqlite3.connect(DB)
    try:
        conn.execute(query, params)
        conn.commit()
    finally:
        conn.close()


# ---------- Auth ----------
def hash_pw(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 100000
    ).hex()


def register(username, password):
    username = username.strip().lower()
    if len(username) < 3:
        return False, "Username iwe angalau herufi 3"
    if len(password) < 4:
        return False, "Password iwe angalau herufi 4"

    conn = sqlite3.connect(DB)
    try:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE username=?", (username,)
        ).fetchone()
        if exists:
            return False, "Username tayari imechukuliwa"

        first_user = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        salt = os.urandom(16).hex()
        cur = conn.execute(
            "INSERT INTO users (username, salt, pw_hash) VALUES (?,?,?)",
            (username, salt, hash_pw(password, salt)),
        )
        uid = cur.lastrowid
        if first_user:
            # Data ya zamani inakuwa ya akaunti ya kwanza
            conn.execute("UPDATE expenses SET user_id=? WHERE user_id IS NULL", (uid,))
            conn.execute("UPDATE todos SET user_id=? WHERE user_id IS NULL", (uid,))
        conn.commit()
        return True, "Akaunti imetengenezwa! Sasa ingia (Login)."
    finally:
        conn.close()


def login(username, password):
    username = username.strip().lower()
    conn = sqlite3.connect(DB)
    try:
        row = conn.execute(
            "SELECT id, salt, pw_hash FROM users WHERE username=?", (username,)
        ).fetchone()
    finally:
        conn.close()
    if row and hmac.compare_digest(row[2], hash_pw(password, row[1])):
        return row[0], username
    return None, None


# ---------- Data ----------
def load_expenses(uid):
    df = read(
        """SELECT id, date AS Date, type AS Type, category AS Category,
                  description AS Description, amount AS Amount
           FROM expenses WHERE user_id=? ORDER BY date, id""",
        (uid,),
    )
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0)
    return df


def load_todos(uid):
    df = read(
        "SELECT id, task AS Task, done AS Done FROM todos WHERE user_id=? ORDER BY id",
        (uid,),
    )
    df["Done"] = df["Done"].astype(bool)
    return df


def to_excel(df):
    out = df.drop(columns="id").copy()
    out["Date"] = out["Date"].dt.date
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        out.to_excel(writer, index=False, sheet_name="Expenses")
    return buf.getvalue()


init_db()

# ---------- Login screen ----------
if "user_id" not in st.session_state:
    st.session_state.user_id = None
    st.session_state.username = None

if st.session_state.user_id is None:
    st.title("MyDesk")
    tab_login, tab_reg = st.tabs(["Login", "Jisajili"])

    with tab_login:
        with st.form("login_form"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            go = st.form_submit_button("Ingia")
        if go:
            uid, uname = login(u, p)
            if uid:
                st.session_state.user_id = uid
                st.session_state.username = uname
                st.rerun()
            else:
                st.error("Username au password si sahihi")

    with tab_reg:
        with st.form("reg_form"):
            u2 = st.text_input("Username mpya")
            p2 = st.text_input("Password mpya", type="password")
            p3 = st.text_input("Rudia password", type="password")
            go2 = st.form_submit_button("Tengeneza akaunti")
        if go2:
            if p2 != p3:
                st.error("Password hazifanani")
            else:
                ok, msg = register(u2, p2)
                (st.success if ok else st.error)(msg)

    st.stop()

# ---------- Main app (mtumiaji ameingia) ----------
uid = st.session_state.user_id

st.title("MyDesk")
menu = st.sidebar.radio("Menu", ["Home", "Expenses", "To-Do", "Invoice"])
st.sidebar.write(f"Umeingia kama: **{st.session_state.username}**")
if st.sidebar.button("Logout"):
    st.session_state.user_id = None
    st.session_state.username = None
    st.rerun()


# ---------- HOME ----------
if menu == "Home":
    st.subheader("Home")
    st.write(f"Karibu {st.session_state.username}! Hii ni app yako ya kila siku.")

    df = load_expenses(uid)
    todos = load_todos(uid)
    income = df[df["Type"] == "Income"]["Amount"].sum()
    expense = df[df["Type"] == "Expense"]["Amount"].sum()
    pending = int((~todos["Done"]).sum()) if not todos.empty else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Balance", f"{income - expense:,.0f} TSh")
    c2.metric("Expenses", f"{expense:,.0f} TSh")
    c3.metric("Tasks zilizobaki", pending)

    st.info("Chagua zana kwenye menu upande wa kushoto.")


# ---------- EXPENSES ----------
elif menu == "Expenses":
    st.subheader("Expenses")

    with st.form("add_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        d = c1.date_input("Date", date.today())
        t = c2.selectbox("Type", ["Expense", "Income"])
        cat = c1.selectbox("Category", CATEGORIES)
        amount = c2.number_input("Amount (TSh)", min_value=0, step=500)
        desc = st.text_input("Description")
        submit = st.form_submit_button("Save")

    if submit:
        if amount > 0:
            run(
                "INSERT INTO expenses (user_id, date, type, category, description, amount) VALUES (?,?,?,?,?,?)",
                (uid, d.isoformat(), t, cat, desc, float(amount)),
            )
            st.success("Imehifadhiwa!")
        else:
            st.warning("Weka amount kubwa kuliko 0")

    df = load_expenses(uid)

    st.markdown("### Chuja")
    f1, f2 = st.columns(2)
    months = sorted(df["Date"].dt.strftime("%Y-%m").dropna().unique(), reverse=True)
    month = f1.selectbox("Mwezi", ["Zote"] + months)
    cats = f2.multiselect("Category", CATEGORIES)

    view = df.copy()
    if month != "Zote":
        view = view[view["Date"].dt.strftime("%Y-%m") == month]
    if cats:
        view = view[view["Category"].isin(cats)]

    income = view[view["Type"] == "Income"]["Amount"].sum()
    expense = view[view["Type"] == "Expense"]["Amount"].sum()
    m1, m2, m3 = st.columns(3)
    m1.metric("Income", f"{income:,.0f} TSh")
    m2.metric("Expenses", f"{expense:,.0f} TSh")
    m3.metric("Balance", f"{income - expense:,.0f} TSh")

    exp = view[view["Type"] == "Expense"]
    if not exp.empty:
        st.markdown("### Matumizi kwa Category")
        st.bar_chart(exp.groupby("Category")["Amount"].sum())

    st.markdown("### Hariri / Futa")
    if view.empty:
        st.write("Hakuna data.")
    else:
        st.caption("Bonyeza kisanduku kubadilisha. Tiki 'Delete' kufuta mstari.")
        edit_df = view.copy()
        edit_df["Delete"] = False
        edited = st.data_editor(
            edit_df,
            column_config={
                "id": None,
                "Date": st.column_config.DateColumn("Date"),
                "Type": st.column_config.SelectboxColumn("Type", options=["Expense", "Income"]),
                "Category": st.column_config.SelectboxColumn("Category", options=CATEGORIES),
                "Amount": st.column_config.NumberColumn("Amount", min_value=0, step=500),
            },
        )

        if st.button("Hifadhi mabadiliko"):
            conn = sqlite3.connect(DB)
            for _, r in edited.iterrows():
                rid = int(r["id"])
                if r["Delete"]:
                    conn.execute(
                        "DELETE FROM expenses WHERE id=? AND user_id=?", (rid, uid)
                    )
                else:
                    dt = pd.to_datetime(r["Date"], errors="coerce")
                    dt_str = dt.strftime("%Y-%m-%d") if pd.notna(dt) else None
                    dsc = "" if pd.isna(r["Description"]) else str(r["Description"])
                    conn.execute(
                        "UPDATE expenses SET date=?, type=?, category=?, description=?, amount=? WHERE id=? AND user_id=?",
                        (dt_str, r["Type"], r["Category"], dsc, float(r["Amount"]), rid, uid),
                    )
            conn.commit()
            conn.close()
            st.rerun()

        st.download_button(
            "Pakua Excel",
            to_excel(view),
            file_name="expenses.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


# ---------- TO-DO ----------
elif menu == "To-Do":
    st.subheader("To-Do")

    with st.form("todo_form", clear_on_submit=True):
        task = st.text_input("Task mpya")
        add = st.form_submit_button("Add")

    if add and task.strip():
        run(
            "INSERT INTO todos (user_id, task, done) VALUES (?, ?, 0)",
            (uid, task.strip()),
        )
        st.rerun()

    todos = load_todos(uid)

    if todos.empty:
        st.write("Hakuna task bado.")
    else:
        changed = False
        for _, row in todos.iterrows():
            tid = int(row["id"])
            done = st.checkbox(row["Task"], value=bool(row["Done"]), key=f"task_{tid}")
            if done != bool(row["Done"]):
                run(
                    "UPDATE todos SET done=? WHERE id=? AND user_id=?",
                    (int(done), tid, uid),
                )
                changed = True
        if changed:
            st.rerun()

        if st.button("Futa zilizokamilika"):
            run("DELETE FROM todos WHERE done=1 AND user_id=?", (uid,))
            st.rerun()


# ---------- INVOICE ----------
elif menu == "Invoice":
    st.subheader("Invoice / Risiti")

    c1, c2 = st.columns(2)
    business = c1.text_input("Jina la biashara", "Biashara Yangu")
    customer = c2.text_input("Jina la mteja")

    st.write("Ongeza bidhaa (bonyeza + chini ya table kuongeza mstari):")
    items = st.data_editor(
        pd.DataFrame([{"Item": "", "Qty": 1, "Price": 0}]),
        num_rows="dynamic",
    )

    items["Qty"] = pd.to_numeric(items["Qty"], errors="coerce").fillna(0)
    items["Price"] = pd.to_numeric(items["Price"], errors="coerce").fillna(0)
    items["Total"] = items["Qty"] * items["Price"]
    grand = items["Total"].sum()

    st.metric("Jumla", f"{grand:,.0f} TSh")

    if st.button("Tengeneza Risiti"):
        lines = [
            business.upper(),
            f"Tarehe: {date.today()}",
            f"Mteja: {customer}",
            "-" * 32,
        ]
        for _, r in items.iterrows():
            if str(r["Item"]).strip():
                lines.append(f"{r['Item']} x{int(r['Qty'])} = {r['Total']:,.0f} TSh")
        lines += ["-" * 32, f"JUMLA: {grand:,.0f} TSh", "Asante kwa kununua!"]
        receipt = "\n".join(lines)

        st.code(receipt)
        st.download_button("Pakua Risiti (.txt)", receipt, file_name="risiti.txt")