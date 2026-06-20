import sys

with open(r'C:\Users\Administrator\Desktop\oxware-hypervisor-main\ankavm\frontend\templates\login.html', 'rb') as f:
    data = f.read()
if data.startswith(b'\xef\xbb\xbf'):
    data = data[3:]
    
s = data.decode('utf-8')

for i, ch in enumerate(s):
    try:
        ch.encode('cp1252')
    except Exception as e:
        print(f'Failed at pos {i}: {repr(ch)} ({ord(ch)})')
        break
