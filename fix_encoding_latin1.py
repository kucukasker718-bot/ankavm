import os

def fix_encoding(filepath):
    try:
        with open(filepath, 'rb') as f:
            data = f.read()
            
        if data.startswith(b'\xef\xbb\xbf'):
            data = data[3:]
            
        try:
            s = data.decode('utf-8')
        except UnicodeDecodeError:
            return False
            
        layers_removed = 0
        
        while True:
            try:
                b = s.encode('latin1')
                s_new = b.decode('utf-8')
                if s_new == s:
                    break
                s = s_new
                layers_removed += 1
            except Exception:
                break
                
        if layers_removed > 0:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(s)
            return True
            
    except Exception as e:
        pass
    return False

root_dir = r'C:\Users\Administrator\Desktop\oxware-hypervisor-main\ankavm\frontend\templates'
for f in os.listdir(root_dir):
    if f.endswith('.html'):
        path = os.path.join(root_dir, f)
        if fix_encoding(path):
            print(f'Fixed {path}')
