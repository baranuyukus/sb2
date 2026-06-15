# SneakerBaker Desktop

Bu proje SneakerBaker panelini yerelde Flask ile ayağa kaldırır, `cloudflared` quick tunnel başlatır ve linki arayüzde gösterir.

## Tek tık davranışı

Paketlenmiş uygulama açıldığında:

1. Önce masaüstü launcher açılır.
2. Kullanıcı profil seçer ya da yeni profil oluşturur.
3. Seçilen profil için uygun boş port bulunur.
4. Yerel dashboard başlatılır.
5. Varsayılan tarayıcıda panel otomatik açılır.
6. `cloudflared` tüneli başlatılır.
7. Tunnel linki hem loglarda hem de panel içinde gösterilir.

## Profil mantığı

- Her profil kendi state, cookie, min fiyat, ayar ve tunnel runtime alanına sahiptir.
- Aynı anda birden fazla farklı profil çalıştırılabilir.
- Aynı profil ikinci kez başlatılmak istenirse mevcut local panel açılır.

## Kurulumsuz paketler

GitHub Actions workflow'u macOS ve Windows için şu bileşenleri paketler:

- Python runtime
- Uygulama kodu
- `cloudflared`
- Chrome for Testing
- Chromedriver

Bu sayede hedef cihazda ayrıca Python, `cloudflared` ya da Chrome kurulumu gerekmemesi hedeflenir.

## Yerel geliştirme

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python launcher.py
```

Doğrudan dashboard server çalıştırmak isterseniz:

```bash
python launcher.py --app-server --profile profile-1 --port 5050 --no-tunnel
```

## Desktop build

Önce runtime assetlerini hazırlayın:

```bash
python scripts/prepare_runtime_assets.py
```

Sonra PyInstaller build alın:

```bash
python scripts/build_desktop.py
```

## GitHub Actions

Workflow dosyası: `.github/workflows/build-desktop.yml`

Çalıştığında:

- `SneakerBaker-macos-arm64.zip`
- `SneakerBaker-windows-x64.zip`

artifact'lerini üretir.

## Not

GitHub üzerinden indirilen macOS ve Windows paketleri imzasızdır. Bu yüzden Apple Gatekeeper ve Windows SmartScreen ilk açılışta uyarı gösterebilir. Gerçek anlamda tamamen sürtünmesiz tek tık dağıtım için ayrıca kod imzalama ve macOS notarization gerekir.
