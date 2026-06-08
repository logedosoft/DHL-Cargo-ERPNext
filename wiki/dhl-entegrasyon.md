# DHL Kargo Entegrasyonu

---

## 1. Günlük Kullanım — Etiket Nasıl Basılır?

Bir kargoyu DHL ile göndermek istediğinizde yapılması gerekenler:

1. **Satış İrsaliyesi**'ni açın
2. **Gönderim Yöntemi** alanını **"DHL"** yapın
3. Kaydedin ve **Onayla**yın
4. Üstte görünen **Kargo Etiketleri->DHL** butonuna tıklayın
- Sizi **kaç kutu** göndereceğinizi sormak için bir pencere karşılar
- Her kutu için **desi** ve **kg** değerlerini girersiniz
- Sistem arka planda DHL'e siparişi iletir, barkodları alır ve **PDF etiketleri** otomatik olarak satış irsaliyesine ekler

Etiketleri yazdırmak için:
- Satış İrsaliye altındaki **Ekler** bölümünden PDF'leri indirip yazdırmanız yeterlidir
- PDF'leri tekrar oluşturmak isterseniz **DHL Etiket PDF** butonuna tıklayın

---

## 2. Ayarlar — İlk Kurulum

İlk kurulumu bir kez yapmanız yeterlidir. Bundan sonra ayarlara dokunmanıza gerek kalmaz.

### Adım 1: DHL Bilgilerinizi Girin

**Ayarlar > DHL Kargo Ayarları** sayfasını açın ve şu bilgileri doldurun:

| Alan | Nereden Bulunur? |
|------|-------------------|
| Müşteri Numarası | DHL Online Branch giriş kullanıcı adınız |
| Şifre | DHL Online Branch şifreniz |
| Client ID | ApiZone portalındaki uygulamanızın Client ID'si |
| Client Secret | ApiZone portalındaki uygulamanızın Client Secret'ı |

**Test** ortamı için URL: `https://testapi.mngkargo.com.tr`
**Canlı** ortam için URL: `https://api.mngkargo.com.tr`

Doldurduktan sonra **Test Et** butonuna basın. "Bağlantı başarılı" mesajı alırsanız her şey doğru demektir.

### Adım 2: Şehir ve İlçe Listesini Çekin

**Şehir ve İlçeleri Getir** butonuna tıklayın. Bu buton DHL'in tüm Türkiye şehir ve ilçe listesini sisteme yükler.

> Bu işlem 1-2 dakika sürebilir. Arka planda çalışır, ekranda ilerleme çubuğu görürsünüz.

### Adım 3: Diğer Ayarlar (İsteğe Bağlı)

| Alan | Varsayılan | Ne İşe Yarar? |
|------|------------|---------------|
| Ödeme Tipi | Gönderici Öder | Kargoyu kim ödeyecek? |
| Teslim Tipi | Adrese Teslim | Adrese mi, şubeden mi teslim? |
| Varsayılan Telefon | — | Adreste telefon yoksa otomatik kullanılır |
| Varsayılan E-posta | — | Adreste e-posta yoksa otomatik kullanılır |

---

## 3. Adres Doğrulama — Neden Hata Alıyorum?

Sistem, herhangi bir **Adres** kaydettiğinizde otomatik olarak kontrol eder:

- Şehir ismi DHL listesinde var mı?
- İlçe o şehrin altında kayıtlı mı?

Eşleşme bulunamazsa hata alırsınız: *"Şehir DHL Kargo Ayarları'nda eşleştirilmemiş: XXX!"*

**Çözüm:** Önce DHL Kargo Ayarları'ndan **Şehir ve İlçeleri Getir** butonunu çalıştırın. Sonra adresinizi kaydedin.

> Dikkat: Türkçe karakterler otomatik olarak büyük harfe çevrilir (ı→I, ş→Ş, ü→Ü, ğ→Ğ, ç→Ç, ö→Ö). Adresinizde doğru yazdığınızdan emin olun.

---

## 4. Sık Karşılaşılan Sorunlar

