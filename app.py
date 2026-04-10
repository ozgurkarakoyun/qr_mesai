from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from datetime import datetime, date
import sqlite3
import hashlib
import os
import pytz

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "qr-yoklama-secret-2024")

TURKEY_TZ = pytz.timezone("Europe/Istanbul")
DB_PATH = os.environ.get("DB_PATH", "yoklama.db")

# ── DB SETUP ──────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS personel (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                ad_soyad TEXT    NOT NULL,
                pin_hash TEXT    NOT NULL,
                aktif    INTEGER DEFAULT 1,
                olusturma_tarihi TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS yoklama (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                personel_id   INTEGER NOT NULL,
                tarih         TEXT    NOT NULL,
                giris_saati   TEXT,
                cikis_saati   TEXT,
                giris_ip      TEXT,
                cikis_ip      TEXT,
                giris_uyari   INTEGER DEFAULT 0,
                cikis_uyari   INTEGER DEFAULT 0,
                giris_lat     REAL,
                giris_lng     REAL,
                cikis_lat     REAL,
                cikis_lng     REAL,
                cikis_disari  INTEGER DEFAULT 0,
                FOREIGN KEY (personel_id) REFERENCES personel(id)
            );
        """)
        # Varsayılan admin personeli ekle (PIN: 1234)
        existing = conn.execute("SELECT COUNT(*) FROM personel").fetchone()[0]
        if existing == 0:
            pin_hash = hashlib.sha256("1234".encode()).hexdigest()
            conn.execute(
                "INSERT INTO personel (ad_soyad, pin_hash) VALUES (?, ?)",
                ("Test Personel", pin_hash)
            )
            conn.commit()

# ── HELPERS ───────────────────────────────────────────────────────────────────

def now_turkey():
    return datetime.now(TURKEY_TZ)

# ── KONUM DOĞRULAMA ───────────────────────────────────────────────────────────
import math

# Klinik koordinatları (env ile override edilebilir)
KLINIK_LAT       = float(os.environ.get("KLINIK_LAT",       "40.9838647"))
KLINIK_LNG       = float(os.environ.get("KLINIK_LNG",       "27.5695521"))
KLINIK_YARICAP_M = int(os.environ.get("KLINIK_YARICAP_M",   "100"))  # metre

def haversine_metre(lat1, lng1, lat2, lng2):
    """İki koordinat arasındaki mesafeyi metre cinsinden döndürür."""
    R = 6_371_000
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p)
         * math.sin((lng2 - lng1) * p / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))

def konum_dogrula(lat, lng):
    """Koordinatın klinik yarıçapı içinde olup olmadığını kontrol eder."""
    mesafe = haversine_metre(KLINIK_LAT, KLINIK_LNG, lat, lng)
    return mesafe <= KLINIK_YARICAP_M, round(mesafe)


# Mesai saatleri
# weekday(): 0=Pazartesi … 4=Cuma, 5=Cumartesi, 6=Pazar
MESAI = {
    "hafta_ici": {"giris": (9, 0), "cikis": (18, 0)},   # Pzt-Cuma
    "cumartesi": {"giris": (9, 0), "cikis": (14, 0)},
}
TOLERANS_DK = 60  # 1 saat = 60 dakika

def mesai_kontrol(now, islem):
    """
    Giriş/çıkış saatinin mesai sınırları dışında olup olmadığını kontrol eder.
    Döndürür: (uyari: bool, uyari_mesaj: str | None)
    """
    gün = now.weekday()  # 0=Pzt … 6=Pzr
    saat_dk = now.hour * 60 + now.minute  # günün kaçıncı dakikası

    if gün == 6:  # Pazar
        return True, "⚠️ Bugün Pazar — normal mesai günü değil."

    if gün == 5:  # Cumartesi
        mesai = MESAI["cumartesi"]
    else:
        mesai = MESAI["hafta_ici"]

    if islem == "giris":
        limit_h, limit_m = mesai["giris"]
        erken_sinir = (limit_h * 60 + limit_m) - TOLERANS_DK   # 1 saat öncesi
        if saat_dk < erken_sinir:
            return True, (
                f"⚠️ Mesai başlangıcından {TOLERANS_DK} dakikadan fazla önce giriş yapıyorsunuz. "
                f"Normal giriş saati: {limit_h:02d}:{limit_m:02d}"
            )
    else:  # çıkış
        limit_h, limit_m = mesai["cikis"]
        gec_sinir = (limit_h * 60 + limit_m) + TOLERANS_DK     # 1 saat sonrası
        if saat_dk > gec_sinir:
            return True, (
                f"⚠️ Mesai bitişinden {TOLERANS_DK} dakikadan fazla sonra çıkış yapıyorsunuz. "
                f"Normal çıkış saati: {limit_h:02d}:{limit_m:02d}"
            )

    return False, None

def hash_pin(pin):
    return hashlib.sha256(pin.strip().encode()).hexdigest()

def get_personel_by_pin(pin):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM personel WHERE pin_hash = ? AND aktif = 1",
            (hash_pin(pin),)
        ).fetchone()

def get_or_create_yoklama(personel_id, tarih):
    """Bugünkü yoklama kaydını getir veya oluştur."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM yoklama WHERE personel_id = ? AND tarih = ?",
            (personel_id, tarih)
        ).fetchone()
        if row:
            return dict(row), False
        conn.execute(
            "INSERT INTO yoklama (personel_id, tarih) VALUES (?, ?)",
            (personel_id, tarih)
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM yoklama WHERE personel_id = ? AND tarih = ?",
            (personel_id, tarih)
        ).fetchone()
        return dict(row), True

