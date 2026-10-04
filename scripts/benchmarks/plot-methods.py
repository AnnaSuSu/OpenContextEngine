"""Generate publication assets directly from the verified comparison JSON."""
import json,math,os,tempfile
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR',str(Path(tempfile.gettempdir())/'oce-matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch,PathPatch
from matplotlib.path import Path as PlotPath
from matplotlib.ticker import PercentFormatter
ROOT=Path(__file__).resolve().parents[2]
data=json.loads((ROOT/'docs/eval/results/method-comparison-20261004.json').read_text())
labels={'opencontextengine':'OpenContextEngine','ace':'Augment Context Engine','cocoindex':'CocoIndex Code','contextweaver':'ContextWeaver','grepai':'grepai (hybrid)','claude-context':'Claude Context','oce':'oce-ai/oce'}
colors={'opencontextengine':'#35CE8D','ace':'#A6B8FA','cocoindex':'#FFC782','contextweaver':'#DDABE5','grepai':'#89CFE0','claude-context':'#D6C69A','oce':'#B5BAC7'}
rows=[s for s in data['systems'] if s['queries']==80 and s['completed']==80 and s['runStatus']=='completed']
if len(rows)!=7:raise ValueError('A complete seven-method comparison is required before publishing the chart')
own=next(s for s in rows if s['system']=='opencontextengine')
coverage=lambda s:next(p for p in s['points'] if p['budget']==4000)['coverage']*100
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':13,'text.color':'#EEF2F5','axes.labelcolor':'#CFD4DB','xtick.color':'#B1BAC4','ytick.color':'#B1BAC4','svg.fonttype':'path','svg.hashsalt':'oce-methods-20261004'})
OUT=ROOT/'assets/benchmarks';OUT.mkdir(parents=True,exist_ok=True)
def base(title,subtitle):
 fig=plt.figure(figsize=(14,9),facecolor='#080C0B')
 frame=FancyBboxPatch((.025,.03),.95,.94,boxstyle='round,pad=0.008,rounding_size=0.025',transform=fig.transFigure,facecolor='none',edgecolor='#303A36',linewidth=1.3)
 fig.add_artist(frame)
 # Use the repository's actual bracket logo geometry, rendered as vectors.
 logo=fig.add_axes([.06,.885,.04,.062]);logo.set_xlim(50,462);logo.set_ylim(462,50);logo.set_aspect('equal');logo.axis('off')
 for points in [[(208,112),(176,112),(112,176),(112,336),(176,400),(208,400)],[(304,112),(336,112),(400,176),(400,336),(336,400),(304,400)]]:
  logo.add_patch(PathPatch(PlotPath(points,[PlotPath.MOVETO]+[PlotPath.LINETO]*5),fill=False,edgecolor='#E6F2EC',linewidth=4.5,capstyle='projecting',joinstyle='round'))
 logo.add_patch(FancyBboxPatch((212,212),88,88,boxstyle='round,pad=0,rounding_size=12',facecolor='#35CE8D',edgecolor='none'))
 fig.text(.11,.904,'OpenContextEngine',fontsize=20,fontweight='bold',color='#35CE8D')
 fig.text(.065,.838,title,fontsize=27,fontweight='bold')
 fig.text(.065,.793,subtitle,fontsize=13,color='#AEBAB5')
 return fig
