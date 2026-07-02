# Cara Pakai Login & Lisensi ACA-AOL JV

Saya sudah menambahkan/merapikan sistem login berbasis lisensi untuk pelanggan ACA-AOL JV.

## 1. Halaman untuk pelanggan

Pelanggan membuka halaman utama:

```text
https://domain-anda.com/
```

Pelanggan login memakai email dan password yang Anda daftarkan di Admin Panel.

## 2. Halaman admin untuk mendaftarkan pelanggan

Buka:

```text
https://domain-anda.com/admin
```

Login admin memakai data dari environment variable:

```env
ADMIN_EMAIL=admin@aca-aol.id
ADMIN_PASSWORD=password_admin_anda
```

Jika dijalankan lokal dan belum diubah, default lama di kode adalah:

```text
admin@aca-aol.id / admin123
```

Saran: wajib ubah `ADMIN_PASSWORD` saat deploy produksi.

## 3. Cara mendaftarkan pelanggan baru

Di halaman `/admin`:

1. Isi **Nama PT / Customer**.
2. Isi **Email Login** pelanggan.
3. Isi **Password Login** pelanggan.
4. Isi **Masa Berlaku** dengan format `YYYY-MM-DD`, contoh `2026-12-31`.
5. Isi **Max Database**, contoh `1`, `3`, atau `5`.
6. Klik **Buat Customer**.

Setelah dibuat, pelanggan bisa login di halaman utama menggunakan email dan password tersebut.

## 4. Kuota database pelanggan

Setiap pelanggan punya batas database Accurate sesuai kolom **Max Database**.

Saat pelanggan memilih database Accurate pertama kali, database tersebut otomatis didaftarkan ke lisensi pelanggan. Kalau kuota sudah penuh, pelanggan tidak bisa memilih database baru sampai Anda reset atau naikkan kuotanya.

Di Admin Panel tersedia tombol:

- **Edit**: ubah nama customer, expired, max database, password, dan catatan.
- **Reset DB**: hapus daftar database yang sudah terdaftar untuk pelanggan itu.
- **Suspend/Aktifkan**: nonaktifkan atau aktifkan kembali akun pelanggan.

## 5. File penyimpanan lisensi

Data pelanggan disimpan di:

```text
licenses.json
```

Password tidak disimpan sebagai teks asli, tetapi sebagai hash SHA-256.

## 6. Cara jalan lokal

Install dependency:

```bash
pip install -r requirements.txt
```

Salin `.env.example` menjadi `.env`, lalu isi minimal:

```env
JWT_SECRET=isi_random_panjang_min_32_karakter
SECRET_KEY=isi_random_panjang_min_32_karakter
ADMIN_EMAIL=email_admin_anda
ADMIN_PASSWORD=password_admin_anda
AO_CLIENT_ID=client_id_accurate
AO_CLIENT_SECRET=client_secret_accurate
AO_REDIRECT_URI=http://localhost:5000/oauth/callback
AO_SCOPE=journal_voucher_save journal_voucher_view
AO_JV_SAVE_PATH=/api/journal-voucher/save.do
```

Jalankan:

```bash
python app.py
```

Buka:

```text
http://localhost:5000/admin
```

## 7. Yang sudah saya rapikan di versi ini

- Link Admin ditambahkan dari halaman login utama.
- Endpoint status Accurate, daftar database, dan logout Accurate sekarang wajib membawa token login pelanggan.
- Admin Panel tetap memakai token admin khusus.
- Dokumentasi pemakaian ditambahkan di file ini.
