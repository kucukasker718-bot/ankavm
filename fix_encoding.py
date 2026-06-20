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
            
        original_s = s
        layers_removed = 0
        
        while True:
            try:
                b = s.encode('cp1252')
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

root_dir = r'C:\Users\Administrator\Desktop\oxware-hypervisor-main'
fixed_count = 0
for subdir, dirs, files in os.walk(root_dir):
    if '.git' in subdir:
        continue
    for f in files:
        if f.endswith(('.html', '.md', '.py', '.sh', '.js', '.css', '.txt', '.json')):
            path = os.path.join(subdir, f)
            if fix_encoding(path):
                print(f'Fixed {path}')
                fixed_count += 1

print(f'Total files fixed: {fixed_count}')
