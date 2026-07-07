# WooCommerce BG Scraper v2

Тази версия поправя основния проблем от v1: вече **не прескача сайтове предварително само защото IP-то не изглежда българско**. Това е важно, защото много реални български магазини са зад Cloudflare/CDN и IP геолокацията не показва реалния origin hosting.

## Какво извежда

В `output/` ще получиш:

1. `01_verified_woocommerce_bg_language.xlsx`  
   Всички потвърдени WooCommerce онлайн магазини на български.

2. `02_confirmed_hosted_in_bg.xlsx`  
   Само потвърдените WooCommerce магазини, чието видимо IP е в България и не изглежда като CDN/proxy.

3. `03_possible_bg_or_cdn.xlsx`  
   Практичен файл за leads: WooCommerce + български език + онлайн магазин, включително сайтове зад CDN/proxy или с неизвестен hosting.

4. `04_verified_no_email_found.xlsx`  
   Валидни магазини, при които email не е намерен.

5. `99_all_checked.xlsx`  
   Всички проверени кандидати, включително филтрираните.

6. `00_candidates.csv`  
   Списък с кандидат домейни преди live проверката.

## GitHub Actions настройки

За пълно пускане:

```text
max_sites = 0
indexes = 6
global_discovery = false
```

За бърз тест:

```text
max_sites = 300
indexes = 3
global_discovery = false
```

Ако искаш да търси и български магазини на `.com`, `.eu`, `.net` и други домейни:

```text
max_sites = 0
indexes = 6
global_discovery = true
```

`global_discovery = true` е по-бавно и по-шумно, но може да намери магазини извън `.bg`.

## Препоръка

Първо гледай файла:

```text
01_verified_woocommerce_bg_language.xlsx
```

След това, ако държиш много строго на хостинг в България, ползвай:

```text
02_confirmed_hosted_in_bg.xlsx
```

Ако целта е lead generation, най-полезен често е:

```text
03_possible_bg_or_cdn.xlsx
```

Защото много магазини са зад Cloudflare и реалният им хостинг не може да се потвърди само по IP.

## По-добра IP проверка

Добави `IPINFO_TOKEN` като GitHub Secret:

`Settings → Secrets and variables → Actions → New repository secret`

Name:

```text
IPINFO_TOKEN
```

Без token скриптът използва fallback услуга, която може да има rate limits.
