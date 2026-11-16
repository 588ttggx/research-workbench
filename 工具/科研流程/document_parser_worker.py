"""Short-lived GPU parser worker; no listener, model provider or scientific judgment."""
import json
import hashlib
import os
from pathlib import Path
import sys


def parse(source, output, *, max_pages=None, resume=None, checkpoint_out=None):
    import numpy as np
    import pymupdf
    source_sha = hashlib.sha256(Path(source).read_bytes()).hexdigest()
    pages = []
    if resume and Path(resume).is_file():
        checkpoint=json.loads(Path(resume).read_text('utf-8'))
        if checkpoint.get('source_sha256')==source_sha and checkpoint.get('pipeline_version')=='v1.6':
            candidate=checkpoint.get('pages',[])
            if isinstance(candidate,list) and all(isinstance(p,dict) and p.get('page')==i for i,p in enumerate(candidate,1)):
                pages=candidate
    with pymupdf.open(source) as pdf:
        if len(pages)>pdf.page_count:pages=[]
        if len(pages)==pdf.page_count:
            Path(output).write_text(json.dumps({'source_sha256':source_sha,'pipeline_version':'v1.6',
                'complete':True,'pages':pages},ensure_ascii=False),encoding='utf-8')
            return
        cache=os.environ.get('PADDLE_PDX_CACHE_HOME')
        if cache and not Path(cache).is_dir():
            raise FileNotFoundError('登记的模型缓存不可访问：'+cache)
        from paddleocr import PaddleOCRVL
        options={}
        if os.environ.get('THZ_DOCUMENT_VLM_BACKEND')=='vllm-server':
            options={'vl_rec_backend':'vllm-server',
                     'vl_rec_server_url':os.environ['THZ_DOCUMENT_VLM_URL'],
                     'vl_rec_api_model_name':'PaddleOCR-VL-1.6-0.9B','vl_rec_max_concurrency':8}
        pipeline=PaddleOCRVL(pipeline_version='v1.6',
            device=os.environ.get('THZ_DOCUMENT_LAYOUT_DEVICE','gpu:0'),
            use_doc_orientation_classify=False,use_doc_unwarping=False,use_layout_detection=True,
            use_chart_recognition=False,**options)
        for number, page in enumerate(pdf, 1):
            if max_pages is not None and number > max_pages:break
            if number <= len(pages):continue
            pixmap=page.get_pixmap(matrix=pymupdf.Matrix(3,3),alpha=False)
            pixels=np.frombuffer(pixmap.samples,dtype=np.uint8).reshape(pixmap.height,pixmap.width,3)
            predictions=list(pipeline.predict(pixels[:,:,::-1].copy()))
            if len(predictions)!=1:raise ValueError('Expected exactly one prediction per original page')
            data=predictions[0].json
            if isinstance(data,str):data=json.loads(data)
            data=data.get('res',data)
            blocks=[{'label':b.get('block_label','text'), 'text':b.get('block_content',''),
                     'bbox':b.get('block_bbox')} for b in data['parsing_res_list']]
            pages.append({'page':number,'width':pixmap.width,'height':pixmap.height,
                          'render_dpi':216,'blocks':blocks})
            # A partial result never gets returned by the adapter, but is useful
            # for an interrupted local batch and avoids losing completed GPU work.
            payload={'source_sha256':source_sha,'pipeline_version':'v1.6',
                     'complete':number==pdf.page_count,'pages':pages}
            from document_parser import validate_pages
            validate_pages(payload,expected_pages=number)
            serialized=json.dumps(payload,ensure_ascii=False)
            for destination in [Path(output),*([Path(checkpoint_out)] if checkpoint_out else [])]:
                destination.parent.mkdir(parents=True,exist_ok=True)
                temporary=destination.with_suffix('.tmp')
                temporary.write_text(serialized,encoding='utf-8');temporary.replace(destination)
            print(json.dumps({'page':number,'total':pdf.page_count,'blocks':len(blocks)}),flush=True)


if __name__=='__main__':
    import argparse
    cli=argparse.ArgumentParser()
    cli.add_argument('source',type=Path);cli.add_argument('output',type=Path)
    cli.add_argument('preview_pages',nargs='?',type=int);cli.add_argument('--resume',type=Path)
    cli.add_argument('--checkpoint',type=Path)
    args=cli.parse_args()
    parse(args.source,args.output,max_pages=args.preview_pages,resume=args.resume,checkpoint_out=args.checkpoint)
