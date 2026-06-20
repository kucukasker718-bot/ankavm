import urllib.request

url = "https://raw.githubusercontent.com/kucukasker718-bot/ankavm/main/ankavm/frontend/templates/setup.html"
req = urllib.request.urlopen(url)
raw = req.read()

try:
    s = raw.decode('utf-8')
    print("Valid UTF-8")
    print(s[:200])
except Exception as e:
    print("Invalid UTF-8:", e)
