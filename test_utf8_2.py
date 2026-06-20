import urllib.request

url = "https://raw.githubusercontent.com/kucukasker718-bot/ankavm/main/ankavm/frontend/templates/setup.html"
req = urllib.request.urlopen(url)
raw = req.read()
s = raw.decode('utf-8')
print(s[:200].encode('utf-8'))