fig=base('Code retrieval: quality × latency','40 tasks · Chinese + English · Django, Click, HTTPX, Zod · 4,000-token budget')
ax=fig.add_axes([.105,.235,.77,.485],facecolor='#080C0B')
for spine in ['top','right']:ax.spines[spine].set_visible(False)
for spine in ['left','bottom']:ax.spines[spine].set_color('#708078')
ax.set_ylim(0,105);ax.yaxis.set_major_formatter(PercentFormatter(100,decimals=0));ax.set_yticks(range(0,101,20))
max_seconds=max(s['medianMs']/1000 for s in rows)
ax.set_xlim(0,max_seconds*1.45);ax.grid(axis='y',color='#26312C',linewidth=.7)
ax.set_xlabel('Median query time (seconds)  ← faster',labelpad=16)
ax.set_ylabel('Required evidence coverage  → higher',labelpad=14)
# Labels alternate sides/vertical offsets; output is visually inspected before publication.
offsets={'opencontextengine':(14,15),'ace':(14,-24),'cocoindex':(14,-20),'contextweaver':(14,12),'grepai':(14,14),'claude-context':(14,14),'oce':(14,14)}
for s in sorted(rows,key=coverage):
 key=s['system'];x=s['medianMs']/1000;y=coverage(s);primary=key=='opencontextengine'
 ax.scatter(x,y,s=220 if primary else 110,c=colors[key],marker='D' if primary else 'o',edgecolors='#080C0B',linewidths=1.5,zorder=5)
 label=f"{labels[key]}\n{y:.2f}% · {x:.2f}s"
 ax.annotate(label,(x,y),xytext=offsets[key],textcoords='offset points',fontsize=13 if primary else 11,color=colors[key],fontweight='bold' if primary else 'normal',zorder=6)
fig.text(.065,.122,'Internal development evaluation. Coverage is source evidence retention, not agent task success.',fontsize=10.5,color='#9DAAA3')
fig.text(.065,.093,'Warm indexes/models. Open tools: native query time; ACE: SDK client time. Deployment timings differ.',fontsize=10.5,color='#9DAAA3')
fig.text(.065,.064,'2026-10-04 · Full protocol, per-repository scores and source fingerprints: docs/BENCHMARKS.md',fontsize=10,color='#718278')
for ext in ['svg','png']:fig.savefig(OUT/f'method-comparison.{ext}',dpi=180,facecolor=fig.get_facecolor(),metadata={'Date':None} if ext=='svg' else None)
plt.close(fig)
fig=base('More required evidence in your context','Same 80 responses per method · Four repositories · Original returned order')
ax=fig.add_axes([.105,.235,.63,.485],facecolor='#080C0B')
for spine in ['top','right']:ax.spines[spine].set_visible(False)
for spine in ['left','bottom']:ax.spines[spine].set_color('#708078')
ax.set_xlim(850,4150);ax.set_ylim(0,105);ax.set_xticks([1000,2000,3000,4000],['1,000','2,000','3,000','4,000']);ax.set_yticks(range(0,101,20));ax.yaxis.set_major_formatter(PercentFormatter(100,decimals=0));ax.grid(axis='y',color='#26312C',linewidth=.7)
for s in sorted(rows,key=coverage,reverse=True):
 key=s['system'];ax.plot([p['budget'] for p in s['points']],[100*p['coverage'] for p in s['points']],color=colors[key],label=labels[key],marker='D' if key=='opencontextengine' else 'o',linewidth=3 if key=='opencontextengine' else 1.8,markersize=7)
ax.annotate(f'{coverage(own):.2f}%',(4000,coverage(own)),xytext=(0,11),textcoords='offset points',ha='right',fontsize=13,fontweight='bold',color=colors['opencontextengine'])
ax.legend(loc='center left',bbox_to_anchor=(1.015,.55),frameon=False,fontsize=10.5,labelcolor='linecolor')
ax.set_xlabel('Returned-context budget (tokens)',labelpad=16);ax.set_ylabel('Required evidence coverage',labelpad=14)
fig.text(.065,.122,'Offline prefix scoring of the same responses; these are not new searches at each token budget.',fontsize=10.5,color='#9DAAA3')
fig.text(.065,.093,'40 source-derived tasks × 2 languages · Four repositories · Internal development set',fontsize=10.5,color='#9DAAA3')
fig.text(.065,.064,'2026-10-04 · Reproduce with scripts/benchmarks/plot-methods.py',fontsize=10,color='#718278')
for ext in ['svg','png']:fig.savefig(OUT/f'context-budget.{ext}',dpi=180,facecolor=fig.get_facecolor(),metadata={'Date':None} if ext=='svg' else None)
plt.close(fig)
for svg in OUT.glob('*.svg'):
 svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines())+'\n')
print('Generated SVG + PNG comparison and context-budget charts')
