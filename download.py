import urllib.request
import os

files = ["login.html", "setup.html", "console.html", "vnc_console.html"]
repo_url = "https://raw.githubusercontent.com/kucukasker718-bot/ankavm/main/ankavm/frontend/templates/"
for f in files:
    urllib.request.urlretrieve(repo_url + f, r"C:\Users\Administrator\Desktop\oxware-hypervisor-main\ankavm\frontend\templates\\" + f)
    print(f"Downloaded {f}")
