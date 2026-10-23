# MES botas 🐒

Popierinis (paper trading) botas Micro E-mini S&P 500 futures. Prekiauja $10 000 netikrų pinigų su tikromis MES kainomis (Yahoo, ~10 min vėlavimas), 1 kontraktu, long arba short. Veikia GitHub serveryje, todėl kompiuteris gali būti išjungtas. Ką jis daro, rodo beždžionių biuras.

## Kaip veikia

- **GitHub Actions** kas 15 min darbo dienomis paleidžia `run_once.py`. Botas apdoroja naujas žvakes, priima sprendimus ir išsaugo būseną į repozitoriją (`data/`).
- **Šeštadienį** `review.py` išbando visas kandidatų strategijas su paskutinių 60 dienų duomenimis ir pasirenka geriausią, bet tik jei ji buvo pelninga abiejose laikotarpio pusėse. Tai boto „mokymasis“.
- **GitHub Pages** rodo beždžionių biurą (`docs/index.html`), kuris kas minutę skaito `docs/data/status.json`.

## Įjungimas (vieną kartą)

1. Įkelk visus failus į GitHub repozitoriją `mes-bot` (Public).
2. **Settings → Actions → General → Workflow permissions:** pažymėk **Read and write permissions** → Save.
3. **Settings → Pages → Build and deployment:** Source **Deploy from a branch**, Branch **main**, aplankas **/docs** → Save.
4. **Actions** skirtukas → jei prašo, spausk **I understand… enable** → kairėje **MES botas** → **Run workflow**. Pirmas paleidimas tik „įšildo“ botą.
5. Po kelių minučių biuras bus adresu `https://<vartotojas>.github.io/mes-bot/`.

## Taisyklės

- Tik JAV sesijoje (16:30–22:55 LT), pozicijos uždaromos prieš uždarymą, savaitgalį nelaikomos.
- 1 kontraktas, 1 tick slippage, ~$1.24 komisinių, dienos nuostolio limitas -$150.
- Pradinė strategija: grįžimas į vidurkį (z ≥ 3, 5 min žvakės, stop 8 pt).

## Ranka kompiuteryje

```
pip install -r requirements.txt
python backtest.py          # palygina strategijas su tikrais duomenimis
python review.py            # savaitės apžvalga
python run_once.py --sim    # vienas boto žingsnis su simuliacija
```

| Failas | Ką daro |
|---|---|
| `run_once.py` | vienas boto žingsnis (jį leidžia GitHub) |
| `review.py` | savaitės apžvalga ir strategijos pasirinkimas |
| `engine.py` | sprendimai: analitikas, rizika, treideris |
| `config.py` | nustatymai ir kandidatų strategijos |
| `data/trades.csv` | visų sandorių žurnalas |
| `docs/index.html` | beždžionių biuras |
