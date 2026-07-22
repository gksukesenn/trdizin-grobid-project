# Versioned migrations

`migration_runner.py`, `schema_migrations` tablosundaki version ve SHA-256
checksum değerlerini kontrol eder. Uygulanmış migration tekrar çalıştırılmaz;
aynı version'ın içeriği sonradan değiştirilirse runner hata verir. Yeni şema
değişiklikleri yeni, additive ve sıralı bir SQL dosyası olarak eklenmelidir.

Migration dosyalarında destructive `DROP TABLE` veya `DROP COLUMN` kullanmayın.
