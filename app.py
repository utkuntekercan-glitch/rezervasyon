import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
import os
import hashlib

import pandas as pd
import streamlit as st
try:
    import psycopg
except Exception:
    psycopg = None
try:
    import psycopg2
except Exception:
    psycopg2 = None

st.set_page_config(page_title="Old School Rezervasyon", layout="wide")
st.markdown(
    """
    <style>
    .pc-legend-chip {
      display:inline-block;
      padding:4px 10px;
      border-radius:999px;
      font-size:12px;
      font-weight:700;
      margin-right:8px;
      margin-bottom:6px;
      border:1px solid transparent;
    }
    .pc-free { background:#ecfdf5; color:#065f46; border-color:#a7f3d0; }
    .pc-used { background:#fef2f2; color:#991b1b; border-color:#fecaca; }
    .pc-picked { background:#eff6ff; color:#1e3a8a; border-color:#bfdbfe; }
    .pc-area-title {
      font-weight:800;
      font-size:15px;
      margin-bottom:2px;
    }
    .pc-area-sub {
      color:#4b5563;
      font-size:12px;
      margin-bottom:8px;
    }
    .pc-grid div[data-testid="stCheckbox"] {
      margin-bottom: 0.18rem;
    }
    .pc-grid div[data-testid="stCheckbox"] label {
      width: 100%;
      border-radius: 10px;
      border: 1px solid #a7f3d0;
      background: #ecfdf5;
      padding: 8px 6px;
      display: flex;
      justify-content: center;
      align-items: center;
      transition: all 0.15s ease;
      min-height: 44px;
      cursor: pointer;
    }
    .pc-grid div[data-testid="stCheckbox"] label:hover {
      transform: translateY(-1px);
      box-shadow: 0 2px 10px rgba(0,0,0,0.06);
    }
    .pc-grid div[data-testid="stCheckbox"] label p {
      margin: 0;
      width: 100%;
      text-align: center;
      font-weight: 700;
      font-size: 12px;
      color: #065f46;
    }
    .pc-grid div[data-testid="stCheckbox"]:has(input:checked) label {
      background: #eff6ff;
      border-color: #93c5fd;
    }
    .pc-grid div[data-testid="stCheckbox"]:has(input:checked) label p {
      color: #1e3a8a;
    }
    .pc-grid div[data-testid="stCheckbox"]:has(input:disabled) label {
      background: #fef2f2;
      border-color: #fecaca;
      cursor: not-allowed;
      opacity: 0.95;
    }
    .pc-grid div[data-testid="stCheckbox"]:has(input:disabled) label p {
      color: #991b1b;
      text-decoration: line-through;
    }
    .pc-grid div[data-testid="stCheckbox"] input[type="checkbox"] {
      display: none;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

DB_PATH = Path("oldschool_reservation.db")
DATABASE_URL = str(st.secrets.get("DATABASE_URL", os.getenv("DATABASE_URL", ""))).strip()
APP_USER = str(st.secrets.get("APP_USER", os.getenv("APP_USER", "admin"))).strip()
APP_PASSWORD = str(st.secrets.get("APP_PASSWORD", os.getenv("APP_PASSWORD", "123456")))
UNKNOWN_END_LABEL = "belirsiz"
AREA_LAYOUT = [
    ("Yellow Area", "Y", 32),
    ("EF Area", "EF", 10),
    ("Red Area", "R", 10),
    ("VIP", "VIP", 5),
    ("Blue Area", "B", 10),
]


class DBConn:
    def __init__(self, driver: str, raw_conn):
        self.driver = driver
        self._conn = raw_conn

    def _sql(self, q: str) -> str:
        if self.driver == "postgres":
            return q.replace("?", "%s")
        return q

    def execute(self, q: str, params=()):
        cur = self._conn.cursor()
        cur.execute(self._sql(q), tuple(params))
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_conn():
    if DATABASE_URL:
        if psycopg is not None:
            if "sslmode=" in DATABASE_URL:
                raw = psycopg.connect(DATABASE_URL)
            else:
                raw = psycopg.connect(DATABASE_URL, sslmode="require")
        elif psycopg2 is not None:
            if "sslmode=" in DATABASE_URL:
                raw = psycopg2.connect(DATABASE_URL)
            else:
                raw = psycopg2.connect(DATABASE_URL, sslmode="require")
        else:
            raise RuntimeError("Postgres driver bulunamadi. requirements'e psycopg[binary] veya psycopg2-binary ekleyin.")
        raw.autocommit = False
        return DBConn("postgres", raw)

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return DBConn("sqlite", conn)


def hash_password(raw: str) -> str:
    return hashlib.sha256(str(raw).encode("utf-8")).hexdigest()


def init_db(conn: DBConn):
    id_col = "BIGSERIAL PRIMARY KEY" if conn.driver == "postgres" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS reservation (
            id {id_col},
            d TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            phone TEXT,
            people_count INTEGER NOT NULL DEFAULT 1,
            table_no TEXT,
            status TEXT NOT NULL DEFAULT 'onayli',
            note TEXT,
            created_at TEXT NOT NULL,
            created_by TEXT
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reservation_d ON reservation(d);")

    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS app_user (
            id {id_col},
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL
        );
        """
    )

    has_created_by = False
    if conn.driver == "postgres":
        row = conn.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'reservation'
              AND column_name = 'created_by'
            """
        ).fetchone()
        has_created_by = row is not None
    else:
        cols = conn.execute("PRAGMA table_info(reservation);").fetchall()
        has_created_by = any(str(c[1]).lower() == "created_by" for c in cols)

    if not has_created_by:
        conn.execute("ALTER TABLE reservation ADD COLUMN created_by TEXT;")

    admin_exists = conn.execute("SELECT id FROM app_user WHERE username=?", (APP_USER,)).fetchone()
    if not admin_exists:
        conn.execute(
            "INSERT INTO app_user(username, password_hash, role, created_at) VALUES(?,?,?,?)",
            (
                APP_USER,
                hash_password(APP_PASSWORD),
                "admin",
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    conn.commit()


def df_query(conn, q, params=()):
    cur = conn.execute(q, params)
    rows = cur.fetchall()
    cols = [c[0] for c in cur.description] if cur.description else []
    return pd.DataFrame(rows, columns=cols)


def col_name(df: pd.DataFrame, preferred: str) -> str | None:
    if preferred in df.columns:
        return preferred
    low = preferred.lower()
    for c in df.columns:
        if str(c).lower() == low:
            return c
    return None


def status_badge(s: str) -> str:
    s = str(s).lower()
    if s == "onayli":
        return "🟢 Onayli"
    if s == "beklemede":
        return "🟡 Beklemede"
    if s == "iptal":
        return "🔴 Iptal"
    return s


def check_login(conn: DBConn) -> bool:
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        if "username" not in st.session_state:
            st.session_state.username = APP_USER
        if "role" not in st.session_state:
            st.session_state.role = "admin"
        return True

    st.title("Old School Rezervasyon Yonetimi")
    st.subheader("Giris Yap")
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Kullanici Adi")
        password = st.text_input("Sifre", type="password")
        submitted = st.form_submit_button("Giris", type="primary")

    st.caption("Varsayilan kullanici: admin | Varsayilan parola: 123456")

    if submitted:
        row = conn.execute(
            "SELECT username, password_hash, role FROM app_user WHERE username=?",
            (username.strip(),),
        ).fetchone()
        if row and hash_password(password) == str(row[1]):
            st.session_state.authenticated = True
            st.session_state.username = str(row[0])
            st.session_state.role = str(row[2]).lower()
            st.rerun()
        else:
            st.error("Hatali kullanici adi veya sifre")
    return False


def normalize_pc_list(raw: str | None) -> list[str]:
    if raw is None:
        return []
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    # Backward compatibility for old single text values
    if len(parts) == 1 and "-" not in parts[0]:
        return parts
    return sorted(parts)


def parse_hhmm(t: str) -> tuple[int, int] | None:
    s = str(t).strip()
    if len(s) != 5 or s[2] != ":":
        return None
    try:
        hh = int(s[:2])
        mm = int(s[3:])
    except Exception:
        return None
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        return None
    return hh, mm


def reservation_bounds(d_str: str, start_time: str, end_time: str):
    d0 = date.fromisoformat(str(d_str))
    st = parse_hhmm(start_time)
    if st is None:
        return None
    start_dt = datetime(d0.year, d0.month, d0.day, st[0], st[1])
    if str(end_time).strip().lower() == UNKNOWN_END_LABEL:
        # Unknown end-time blocks this machine for up to 24 hours from start.
        end_dt = start_dt + timedelta(days=1)
        return start_dt, end_dt
    et = parse_hhmm(end_time)
    if et is None:
        return None
    end_dt = datetime(d0.year, d0.month, d0.day, et[0], et[1])
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return start_dt, end_dt


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def collect_occupied_pcs(conn: DBConn, d_str: str, start_time: str, end_time: str, exclude_id: int | None = None) -> set[str]:
    cand = reservation_bounds(d_str, start_time, end_time)
    if cand is None:
        return set()
    cand_start, cand_end = cand
    d0 = date.fromisoformat(str(d_str))
    d_prev = (d0 - timedelta(days=1)).isoformat()
    d_next = (d0 + timedelta(days=1)).isoformat()

    q = """
        SELECT id, d, start_time, end_time, table_no
        FROM reservation
        WHERE d IN (?, ?, ?)
          AND status != 'iptal'
    """
    params = [d_prev, d_str, d_next]
    if exclude_id is not None:
        q += " AND id != ?"
        params.append(int(exclude_id))

    rows = conn.execute(q, tuple(params)).fetchall()
    occ: set[str] = set()
    for _, rd, rst, ret, pcs in rows:
        rb = reservation_bounds(str(rd), str(rst), str(ret))
        if rb is None:
            continue
        r_start, r_end = rb
        if overlaps(cand_start, cand_end, r_start, r_end):
            for p in normalize_pc_list(pcs):
                occ.add(p)
    return occ


def render_pc_picker(key_prefix: str, occupied: set[str], preselected: list[str] | None = None) -> list[str]:
    preselected = preselected or []
    selected: list[str] = []
    st.markdown("#### Bilgisayar Secimi")
    st.markdown("🟩 Bos   |   🟥 Dolu (kilitli)   |   🟦 Secili")
    st.caption("Rezervasyon icin en az 1 bilgisayar sec.")

    for area_name, area_code, count in AREA_LAYOUT:
        area_pc_ids = [f"{area_code}-{i:02d}" for i in range(1, count + 1)]
        area_occ = sum(1 for pc in area_pc_ids if pc in occupied and pc not in preselected)

        with st.container(border=True):
            st.markdown(f"<div class='pc-area-title'>{area_name}</div>", unsafe_allow_html=True)
            st.markdown(
                f"<div class='pc-area-sub'>Toplam: {count} | Dolu: {area_occ} | Musait: {count - area_occ}</div>",
                unsafe_allow_html=True,
            )
            cols = st.columns(6)
            for i in range(1, count + 1):
                pc_id = f"{area_code}-{i:02d}"
                default_val = pc_id in preselected
                disabled = (pc_id in occupied) and (pc_id not in preselected)
                if disabled:
                    label = f"🟥 {pc_id}"
                elif default_val:
                    label = f"🟦 {pc_id}"
                else:
                    label = f"🟩 {pc_id}"
                col = cols[(i - 1) % 6]
                with col:
                    val = st.checkbox(
                        label,
                        value=default_val,
                        key=f"{key_prefix}_{pc_id}",
                        disabled=disabled,
                    )
                if val:
                    selected.append(pc_id)
        st.write("")
    return sorted(selected)


conn = get_conn()
init_db(conn)

if not check_login(conn):
    st.stop()

st.title("Old School Rezervasyon Yonetimi")

today = date.today()
MENU_OPTIONS = ["Dashboard", "Yeni Rezervasyon", "Rezervasyon Listesi"]
if str(st.session_state.get("role", "")).lower() == "admin":
    MENU_OPTIONS.append("Kullanici Yonetimi")

if "page_ui" not in st.session_state:
    st.session_state.page_ui = "Dashboard"
if st.session_state.page_ui not in MENU_OPTIONS:
    st.session_state.page_ui = "Dashboard"

with st.sidebar:
    current_page = st.session_state.get("page_ui", "Dashboard")
    page_pick = st.radio(
        "Menu",
        MENU_OPTIONS,
        index=MENU_OPTIONS.index(current_page) if current_page in MENU_OPTIONS else 0,
    )
    if page_pick != current_page:
        st.session_state.page_ui = page_pick
    selected_day = st.date_input("Tarih", value=today)

page = st.session_state.get("page_ui", "Dashboard")


if page == "Dashboard":
    st.subheader(f"{selected_day.isoformat()} Ozeti")
    if st.button("Rezervasyon Ekle", type="primary"):
        st.session_state.page_ui = "Yeni Rezervasyon"
        st.rerun()

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
        SELECT id, d AS "Tarih", start_time AS "Baslangic", end_time AS "Bitis",
               customer_name AS "Musteri", phone AS "Telefon", people_count AS "Kisi",
               table_no AS "Bilgisayarlar", status AS "Durum", note AS "Notlar",
               COALESCE(created_by, '-') AS "Olusturan"
        FROM reservation
        WHERE d = ?
        ORDER BY start_time
        """,
        (selected_day.isoformat(),),
    )
    if len(day_list):
        durum_col = col_name(day_list, "Durum")
        if durum_col:
            day_list[durum_col] = day_list[durum_col].apply(status_badge)
        st.dataframe(day_list, use_container_width=True, hide_index=True)

        id_col = col_name(day_list, "id")
        tarih_col = col_name(day_list, "Tarih")
        bas_col = col_name(day_list, "Baslangic")
        bit_col = col_name(day_list, "Bitis")
        musteri_col = col_name(day_list, "Musteri")
        pcs_col = col_name(day_list, "Bilgisayarlar")
        durum_col = col_name(day_list, "Durum")
        olusturan_col = col_name(day_list, "Olusturan")

        st.markdown("### Düzenle")
        for _, r in day_list.iterrows():
            rid = int(r[id_col]) if id_col else None
            if rid is None:
                continue
            with st.container(border=True):
                top_left, top_right = st.columns([6.8, 2.2], vertical_alignment="center")
                with top_left:
                    st.markdown(
                        f"**{str(r[musteri_col]) if musteri_col else '-'}**  \n"
                        f"Saat: {str(r[bas_col]) if bas_col else '-'} - {str(r[bit_col]) if bit_col else '-'}  |  "
                        f"PC: {str(r[pcs_col]) if pcs_col else '-'}  |  "
                        f"{str(r[durum_col]) if durum_col else '-'}  |  "
                        f"Olusturan: {str(r[olusturan_col]) if olusturan_col else '-'}"
                    )
                with top_right:
                    edit_col, del_col = st.columns(2)
                    with edit_col:
                        if st.button("Duzenle", key=f"dash_edit_{rid}", use_container_width=True):
                            st.session_state.page_ui = "Rezervasyon Listesi"
                            st.session_state.edit_reservation_id = rid
                            st.rerun()
                    with del_col:
                        if st.button("Sil", key=f"dash_delete_{rid}", use_container_width=True, type="secondary"):
                            st.session_state[f"confirm_delete_{rid}"] = True

                if st.session_state.get(f"confirm_delete_{rid}", False):
                    st.warning("Bu rezervasyon silinsin mi?")
                    c_yes, c_no = st.columns(2)
                    with c_yes:
                        if st.button("Evet, Sil", key=f"dash_delete_yes_{rid}", use_container_width=True, type="primary"):
                            conn.execute("DELETE FROM reservation WHERE id=?", (rid,))
                            conn.commit()
                            st.session_state.pop(f"confirm_delete_{rid}", None)
                            st.success("Rezervasyon silindi.")
                            st.rerun()
                    with c_no:
                        if st.button("Vazgeç", key=f"dash_delete_no_{rid}", use_container_width=True):
                            st.session_state.pop(f"confirm_delete_{rid}", None)
                            st.rerun()
    else:
        st.info("Bu tarih icin rezervasyon yok.")

