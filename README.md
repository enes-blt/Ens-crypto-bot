# Crypto Trend Bot

BTCUSDT ve ETHUSDT icin once backtest, sonra paper trading hedefleyen arastirma projesi.
Bu surum gercek emir gondermez ve API anahtari kullanmaz.

## Baslangic

Python 3.11 veya daha yenisi gerekir.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
crypto-trend download --symbol BTCUSDT --days 365
crypto-trend backtest --symbol BTCUSDT
crypto-trend research --symbol BTCUSDT
crypto-trend research-v2 --symbol BTCUSDT
crypto-trend portfolio-v2
crypto-trend research-v3 --symbol BTCUSDT
crypto-trend portfolio-v3
crypto-trend prepare-paper
crypto-trend paper-once
```

Ayni komutlari `ETHUSDT` icin de calistirin. Veri, Binance USD-M Futures'in halka acik
mum endpoint'inden alinir; hesap veya API anahtari gerekmez.

## Strateji v1

- 4 saatlik EMA50/EMA200 ile yon filtresi
- 1 saatlik Donchian(20) kirilimi ile giris
- ADX(14) ile trend gucu filtresi
- ATR(14) tabanli stop ve pozisyon buyuklugu
- Islem basina varsayilan %0,5 risk, en fazla 2x notional kaldirac
- Komisyon ve slippage varsayimlari her giris/cikista uygulanir
- Gerceklesmis perpetual funding oranlari pozisyon yonune gore uygulanir
- Sinyal kapanista uretilir, emir sonraki mumun acilisinda modellenir

## Arastirma modu

`research` komutu trend kirilimi, trend geri cekilmesi ve volatilite kirilimi
ailelerinden 48 konfigurasyonu karsilastirir. Her fold'da yalnizca onceki 730 gun
ile secim yapar ve secilen konfigurasyonu sonraki 180 gunluk gorulmemis veride
sinayarak ilerler. Raporlar `reports/` altina JSON olarak yazilir.

Rapor; net getiri, CAGR, maksimum dusus, Sharpe/Sortino, profit factor, long/short
ayrimi, komisyon, funding, aylik/yillik getiriler ve buy-and-hold benchmark'ini
icerir. Gecmis sonuclar gelecekteki performansi garanti etmez.

`research-v2`, yalnizca long/cash kullanan ve girisleri 4 saatlik mum kapanisinda
degerlendiren daha yavas 48 aday uzerinde ayni walk-forward testi uygular.
`portfolio-v2`, BTC ve ETH stratejilerini ayri egitim verisinde secer; sonraki
gorulmemis donemde iki risk kolunu egitim donemi volatilitesinin tersine gore
agirliklandirir.

`research-v3`, bunlara tamamlanmis gunluk mumlardan hesaplanan EMA rejim filtresi
ve 30 gunluk gerceklesen volatiliteye gore yalnizca riski azaltan pozisyon boyutu
ekler. `portfolio-v3`, egitim donemi BTC/ETH gunluk korelasyonu 0,75 veya daha
yuksekse toplam yatirilan agirligi %70'e indirir ve %30 nakit tamponu tutar.

## Shadow/paper servis

`prepare-paper`, v2 long-only adaylarindan her parite icin son 730 gunde en iyi
risk-duzeltilmis konfigurasyonu bir kez secer ve sabitler. `paper-once` tek bir
veri yenileme ve sanal hesaplama yapar. `paper-daemon` ayni islemi varsayilan
olarak bes dakikada bir tekrarlar. Tum islemler sanaldir; projede borsa API
anahtari veya gercek emir endpoint'i bulunmaz.

Oracle kurulumu icin [ORACLE.md](ORACLE.md) belgesine bakin.

Bu yazilim yatirim tavsiyesi degildir. Canli islemden once farkli piyasa rejimlerinde
walk-forward test ve en az 30 gun paper trading gerekir.
