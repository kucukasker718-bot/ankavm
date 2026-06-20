import sys

with open(r'C:\Users\Administrator\Desktop\oxware-hypervisor-main\ankavm\frontend\templates\login.html', 'rb') as f:
    data = f.read()
if data.startswith(b'\xef\xbb\xbf'):
    data = data[3:]
    
s = data.decode('utf-8')

high_chars = set()
for ch in s:
    if ord(ch) >= 256:
        high_chars.add(ch)

print(f"High characters (>255) found: {[ (ch, ord(ch)) for ch in high_chars ]}")