elif page == "Yeni Rezervasyon":
    st.subheader("Yeni Rezervasyon")
    st.caption("Sabahlama icin varsayilan saatler: 22:00 - 07:00 (ertesi gun).")
    with st.form("create_reservation"):
        d = st.date_input("Tarih", value=selected_day)
        c1, c2 = st.columns(2)
        start_time = c1.text_input("Baslangic (HH:MM)", value="22:00")
        end_unknown = c2.checkbox("Bitis belirsiz", value=False)
        end_time = c2.text_input("Bitis (HH:MM)", value="07:00", disabled=end_unknown)
        final_end_time = UNKNOWN_END_LABEL if end_unknown else end_time.strip()
        customer_name = st.text_input("Musteri Adi", value="")
        phone = st.text_input("Telefon", value="")
        c3, c4 = st.columns(2)
        status = c3.selectbox("Durum", ["onayli", "beklemede", "iptal"], index=0)
        note = c4.text_input("Not", value="")

        occupied = collect_occupied_pcs(conn, d.isoformat(), start_time.strip(), final_end_time)
        selected_pcs = render_pc_picker("new_pc", occupied, preselected=[])
        st.caption(f"Secilen bilgisayar sayisi: {len(selected_pcs)}")
        submitted = st.form_submit_button("Rezervasyon Ekle", type="primary")

    if submitted:
        if not customer_name.strip():
            st.warning("Musteri adi zorunlu.")
        elif len(selected_pcs) == 0:
            st.warning("En az 1 bilgisayar secmelisin.")
        elif reservation_bounds(d.isoformat(), start_time.strip(), final_end_time) is None:
            st.warning("Saat formati hatali. HH:MM (ornek 22:00) gir ya da bitisi belirsiz sec.")
        else:
            conn.execute(
                """
                INSERT INTO reservation(
                    d, start_time, end_time, customer_name, phone, people_count, table_no, status, note, created_at, created_by
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    d.isoformat(),
                    start_time.strip(),
                    final_end_time,
                    customer_name.strip(),
                    phone.strip() or None,
                    int(len(selected_pcs)),
                    ", ".join(selected_pcs),
                    status,
                    note.strip() or None,
                    datetime.now().isoformat(timespec="seconds"),
                    str(st.session_state.get("username", "")).strip() or None,
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
        SELECT id, d, start_time, end_time, customer_name, phone, people_count, table_no, status, note, created_by
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
                "created_by": "Olusturan",
            }
        )
        show["Durum"] = show["Durum"].apply(status_badge)
        st.caption(f"Kayit: {len(show)}")
        st.dataframe(show, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("### Kayit Duzenle / Iptal")
        opts = filtered["id"].tolist()
        desired = st.session_state.pop("edit_reservation_id", None)
        idx = opts.index(desired) if desired in opts else 0
        picked_id = st.selectbox("Rezervasyon Sec", opts, index=idx)
        row = filtered.loc[filtered["id"] == picked_id].iloc[0]
        with st.form("edit_reservation"):
            ed = st.date_input("Tarih", value=date.fromisoformat(str(row["d"])))
            c1, c2 = st.columns(2)
            est = c1.text_input("Baslangic (HH:MM)", value=str(row["start_time"]))
            row_end_time = "" if pd.isna(row["end_time"]) else str(row["end_time"])
            end_unknown_edit = c2.checkbox(
                "Bitis belirsiz",
                value=row_end_time.strip().lower() == UNKNOWN_END_LABEL,
            )
            eet = c2.text_input(
                "Bitis (HH:MM)",
                value="07:00" if row_end_time.strip().lower() == UNKNOWN_END_LABEL else row_end_time,
                disabled=end_unknown_edit,
            )
            final_edit_end = UNKNOWN_END_LABEL if end_unknown_edit else eet.strip()
            ename = st.text_input("Musteri Adi", value=str(row["customer_name"]))
            ephone = st.text_input("Telefon", value="" if pd.isna(row["phone"]) else str(row["phone"]))
            estatus = st.selectbox("Durum", ["onayli", "beklemede", "iptal"], index=["onayli", "beklemede", "iptal"].index(str(row["status"])))
            enote = st.text_input("Not", value="" if pd.isna(row["note"]) else str(row["note"]))

            occupied_edit = collect_occupied_pcs(
                conn, ed.isoformat(), est.strip(), final_edit_end, exclude_id=int(picked_id)
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
            elif reservation_bounds(ed.isoformat(), est.strip(), final_edit_end) is None:
                st.warning("Saat formati hatali. HH:MM (ornek 22:00) gir ya da bitisi belirsiz sec.")
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
                        final_edit_end,
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

elif page == "Kullanici Yonetimi":
    if str(st.session_state.get("role", "")).lower() != "admin":
        st.error("Bu sayfaya sadece admin erisebilir.")
    else:
        st.subheader("Kullanici Yonetimi")
        users = df_query(
            conn,
            """
            SELECT username AS "Kullanici", role AS "Rol", created_at AS "Olusturulma"
            FROM app_user
            ORDER BY username
            """,
        )
        st.dataframe(users, use_container_width=True, hide_index=True)

        st.markdown("### Yeni Kullanici Olustur")
        with st.form("create_user_form"):
            new_username = st.text_input("Kullanici Adi")
            new_password = st.text_input("Gecici Sifre", type="password")
            new_role = st.selectbox("Rol", ["user", "admin"], index=0)
            create_user = st.form_submit_button("Kullanici Olustur", type="primary")

        if create_user:
            u = new_username.strip()
            p = new_password.strip()
            if len(u) < 3:
                st.warning("Kullanici adi en az 3 karakter olmali.")
            elif len(p) < 6:
                st.warning("Sifre en az 6 karakter olmali.")
            else:
                exists = conn.execute("SELECT id FROM app_user WHERE username=?", (u,)).fetchone()
                if exists:
                    st.warning("Bu kullanici adi zaten var.")
                else:
                    conn.execute(
                        "INSERT INTO app_user(username, password_hash, role, created_at) VALUES(?,?,?,?)",
                        (
                            u,
                            hash_password(p),
                            new_role,
                            datetime.now().isoformat(timespec="seconds"),
                        ),
                    )
                    conn.commit()
                    st.success(f"Kullanici olusturuldu: {u}")
                    st.rerun()
