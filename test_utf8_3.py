import urllib.request

url = "https://raw.githubusercontent.com/kucukasker718-bot/ankavm/main/ankavm/frontend/templates/setup.html"
req = urllib.request.urlopen(url)
raw = req.read()
if raw.startswith(b'\xef\xbb\xbf'):
    raw = raw[3:]
s = raw.decode('utf-8')
for i, ch in enumerate(s):
    try:
        ch.encode('cp1252')
    except Exception as e:
        print(f"Failed at pos {i}: {repr(ch)}")
        break