# ── PERSONEL ROUTES ───────────────────────────────────────────────────────────

@app.route("/giris")
def giris_page():
    return render_template("pin_giris.html", islem="giris")

@app.route("/cikis")
def cikis_page():
    return render_template("pin_giris.html", islem="cikis")

@app.route("/api/giris", methods=["POST"])
def api_giris():
    data = request.get_json()
    pin  = data.get("pin", "").strip()
    lat  = data.get("lat")
    lng  = data.get("lng")

    if not pin:
        return jsonify({"ok": False, "mesaj": "PIN boş olamaz."})

    # --- Konum doğrulama ---
    if lat is None or lng is None:
        return jsonify({"ok": False, "mesaj": "📍 Konum bilgisi alınamadı. Lütfen konum iznini verin ve tekrar deneyin.", "konum_hatasi": True})
    try:
        lat, lng = float(lat), float(lng)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "mesaj": "Geçersiz konum verisi.", "konum_hatasi": True})

    iceride, mesafe = konum_dogrula(lat, lng)
    if not iceride:
        return jsonify({
            "ok": False,
            "mesaj": f"🚫 Kliniğe çok uzaktasınız ({mesafe} m). Giriş yalnızca klinik içinden yapılabilir.",
            "konum_hatasi": True,
            "mesafe": mesafe
        })
    # -----------------------

    personel = get_personel_by_pin(pin)
    if not personel:
        return jsonify({"ok": False, "mesaj": "Hatalı PIN. Lütfen tekrar deneyin."})

    now   = now_turkey()
    tarih = now.strftime("%Y-%m-%d")
    saat  = now.strftime("%H:%M:%S")

    yoklama, yeni = get_or_create_yoklama(personel["id"], tarih)

    if yoklama["giris_saati"]:
        return jsonify({
            "ok": False,
            "mesaj": f"Bugün zaten giriş yaptınız ({yoklama['giris_saati'][:5]})."
        })

    uyari, uyari_mesaj = mesai_kontrol(now, "giris")
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    with get_db() as conn:
        conn.execute(
            "UPDATE yoklama SET giris_saati = ?, giris_ip = ?, giris_uyari = ?, giris_lat = ?, giris_lng = ? WHERE id = ?",
            (saat, ip, 1 if uyari else 0, lat, lng, yoklama["id"])
        )
        conn.commit()

    return jsonify({
        "ok": True,
        "mesaj": f"Günaydın, {personel['ad_soyad']}! Giriş saatiniz: {saat[:5]}",
        "uyari": uyari,
        "uyari_mesaj": uyari_mesaj
    })