### "DHL Kargo" butonu görünmüyor
- Teslimat notu **submit** edilmemiş olabilir
- **Gönderim Yöntemi** "DHL" olarak seçilmemiş olabilir

### "Token süresi doldu" hatası
- JWT token 8 saat geçerli, süresi dolmuş
- **Çözüm:** Ayarlar'daki JWT ve bitiş tarihini temizleyin, **Test Et** butonuna tekrar basın

### Barkod basılamadı / PDF boş
- Dış servis (Labelary) geçici olarak erişilemez olabilir
- **Çözüm:** Birkaç dakika bekleyip tekrar deneyin. Hata devam ederse Error Log'u kontrol edin

### Şehir/İlçe bulunamadı hatası
- **Çözüm:** "Şehir ve İlçeleri Getir" butonunu çalıştırın

### Etiketleri tekrar basmak istiyorum
- **DHL Etiket PDF** butonuna tıklayın — kayıtlı barkodlardan yeni PDF oluşturulur

---

## 5. Teknik Detaylar (Opsiyonel)

> Bu bölüm yöneticiler ve teknik sorumlular içindir. Günlük kullanımda bilinmesi gerekmez.

### Entegrasyon Akışı

```
Kullanıcı butona tıklar
        ↓
    Token Al (8 saat cache'li JWT)
        ↓
    CreateOrder → DHL'e sipariş gönderilir
        ↓
    CreateBarcode → Barkod/ZPL verileri alınır
        ↓
    ZPL → PDF dönüştürme (Labelary API)
        ↓
    PDF'ler teslimat notuna eklenir
```

### Delivery Note Ek Alanları

Kurulum sırasında otomatik eklenir (salt okunur):

| Alan | Açıklama |
|------|----------|
| `dhl_reference_id` | Sipariş referansı (DN adı) |
| `dhl_order_invoice_id` | Sipariş fatura ID |
| `dhl_shipper_branch_code` | Gönderen şube kodu |
| `dhl_barcode_invoice_id` | Barkod fatura ID |
| `dhl_shipment_id` | Gönderi ID |
| `dhl_barcodes` | Kutu başı barkod/ZPL tablosu |

### Şehir/İlçe Senkronizasyonu

- DHL CBS API'sinden çekilir (`getcities` / `getdistricts`)
- Token gerektirmez, sadece `client_id` ve `client_secret` yeterlidir
- Arka planda çalışır (Frappe long queue, 1400sn timeout)
- Mevcut "örnek" değerleri korunarak güncellenir

### Address Validasyon Mekanizması

- `Address` DocType'ı `validate` hook'uyla çalışır
- Ülke `TR` değilse doğrulama yapılmaz
- Şehir/isim DHL listesinde eşleştirilir → bulunamazsa `frappe.throw()` ile durdurulur

### Desteklenen Ödeme ve Teslim Tipleri

**Ödeme Tipleri:**
| Kod | Açıklama |
|-----|----------|
| 1 | Gönderici Öder |
| 2 | Alıcı Öder |
| 3 | Platform Öder |

**Teslim Tipleri:**
| Kod | Açıklama |
|-----|----------|
| 1 | Adrese Teslim |
| 2 | Şubeden Teslim |

### Token Yönetimi

- JWT 8 saat geçerli
- `jwt_expire_date` alanında cache'lenir
- `exp` claim'inden 5 dakika güvenlik payıyla kontrol edilir
- Her API çağrısında önce cache, sonra yeni token alınır

### Kurulum Notları (Teknik)

- App kurulumu sonrası `bench migrate` çalıştırılmalıdır
- `Customer` DocType'ına `dhl_customer_id` alanı eklenir
- `DHL Ödeme Tipi` ve `DHL Teslim Tipi` DocType'ları `after_install` ile seed edilir
- Sales Order submit edildiğinde (`sales_order_creates_recipient` açıksa) alıcı DHL'e kaydedilir
- Detaylı log açılırsa tüm API istek/yanıtları Error Log'a yazılır
