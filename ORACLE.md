# Oracle Cloud paper kurulumu

Bu servis yalnizca halka acik piyasa verisi kullanir. Borsa API anahtari, hesap
baglantisi ve gercek emir kodu icermez.

Ubuntu tabanli Oracle VM uzerinde Docker ve Compose kurulduktan sonra:

```bash
git clone <GITHUB_REPOSITORY_URL> crypto-trend-bot
cd crypto-trend-bot
docker compose build
docker compose run --rm paper-bot crypto-trend prepare-paper
docker compose up -d
docker compose ps
docker compose logs --tail=100 paper-bot
```

`prepare-paper` son 730 gunu kullanarak konfigurasyonu bir kez secer ve
`paper/config.json` dosyasinda sabitler. Servis calisirken parametreleri yeniden
optimize etmez. Sanal durum `paper/paper.db`, son ozet ise
`reports/paper_status.json` icinde tutulur.

Sunucunun saat dilimi onemli degildir; tum hesaplamalar UTC kullanir. Guvenlik
duvarinda gelen port acmak gerekmez. Servis yalnizca borsanin halka acik HTTPS
veri endpoint'ine disari baglanir.

## Dusuk bellekli VM'de systemd kurulumu

Ubuntu kullanicisinin ev dizinine klonlanan depoda Python sanal ortami
hazirlandiktan ve `prepare-paper` bir kez calistirildiktan sonra:

```bash
sudo cp deploy/crypto-trend-paper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crypto-trend-paper
sudo systemctl status crypto-trend-paper --no-pager
```

Servis gunlukleri `journalctl -u crypto-trend-paper` ile izlenebilir.