@app.route("/api/cikis", methods=["POST"])
def api_cikis():
    data = request.get_json()
    pin  = data.get("pin", "").strip()
    lat  = data.get("lat")
    lng  = data.get("lng")

    if not pin:
        return jsonify({"ok": False, "mesaj": "PIN boş olamaz."})

    # --- Konum doğrulama ---
    if lat is None or lng is None:
        return jsonify({"ok": False, "mesaj": "📍 Konum bilgisi alınamadı. Lütfen konum iznini verin ve tekrar deneyin.", "konum_hatasi": True})
    try:
        lat, lng = float(lat), float(lng)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "mesaj": "Geçersiz konum verisi.", "konum_hatasi": True})

    iceride, mesafe = konum_dogrula(lat, lng)
    cikis_disari = 0 if iceride else 1
    # -----------------------

    personel = get_personel_by_pin(pin)
    if not personel:
        return jsonify({"ok": False, "mesaj": "Hatalı PIN. Lütfen tekrar deneyin."})

    now   = now_turkey()
    tarih = now.strftime("%Y-%m-%d")
    saat  = now.strftime("%H:%M:%S")

    yoklama, _ = get_or_create_yoklama(personel["id"], tarih)

    if not yoklama["giris_saati"]:
        return jsonify({"ok": False, "mesaj": "Bugün giriş kaydınız bulunamadı."})

    if yoklama["cikis_saati"]:
        return jsonify({
            "ok": False,
            "mesaj": f"Bugün zaten çıkış yaptınız ({yoklama['cikis_saati'][:5]})."
        })

    uyari, uyari_mesaj = mesai_kontrol(now, "cikis")

    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    with get_db() as conn:
        conn.execute(
            "UPDATE yoklama SET cikis_saati = ?, cikis_ip = ?, cikis_uyari = ?, cikis_lat = ?, cikis_lng = ?, cikis_disari = ? WHERE id = ?",
            (saat, ip, 1 if (uyari or cikis_disari) else 0, lat, lng, cikis_disari, yoklama["id"])
        )
        conn.commit()

    # Çalışma süresi hesapla
    giris_dt  = datetime.strptime(f"{tarih} {yoklama['giris_saati']}", "%Y-%m-%d %H:%M:%S")
    cikis_dt  = datetime.strptime(f"{tarih} {saat}", "%Y-%m-%d %H:%M:%S")
    sure_dk   = int((cikis_dt - giris_dt).total_seconds() / 60)
    sure_text = f"{sure_dk // 60} saat {sure_dk % 60} dakika"

    # Klinik dışı çıkış uyarısı
    if cikis_disari:
        uyari = True
        konum_uyari = f"⚠️ Klinik dışında çıkış yapıldı ({mesafe} m uzakta). Kayıt 'erken/dışarıda çıkış' olarak işaretlendi."
        if uyari_mesaj:
            uyari_mesaj = konum_uyari + " | " + uyari_mesaj
        else:
            uyari_mesaj = konum_uyari

    return jsonify({
        "ok": True,
        "mesaj": f"İyi günler, {personel['ad_soyad']}! Çıkış saatiniz: {saat[:5]} | Çalışma süresi: {sure_text}",
        "uyari": uyari,
        "uyari_mesaj": uyari_mesaj
    })

# ── ADMIN ROUTES ──────────────────────────────────────────────────────────────

ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "admin123")

@app.route("/admin")
def admin_login_page():
    if session.get("admin"):
        return redirect(url_for("admin_panel"))
    return render_template("admin_login.html")

@app.route("/admin/login", methods=["POST"])
def admin_login():
    if request.form.get("sifre") == ADMIN_PASS:
        session["admin"] = True
        return redirect(url_for("admin_panel"))
    return render_template("admin_login.html", hata="Hatalı şifre!")

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login_page"))

@app.route("/admin/panel")
def admin_panel():
    if not session.get("admin"):
        return redirect(url_for("admin_login_page"))
    return render_template("admin_panel.html")

@app.route("/api/admin/personeller")
def api_personeller():
    if not session.get("admin"):
        return jsonify({"hata": "Yetkisiz"}), 401
    with get_db() as conn:
        rows = conn.execute("SELECT id, ad_soyad, aktif, olusturma_tarihi FROM personel ORDER BY ad_soyad").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/admin/personel_ekle", methods=["POST"])
