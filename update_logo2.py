import os
import re

new_link = "https://cdn.discordapp.com/attachments/1515045766870204546/1517299816584187974/A6BC5533-45B8-4EFC-A059-6BEEB5EFD501.png?ex=6a371892&is=6a35c712&hm=6afedb435545b73510418a3a2d8e5ffd7933ab1632c85d9436a7f76009e48114&"

pattern_discord = re.compile(r'https://cdn\.discordapp\.com/attachments/[^"\'\s>)]+')

root_dir = r'C:\Users\Administrator\Desktop\oxware-hypervisor-main\ankavm\frontend\templates'
for f in os.listdir(root_dir):
    if f.endswith('.html'):
        path = os.path.join(root_dir, f)
        try:
            with open(path, 'r', encoding='utf-8') as file:
                content = file.read()
                
            new_content = pattern_discord.sub(new_link, content)
            new_content = new_content.replace('/static/img/sadeceikon.png', new_link)
            
            if new_content != content:
                with open(path, 'w', encoding='utf-8') as file:
                    file.write(new_content)
                print(f"Updated {path}")
        except Exception as e:
            print(f"Error on {path}: {e}")
