import sqlite3
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Old School Rezervasyon", layout="wide")

DB_PATH = Path("oldschool_reservation.db")
AREA_LAYOUT = [
    ("Yellow Area", "Y", 32),
    ("EF Area", "EF", 10),
    ("Red Area", "R", 10),
    ("VIP", "VIP", 5),
    ("Blue Area", "B", 10),
]


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


def normalize_pc_list(raw: str | None) -> list[str]:
    if raw is None:
        return []
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    # Backward compatibility for old single text values
    if len(parts) == 1 and "-" not in parts[0]:
        return parts
    return sorted(parts)


def collect_occupied_pcs(conn: sqlite3.Connection, d_str: str, start_time: str, end_time: str, exclude_id: int | None = None) -> set[str]:
    q = """
        SELECT id, table_no
        FROM reservation
        WHERE d = ?
          AND status != 'iptal'
          AND NOT (end_time <= ? OR start_time >= ?)
    """
    params = [d_str, start_time, end_time]
    if exclude_id is not None:
        q += " AND id != ?"
        params.append(int(exclude_id))

    rows = conn.execute(q, tuple(params)).fetchall()
    occ: set[str] = set()
    for _, pcs in rows:
        for p in normalize_pc_list(pcs):
            occ.add(p)
    return occ


def render_pc_picker(key_prefix: str, occupied: set[str], preselected: list[str] | None = None) -> list[str]:
    preselected = preselected or []
    selected: list[str] = []
    st.markdown("#### Bilgisayar Secimi")
    st.caption("Dolu bilgisayarlar kilitli gorunur. Rezervasyon icin en az 1 bilgisayar sec.")

    for area_name, area_code, count in AREA_LAYOUT:
        st.markdown(f"**{area_name}** ({count})")
        cols = st.columns(8)
        for i in range(1, count + 1):
            pc_id = f"{area_code}-{i:02d}"
            default_val = pc_id in preselected
            disabled = (pc_id in occupied) and (pc_id not in preselected)
            col = cols[(i - 1) % 8]
            with col:
                val = st.checkbox(
                    pc_id,
                    value=default_val,
                    key=f"{key_prefix}_{pc_id}",
                    disabled=disabled,
                )
            if val:
                selected.append(pc_id)
        st.write("")
    return sorted(selected)


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
               table_no AS Bilgisayarlar, status AS Durum, note AS Notlar
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
        c3, c4 = st.columns(2)
        status = c3.selectbox("Durum", ["onayli", "beklemede", "iptal"], index=0)
        note = c4.text_input("Not", value="")

        occupied = collect_occupied_pcs(conn, d.isoformat(), start_time.strip(), end_time.strip())
        selected_pcs = render_pc_picker("new_pc", occupied, preselected=[])
        st.caption(f"Secilen bilgisayar sayisi: {len(selected_pcs)}")
        submitted = st.form_submit_button("Rezervasyon Ekle", type="primary")

    if submitted:
        if not customer_name.strip():
            st.warning("Musteri adi zorunlu.")
        elif len(selected_pcs) == 0:
            st.warning("En az 1 bilgisayar secmelisin.")
        elif start_time.strip() >= end_time.strip():
            st.warning("Bitis saati baslangictan sonra olmali.")
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
                    int(len(selected_pcs)),
                    ", ".join(selected_pcs),
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
                "table_no": "Bilgisayarlar",
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
            estatus = st.selectbox("Durum", ["onayli", "beklemede", "iptal"], index=["onayli", "beklemede", "iptal"].index(str(row["status"])))
            enote = st.text_input("Not", value="" if pd.isna(row["note"]) else str(row["note"]))

            occupied_edit = collect_occupied_pcs(
                conn, ed.isoformat(), est.strip(), eet.strip(), exclude_id=int(picked_id)
            )
            preselected = normalize_pc_list(None if pd.isna(row["table_no"]) else str(row["table_no"]))
            eselected_pcs = render_pc_picker(f"edit_{picked_id}", occupied_edit, preselected=preselected)
            st.caption(f"Secilen bilgisayar sayisi: {len(eselected_pcs)}")
            b1, b2 = st.columns(2)
            save = b1.form_submit_button("Guncelle", type="primary")
            cancel = b2.form_submit_button("Iptal Olarak Isaretle")

        if save:
            if not ename.strip():
                st.warning("Musteri adi zorunlu.")
            elif len(eselected_pcs) == 0:
                st.warning("En az 1 bilgisayar secmelisin.")
            elif est.strip() >= eet.strip():
                st.warning("Bitis saati baslangictan sonra olmali.")
            else:
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
                        int(len(eselected_pcs)),
                        ", ".join(eselected_pcs),
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