def api_personel_ekle():
    if not session.get("admin"):
        return jsonify({"hata": "Yetkisiz"}), 401
    data = request.get_json()
    ad   = data.get("ad_soyad", "").strip()
    pin  = data.get("pin", "").strip()
    if not ad or not pin:
        return jsonify({"ok": False, "mesaj": "Ad ve PIN zorunludur."})
    if len(pin) < 4:
        return jsonify({"ok": False, "mesaj": "PIN en az 4 haneli olmalıdır."})
    with get_db() as conn:
        conn.execute(
            "INSERT INTO personel (ad_soyad, pin_hash) VALUES (?, ?)",
            (ad, hash_pin(pin))
        )
        conn.commit()
    return jsonify({"ok": True, "mesaj": f"{ad} eklendi."})

@app.route("/api/admin/personel_sil/<int:pid>", methods=["POST"])
def api_personel_sil(pid):
    if not session.get("admin"):
        return jsonify({"hata": "Yetkisiz"}), 401
    with get_db() as conn:
        conn.execute("UPDATE personel SET aktif = 0 WHERE id = ?", (pid,))
        conn.commit()
    return jsonify({"ok": True})

@app.route("/api/admin/pin_degistir/<int:pid>", methods=["POST"])
def api_pin_degistir(pid):
    if not session.get("admin"):
        return jsonify({"hata": "Yetkisiz"}), 401
    data    = request.get_json()
    yeni_pin = data.get("pin", "").strip()
    if len(yeni_pin) < 4:
        return jsonify({"ok": False, "mesaj": "PIN en az 4 haneli olmalıdır."})
    with get_db() as conn:
        conn.execute("UPDATE personel SET pin_hash = ? WHERE id = ?", (hash_pin(yeni_pin), pid))
        conn.commit()
    return jsonify({"ok": True, "mesaj": "PIN güncellendi."})

@app.route("/api/admin/yoklamalar")
def api_yoklamalar():
    if not session.get("admin"):
        return jsonify({"hata": "Yetkisiz"}), 401
    baslangic = request.args.get("baslangic", date.today().strftime("%Y-%m-%d"))
    bitis     = request.args.get("bitis",     date.today().strftime("%Y-%m-%d"))
    with get_db() as conn:
        rows = conn.execute("""
            SELECT y.tarih, p.ad_soyad,
                   y.giris_saati, y.cikis_saati,
                   y.giris_uyari, y.cikis_uyari
            FROM yoklama y
            JOIN personel p ON p.id = y.personel_id
            WHERE y.tarih BETWEEN ? AND ?
            ORDER BY y.tarih DESC, p.ad_soyad
        """, (baslangic, bitis)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/admin/qr_urls")
def api_qr_urls():
    if not session.get("admin"):
        return jsonify({"hata": "Yetkisiz"}), 401
    base = request.host_url.rstrip("/")
    return jsonify({
        "giris_url": f"{base}/giris",
        "cikis_url": f"{base}/cikis"
    })

@app.route("/api/admin/konum_ayar")
def api_konum_ayar_get():
    if not session.get("admin"):
        return jsonify({"hata": "Yetkisiz"}), 401
    return jsonify({
        "lat": KLINIK_LAT,
        "lng": KLINIK_LNG,
        "yaricap": KLINIK_YARICAP_M
    })

@app.route("/api/admin/konum_ayar", methods=["POST"])
def api_konum_ayar_set():
    if not session.get("admin"):
        return jsonify({"hata": "Yetkisiz"}), 401
    global KLINIK_LAT, KLINIK_LNG, KLINIK_YARICAP_M
    data = request.get_json()
    try:
        KLINIK_LAT       = float(data["lat"])
        KLINIK_LNG       = float(data["lng"])
        KLINIK_YARICAP_M = int(data["yaricap"])
        return jsonify({"ok": True, "mesaj": f"Konum güncellendi. Yarıçap: {KLINIK_YARICAP_M} m"})
    except Exception as e:
        return jsonify({"ok": False, "mesaj": str(e)})

# ── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
