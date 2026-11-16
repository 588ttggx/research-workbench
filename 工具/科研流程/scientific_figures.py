"""Export the supported plot specifications through Matplotlib's native backends."""
import html
import os
from pathlib import Path
import threading
import workflow as w

LOCK=threading.Lock()


def export(figure,folder,identity):
    os.environ.setdefault('MPLCONFIGDIR',str(w.ROOT/'runtime/cache/Matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    colors=['#357C74','#C38758','#637FA7','#A48DAB','#8B9665','#A6636B']
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    layout=figure.get('layout',{})
    with LOCK,plt.rc_context({'font.family':['Microsoft YaHei','DejaVu Sans'], 'font.size':11,
                             'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none',
                             'svg.hashsalt':identity,'axes.labelcolor':'#263744','text.color':'#263744'}):
        fig,ax=plt.subplots(figsize=(8,5.4),layout='constrained')
        try:
            for index,trace in enumerate(figure.get('data',[])):
                label=html.unescape(trace.get('name') or '')
                if trace.get('type')=='heatmap':
                    image=ax.imshow(trace['z'],cmap='Blues' if trace.get('colorscale')=='Blues' else 'RdBu_r',vmin=trace.get('zmin',-1),vmax=trace.get('zmax'),aspect='auto')
                    ax.set_xticks(range(len(trace['x'])),[html.unescape(x) for x in trace['x']],rotation=45,ha='right')
                    ax.set_yticks(range(len(trace['y'])),[html.unescape(y) for y in trace['y']])
                    fig.colorbar(image,ax=ax,label=trace.get('colorbar',{}).get('title',{}).get('text','Pearson r'),shrink=.8)
                elif trace.get('type')=='bar':
                    bars=ax.bar(trace['x'],trace['y'],label=label,color=colors[index%len(colors)],width=.65)
                    ax.bar_label(bars,padding=4,fontsize=10)
                    ax.margins(y=.15)
                elif trace.get('type')=='scatter':
                    if trace.get('mode')=='lines':
                        ax.plot(trace['x'],trace['y'],label=label,color=trace.get('line',{}).get('color',colors[index%len(colors)]),linewidth=1.7)
                    else:
                        ax.scatter(trace['x'],trace['y'],label=label,color=colors[index%len(colors)],s=28,alpha=.85,edgecolors='white',linewidths=.5)
                else:
                    raise ValueError('当前图类型尚未接入保存后端')
            ax.set_title(html.unescape((layout.get('title') or {}).get('text','')),loc='left',pad=16,fontsize=14,fontweight='semibold')
            for name,setter in (('xaxis',ax.set_xlabel),('yaxis',ax.set_ylabel)):
                setter(html.unescape(((layout.get(name) or {}).get('title') or {}).get('text','')))
                if (layout.get(name) or {}).get('type')=='log':
                    (ax.set_xscale if name=='xaxis' else ax.set_yscale)('log')
            if len(figure.get('data',[]))>1:ax.legend(frameon=False,fontsize=9)
            if not any(t.get('type')=='heatmap' for t in figure.get('data',[])):
                ax.grid(axis='both',color='#E7EBEE',linewidth=.6);ax.set_axisbelow(True)
            files=[]
            for suffix in ('svg','png','pdf'):
                path=folder/('figure.'+suffix)
                metadata={'Creator':'Research Workspace / Matplotlib','Title':identity}
                if suffix=='svg':metadata['Date']=None
                if suffix=='pdf':metadata.update(CreationDate=None,ModDate=None)
                if suffix=='png':metadata={'Software':'Research Workspace / Matplotlib','Run':identity}
                fig.savefig(path,dpi=300,metadata=metadata)
                files.append({'name':path.name,'sha256':w.digest(path.read_bytes()),'bytes':path.stat().st_size})
            return files
        finally:plt.close(fig)
