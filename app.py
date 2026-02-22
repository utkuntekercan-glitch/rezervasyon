import sqlite3
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Old School Rezervasyon", layout="wide")

DB_PATH = Path("oldschool_reservation.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(conn: sqlite3.Connection):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reservation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            d TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            phone TEXT,
            people_count INTEGER NOT NULL DEFAULT 1,
            table_no TEXT,
            status TEXT NOT NULL DEFAULT 'onayli',
            note TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reservation_d ON reservation(d);")
    conn.commit()


def df_query(conn, q, params=()):
    return pd.read_sql_query(q, conn, params=params)


def status_badge(s: str) -> str:
    s = str(s).lower()
    if s == "onayli":
        return "🟢 Onayli"
    if s == "beklemede":
        return "🟡 Beklemede"
    if s == "iptal":
        return "🔴 Iptal"
    return s


st.title("Old School Rezervasyon Yonetimi")

conn = get_conn()
init_db(conn)

today = date.today()

with st.sidebar:
    page = st.radio("Menu", ["Dashboard", "Yeni Rezervasyon", "Rezervasyon Listesi"])
    selected_day = st.date_input("Tarih", value=today)


if page == "Dashboard":
    st.subheader(f"{selected_day.isoformat()} Ozeti")
    rows = df_query(
        conn,
        """
        SELECT status, COUNT(*) AS adet
        FROM reservation
        WHERE d = ?
        GROUP BY status
        """,
        (selected_day.isoformat(),),
    )
    total = int(rows["adet"].sum()) if len(rows) else 0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam", total)
    c2.metric("Onayli", int(rows.loc[rows["status"] == "onayli", "adet"].sum()) if len(rows) else 0)
    c3.metric("Beklemede", int(rows.loc[rows["status"] == "beklemede", "adet"].sum()) if len(rows) else 0)
    c4.metric("Iptal", int(rows.loc[rows["status"] == "iptal", "adet"].sum()) if len(rows) else 0)

    day_list = df_query(
        conn,
        """
        SELECT id, d AS Tarih, start_time AS Baslangic, end_time AS Bitis,
               customer_name AS Musteri, phone AS Telefon, people_count AS Kisi,
               table_no AS Masa, status AS Durum, note AS Notlar
        FROM reservation
        WHERE d = ?
        ORDER BY start_time
        """,
        (selected_day.isoformat(),),
    )
    if len(day_list):
        day_list["Durum"] = day_list["Durum"].apply(status_badge)
        st.dataframe(day_list, use_container_width=True, hide_index=True)
    else:
        st.info("Bu tarih icin rezervasyon yok.")

elif page == "Yeni Rezervasyon":
    st.subheader("Yeni Rezervasyon")
    with st.form("create_reservation"):
        d = st.date_input("Tarih", value=selected_day)
        c1, c2 = st.columns(2)
        start_time = c1.text_input("Baslangic (HH:MM)", value="19:00")
        end_time = c2.text_input("Bitis (HH:MM)", value="21:00")
        customer_name = st.text_input("Musteri Adi", value="")
        phone = st.text_input("Telefon", value="")
        c3, c4, c5 = st.columns(3)
        people_count = c3.number_input("Kisi Sayisi", min_value=1, max_value=50, value=2, step=1)
        table_no = c4.text_input("Masa No", value="")
        status = c5.selectbox("Durum", ["onayli", "beklemede", "iptal"], index=0)
        note = st.text_input("Not", value="")
        submitted = st.form_submit_button("Rezervasyon Ekle", type="primary")

    if submitted:
        if not customer_name.strip():
            st.warning("Musteri adi zorunlu.")
        else:
            conn.execute(
                """
                INSERT INTO reservation(
                    d, start_time, end_time, customer_name, phone, people_count, table_no, status, note, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    d.isoformat(),
                    start_time.strip(),
                    end_time.strip(),
                    customer_name.strip(),
                    phone.strip() or None,
                    int(people_count),
                    table_no.strip() or None,
                    status,
                    note.strip() or None,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            conn.commit()
            st.success("Rezervasyon eklendi.")
            st.rerun()

elif page == "Rezervasyon Listesi":
    st.subheader("Rezervasyon Listesi")
    q = st.text_input("Ara (musteri/telefon/masa/not)")
    status_filter = st.multiselect("Durum", ["onayli", "beklemede", "iptal"], default=["onayli", "beklemede", "iptal"])

    rows = df_query(
        conn,
        """
        SELECT id, d, start_time, end_time, customer_name, phone, people_count, table_no, status, note
        FROM reservation
        ORDER BY d DESC, start_time DESC
        """,
    )
    if len(rows):
        filtered = rows.copy()
        if status_filter:
            filtered = filtered[filtered["status"].isin(status_filter)]
        if q.strip():
            text = filtered.fillna("").astype(str).agg(" | ".join, axis=1).str.lower()
            filtered = filtered[text.str.contains(q.strip().lower(), regex=False)]

        show = filtered.rename(
            columns={
                "d": "Tarih",
                "start_time": "Baslangic",
                "end_time": "Bitis",
                "customer_name": "Musteri",
                "phone": "Telefon",
                "people_count": "Kisi",
                "table_no": "Masa",
                "status": "Durum",
                "note": "Notlar",
            }
        )
        show["Durum"] = show["Durum"].apply(status_badge)
        st.caption(f"Kayit: {len(show)}")
        st.dataframe(show, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("### Kayit Duzenle / Iptal")
        picked_id = st.selectbox("Rezervasyon Sec", filtered["id"].tolist())
        row = filtered.loc[filtered["id"] == picked_id].iloc[0]
        with st.form("edit_reservation"):
            ed = st.date_input("Tarih", value=date.fromisoformat(str(row["d"])))
            c1, c2 = st.columns(2)
            est = c1.text_input("Baslangic (HH:MM)", value=str(row["start_time"]))
            eet = c2.text_input("Bitis (HH:MM)", value=str(row["end_time"]))
            ename = st.text_input("Musteri Adi", value=str(row["customer_name"]))
            ephone = st.text_input("Telefon", value="" if pd.isna(row["phone"]) else str(row["phone"]))
            c3, c4, c5 = st.columns(3)
            epeople = c3.number_input("Kisi Sayisi", min_value=1, max_value=50, value=int(row["people_count"]), step=1)
            etable = c4.text_input("Masa No", value="" if pd.isna(row["table_no"]) else str(row["table_no"]))
            estatus = c5.selectbox("Durum", ["onayli", "beklemede", "iptal"], index=["onayli", "beklemede", "iptal"].index(str(row["status"])))
            enote = st.text_input("Not", value="" if pd.isna(row["note"]) else str(row["note"]))
            b1, b2 = st.columns(2)
            save = b1.form_submit_button("Guncelle", type="primary")
            cancel = b2.form_submit_button("Iptal Olarak Isaretle")

        if save:
            conn.execute(
                """
                UPDATE reservation
                SET d=?, start_time=?, end_time=?, customer_name=?, phone=?, people_count=?, table_no=?, status=?, note=?
                WHERE id=?
                """,
                (
                    ed.isoformat(),
                    est.strip(),
                    eet.strip(),
                    ename.strip(),
                    ephone.strip() or None,
                    int(epeople),
                    etable.strip() or None,
                    estatus,
                    enote.strip() or None,
                    int(picked_id),
                ),
            )
            conn.commit()
            st.success("Rezervasyon guncellendi.")
            st.rerun()

        if cancel:
            conn.execute("UPDATE reservation SET status='iptal' WHERE id=?", (int(picked_id),))
            conn.commit()
            st.success("Rezervasyon iptal olarak isaretlendi.")
            st.rerun()
    else:
        st.info("Henuz rezervasyon kaydi yok.")
