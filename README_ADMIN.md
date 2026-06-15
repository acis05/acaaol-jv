# ACA-AOL Journal Voucher + Admin Panel

Admin panel:

```text
/admin
```

Railway Variables yang perlu ditambahkan:

```env
ADMIN_EMAIL=admin@aca-aol.id
ADMIN_PASSWORD=password_admin_yang_aman
```

Fitur admin:
- Tambah customer baru
- Generate password SHA256 otomatis
- Ubah nama customer, expired date, max database, notes, dan password
- Suspend / aktifkan customer
- Reset database terdaftar

Scope Accurate untuk JV:

```env
AO_SCOPE=journal_voucher_save journal_voucher_view
AO_JV_SAVE_PATH=/api/journal-voucher/save.do
```
