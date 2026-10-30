# Gökbörü / Moriarty CLI

## Brezilya numarası

```bash
bash ./moriarty-local phone-audit "+5511912345678" \
  --i-own-this-number \
  --region BR \
  --sources local
```

Ulusal biçim de kullanılabilir:

```bash
bash ./moriarty-local phone-audit "11 91234-5678" \
  --i-own-this-number \
  --region BR \
  --sources local
```

## Kaynakları listele

```bash
bash ./moriarty-local phone-audit "+905xxxxxxxxx" --i-own-this-number --list-sources
```

## Seçili kaynakları çalıştır

```bash
xvfb-run -a bash ./moriarty-local phone-audit "+905xxxxxxxxx" \
  --i-own-this-number \
  --sources local,facebook,whatsapp,cybernews,databreach,reputation \
  --timeout 180
```

## Bütün kaynakları çalıştır ve JSON kaydet

```bash
xvfb-run -a bash ./moriarty-local phone-audit "+905xxxxxxxxx" \
  --i-own-this-number \
  --sources all \
  --timeout 180 \
  --output "./reports/phone-audit.json"
```

## Yalnızca Facebook

```bash
xvfb-run -a bash ./moriarty-local facebook-self-check "+905xxxxxxxxx" \
  --i-own-this-number \
  --timeout 180
```

`xvfb-run -a`, tarayıcı tabanlı kaynakları görünür pencere açmadan çalıştırır.

## E-posta ile sosyal hesap ara

```bash
bash ./moriarty-local email-audit "ornek@example.com" \
  --sources validation,gravatar,github,localpart \
  --format readable
```

`gravatar` ve `github` doğrudan eşleşen kaynaklardır. `localpart`, e-posta yerel parçasını kullanıcı adı olarak dener; sonuçlar doğrulanmamış sinyal olarak işaretlenir. GitHub limitleri için `GITHUB_TOKEN` kullanın:

```bash
GITHUB_TOKEN="..." bash ./moriarty-local email-audit "ornek@example.com" \
  --sources all \
  --output "./reports/email-audit.json"
```

Kaynakları listelemek için:

```bash
bash ./moriarty-local email-audit --list-sources
```
