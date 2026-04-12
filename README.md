# SneakerBaker Desktop

Bu proje SneakerBaker panelini yerelde Flask ile ayağa kaldırır, `cloudflared` quick tunnel başlatır ve linki arayüzde gösterir.

## Tek tık davranışı

Paketlenmiş uygulama açıldığında:

1. Uygun boş portu bulur.
2. Yerel dashboard'u başlatır.
3. Varsayılan tarayıcıda paneli otomatik açar.
4. `cloudflared` tünelini başlatır.
5. Tunnel linkini hem loglarda hem de panel içinde gösterir.

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
python app.py
```

İsterseniz otomatik davranışları kapatabilirsiniz:

```bash
python app.py --no-browser --no-tunnel
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
