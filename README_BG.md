# WooCommerce BG Scraper

Скриптът търси публично видими WooCommerce сайтове, които:
1. са WooCommerce / онлайн магазин;
2. са на български;
3. имат IP/хостинг в България;
4. извлича име на сайт, фирма, ЕИК, категория, email и контактна страница.

## Как работи

- Намира кандидати през Common Crawl по WooCommerce URL/asset следи.
- Проверява всеки сайт live.
- Търси WooCommerce маркери: `wp-content/plugins/woocommerce`, `wc-ajax`, `add_to_cart_button`, checkout/cart/product структури.
- Проверява български език чрез `<html lang="bg">`, кирилица и думи като `доставка`, `поръчка`, `количка`, `лв.`.
- Проверява IP геолокация чрез IPinfo token, ако е наличен, иначе fallback към ip-api.com.
- Извлича email-и и фирмени данни от начална, контактна, общи условия, privacy/GDPR и доставка страници.

## Инсталация локално

```bash
pip install -r requirements.txt
python scraper.py --max-sites 100 --indexes 2 --require-hosted-bg
```

За пълно пускане:

```bash
python scraper.py --indexes 5 --limit-per-pattern 50000 --require-hosted-bg --workers 10
```

## GitHub Actions

1. Качи файловете в GitHub repository.
2. Влез в Actions.
3. Избери `WooCommerce BG Scraper`.
4. Run workflow.
5. За тест сложи `max_sites = 100`.
6. За пълно пускане сложи `max_sites = 0`.

## По-добра IP геолокация

Създай безплатен/платен IPinfo token и го добави в GitHub:

`Settings → Secrets and variables → Actions → New repository secret`

Име:

`IPINFO_TOKEN`

## Допълнителни домейни

Можеш да добавиш `seeds.txt` с URL-и/домейни, по един на ред:

```text
https://example.bg
shop.example.com
https://example.com
```

Това е полезно за `.com`, `.eu` или други български магазини, които Common Crawl `.bg` търсенето може да пропусне.

## Изходни файлове

В папка `output/`:

- `woocommerce_bg_final_hosted_bg.xlsx` — финалният файл;
- `woocommerce_bg_final_hosted_bg.csv`;
- `woocommerce_bg_all_checked.xlsx` — всички проверени, включително филтрирани;
- `woocommerce_bg_all_checked.csv`.

## Ограничения

- Не може да гарантира 100% всички сайтове в интернет.
- Cloudflare/CDN може да скрие реалния хостинг. Такива сайтове се маркират като CDN/proxy.
- Някои сайтове крият email чрез изображения, форми или JavaScript.
- Използвай данните само при спазване на GDPR, ePrivacy и правилата за търговска комуникация.
