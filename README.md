# QR Yoklama Sistemi

Flask + SQLite tabanlı, Railway'de çalışan QR kod yoklama sistemi.

## Özellikler
- 📱 Ortak QR kod + kişisel PIN ile giriş/çıkış
- 🕐 Türkiye saatiyle otomatik kayıt (Europe/Istanbul)
- 📊 Admin paneli: personel yönetimi, tarih filtreli raporlama
- 🖨️ QR kod yazdırma
- 💾 SQLite veritabanı

---

## Railway'de Deploy

### 1. GitHub'a Yükle
```bash
git init
git add .
git commit -m "QR Yoklama ilk versiyon"
git remote add origin https://github.com/KULLANICI/qr-yoklama.git
git push -u origin main
```

### 2. Railway Projesi Oluştur
- https://railway.app → New Project → Deploy from GitHub Repo
- Bu repoyu seç

### 3. Environment Variables Ekle
Railway Dashboard → Variables sekmesi:

| Değişken       | Değer               | Açıklama              |
|----------------|---------------------|-----------------------|
| SECRET_KEY     | güçlü-rastgele-key  | Flask session şifresi |
| ADMIN_PASSWORD | admin-şifreniz      | Admin panel şifresi   |
| DB_PATH        | /data/yoklama.db    | Kalıcı disk yolu      |

### 4. Kalıcı Disk Ekle (ÖNEMLİ!)
Railway Dashboard → Storage → Add Volume → Mount Path: `/data`
> Bu olmadan her deploy'da veriler sıfırlanır!

---

## Kullanım

### Personel İçin
1. Admin panelinden QR kodları yazdır ve ilgili yere as
2. Personel sabah **Giriş QR**'ı tarar → PIN girer → Giriş kaydedilir
3. Personel akşam **Çıkış QR**'ı tarar → PIN girer → Çıkış + süre kaydedilir

### Admin İçin
- `https://SİTENİZ/admin` adresine git
- Admin şifresiyle giriş yap
- **Yoklama** sekmesi: günlük/haftalık/aylık raporlar
- **Personel** sekmesi: personel ekle/sil, PIN değiştir
- **QR Kodlar** sekmesi: QR görüntüle ve yazdır

---

## Varsayılan Kullanıcı
Sistem ilk kurulumda bir test personeli oluşturur:
- **Ad:** Test Personel  
- **PIN:** 1234

Admin panelinden silebilir veya PIN'ini değiştirebilirsiniz.

---

## URL'ler
| URL                  | Açıklama         |
|----------------------|------------------|
| /giris               | Giriş QR sayfası |
| /cikis               | Çıkış QR sayfası |
| /admin               | Admin girişi     |
| /admin/panel         | Admin paneli     |
