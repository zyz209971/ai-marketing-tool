"""Check tracked/staged files before pushing. Never print secret values."""
import re
import subprocess
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[2]
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=root).decode().split('\0')
issues=[]
for name in filter(None,names):
    path=root/name
    if (path.name=='.env' or path.name.startswith('.env.') and not path.name.endswith('.example')
            or path.suffix in ('.db','.pem','.key')):
        issues.append((name,'不应跟踪私有配置或运行文件'))
        continue
    if not path.is_file() or path.stat().st_size>500000 or path.suffix not in ('.py','.js','.md','.json','.yaml','.yml','.sh','.ps1','.txt','.example'):
        continue
    text=path.read_text(encoding='utf-8',errors='replace')
    if re.search(r'(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}',text):
        issues.append((name,'发现疑似明文密钥，请在本机检查'))
for name,reason in issues:
    print(f'{name}: {reason}')
print('检查未输出任何密钥值。此检查仅识别常见泄漏模式，不能替代提交差异审查。')
raise SystemExit(1 if issues else 0)
