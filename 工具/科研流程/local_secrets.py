"""Windows DPAPI protected credentials, local-machine scope for desktop/service users."""
import json
from pathlib import Path
import secrets
import win32crypt

ROOT=Path(__file__).resolve().parents[2]
FILE=ROOT/'工具/n8n/data/local-credentials.dpapi'


def credentials():
    if FILE.exists():
        return json.loads(win32crypt.CryptUnprotectData(FILE.read_bytes(),None,None,None,0)[1])
    value={'email':'research-workspace@localhost.invalid','password':'R7!'+secrets.token_urlsafe(28),'automation_token':secrets.token_urlsafe(40)}
    FILE.parent.mkdir(parents=True,exist_ok=True)
    FILE.write_bytes(win32crypt.CryptProtectData(json.dumps(value).encode(), 'Research Workspace',None,None,None,4))
    return value


def automation_authorized(header):
    expected='Bearer '+credentials()['automation_token']
    return isinstance(header,str) and secrets.compare_digest(header,expected)
