"""Resume the approved global backfill; same locks, sources and model ledger as the UI."""
import json
import time
from pathlib import Path
import knowledge_extraction as extraction
import workflow as w


def main():
    output=w.ROOT/'output/科研工作区重构/_临时/知识图升级'
    output.mkdir(parents=True,exist_ok=True)
    before=extraction.status()
    if not before['enabled']:extraction.control({'action':'start'})
    started=time.monotonic()
    with (output/'全库处理进度.jsonl').open('a',encoding='utf-8') as log:
        while True:
            previous=extraction.status()
            if previous['paused']:break
            current=extraction.run({'max_chunks':12})
            row={'at':w.now(),'elapsed':round(time.monotonic()-started,1),
                 **{key:current[key] for key in ('status','counts','remaining','failures')}}
            log.write(json.dumps(row,ensure_ascii=False)+'\n');log.flush()
            print(json.dumps(row,ensure_ascii=True),flush=True)
            if current['remaining']==0 or current['counts']['processed_chunks']==previous['counts']['processed_chunks']:
                w.write_json(output/'全库处理覆盖.json',current)
                break


if __name__=='__main__':main()
