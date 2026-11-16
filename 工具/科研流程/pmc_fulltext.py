"""Resolve permitted PDFs through the current official PMC Cloud dataset.

Source: https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/ and the bucket README.txt.
Never replace XML, infer a PMC identity from bibliography references, or guess v1.
"""
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import requests
import workflow as w

BASE='https://pmc-oa-opendata.s3.amazonaws.com'


def identifier(record):
    value=record.get('pmcid') or (record.get('id') if str(record.get('id','')).startswith('PMC') else '')
    if re.fullmatch(r'PMC\d+',str(value)):return value
    for artifact in record.get('artifacts',[]):
        if artifact.get('kind')!='jats_xml':continue
        path=Path(artifact['path'])
        if not path.is_file() or path.stat().st_size>20*1024*1024:continue
        try:tree=ET.parse(path)
        except (OSError,ET.ParseError):continue
        for item in tree.findall('./front/article-meta/article-id'):
            if item.get('pub-id-type') not in ('pmc','pmcid'):continue
            value=(item.text or '').strip();value=value if value.startswith('PMC') else 'PMC'+value
            if re.fullmatch(r'PMC\d+',value):return value
    return None


def pdf_candidates(record):
    pmcid=identifier(record);doi=w.normalize_doi(record.get('doi'))
    if not pmcid or not doi:return []
    response=requests.get(BASE+'/',params={'list-type':'2','prefix':pmcid+'.','delimiter':'/','max-keys':40},timeout=20)
    response.raise_for_status()
    if len(response.content)>1024*1024:raise ValueError('PMC 版本清单过大')
    tree=ET.fromstring(response.content)
    prefixes=[(n.text or '') for n in tree.findall('.//{*}CommonPrefixes/{*}Prefix')]
    prefixes=[p for p in prefixes if re.fullmatch(re.escape(pmcid)+r'\.\d+/',p)]
    result=[]
    for prefix in prefixes[:12]:
        metadata=requests.get(BASE+'/metadata/'+prefix.rstrip('/')+'.json',timeout=20);metadata.raise_for_status();item=metadata.json()
        if not isinstance(item,dict) or str(item.get('pmcid'))!=pmcid or w.normalize_doi(item.get('doi'))!=doi:continue
        url=item.get('pdf_url');parsed=urlparse(url) if isinstance(url,str) else None
        if parsed and parsed.scheme=='s3' and parsed.netloc=='pmc-oa-opendata':
            url=BASE+parsed.path+('?'+parsed.query if parsed.query else '');parsed=urlparse(url)
        if not parsed or parsed.scheme!='https' or parsed.netloc!='pmc-oa-opendata.s3.amazonaws.com' or not parsed.path.startswith('/'+prefix) or not parsed.path.endswith('.pdf'):continue
        result.append({'url':url,'pmcid':pmcid,'version':item.get('version') or prefix.rstrip('/').split('.')[-1],
                       'is_manuscript':item.get('is_manuscript'),'license':item.get('license_code'),'source':'PMC Cloud Service'})
    return sorted(result,key=lambda row:row['is_manuscript'] in (True,'yes','true'))
