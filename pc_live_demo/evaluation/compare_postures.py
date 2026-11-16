"""Replay actual old UI cutoffs vs data-derived cutoffs and a causal posture FSM.

01/02 selects thresholds. 03 is replayed only after parameters freeze.
The old UI has 3 groups; its SIT_OR_BEND output is kept ambiguous rather
than misrepresented as a four-class classifier.
"""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import statistics

import numpy as np
from sklearn.metrics import confusion_matrix,accuracy_score,f1_score,recall_score

from posture_fsm import PostureFSM,old_posture,height_posture
from train_replay import read_frames,PHASE_DIR,LABEL_FILE

CLASSES=['STAND','SIT','BEND','LYING']
COARSE=['STAND','SIT_OR_BEND','LYING']
LABELS={'STAND':'STAND','SIT':'SIT','BEND':'BEND','LYING':'LYING','LYING_POST_FALL':'LYING'}


def coarse(label):return 'SIT_OR_BEND' if label in ('SIT','BEND') else label


def load_streams(root):
    with (root/PHASE_DIR/LABEL_FILE).open(encoding='utf-8-sig',newline='') as f:phases=list(csv.DictReader(f))
    grouped={}
    for row in phases:grouped.setdefault(row['folder'],[]).append(row)
    streams=[]
    for name,rows in sorted(grouped.items()):
        frames=[];last_t=None;last_slot=None;buf=[]
        rows.sort(key=lambda r:int(r['start_t_us']))
        for stamp,targets,backlog in read_frames(root/f'{name[0]}_direction'/name/'samples.csv'):
            if backlog>500 or len(targets)!=1:
                last_t=None;last_slot=None;buf=[];continue
            target=targets[0]
            reset=last_t is None or stamp<=last_t or stamp-last_t>350_000 or target['slot']!=last_slot
            if reset:buf=[]
            buf.append((1700-target['x_mm'])/1000);buf=buf[-3:]
            z=round(statistics.median(buf),3)
            last_t=stamp;last_slot=target['slot']
            matching=[r for r in rows if int(r['start_t_us'])<=stamp<=int(r['end_t_us'])]
            row=matching[0] if len(matching)==1 else None
            label=None
            if row and not row['verification_status'].startswith('needs_review'):
                label=LABELS.get(row['activity_label'])
            frames.append(dict(t=stamp/1e6,z=z,reset=reset,label=label,
                               source_label=row['activity_label'] if row else 'UNLABELED'))
        streams.append(dict(name=name,repeat=int(name.rsplit('_',1)[1]),frames=frames))
    return streams,phases


def metrics(y,pred,labels):
    return dict(frames=len(y),accuracy=float(accuracy_score(y,pred)),
                macro_f1=float(f1_score(y,pred,labels=labels,average='macro',zero_division=0)),
                per_class_recall=dict(zip(labels,map(float,recall_score(y,pred,labels=labels,average=None,zero_division=0)))),
                confusion_matrix=confusion_matrix(y,pred,labels=labels).tolist(),classes=labels)


def evaluate(streams,config=None,height_only=False,details=False):
    y=[];p=[];old=[];records=[];trial_rows=[]
    for stream in streams:
        detector=PostureFSM(**config) if config else None
        ty=[];tp=[];to=[]
        for frame in stream['frames']:
            if config:
                predicted=height_posture(frame['z'],config['low_m'],config['high_m']) if height_only else detector.update(frame['t'],frame['z'],frame['reset'])
            else:predicted=old_posture(frame['z'])
            label=frame['label']
            if label is None:continue
            original=old_posture(frame['z'])
            y.append(label);p.append(predicted);old.append(original)
            ty.append(coarse(label));tp.append(coarse(predicted));to.append(original)
            if details:records.append(dict(trial=stream['name'],t_s=frame['t'],z_est_m=frame['z'],
                 reference=label,old=original,new=predicted,
                 new_bend_is_provisional=predicted=='BEND'))
        if ty:trial_rows.append(dict(trial=stream['name'],frames=len(ty),
                  old_correct=sum(a==b for a,b in zip(ty,to)),
                  new_correct=sum(a==b for a,b in zip(ty,tp))))
    result=dict(common_three_groups=metrics([coarse(v) for v in y],[coarse(v) for v in p],COARSE),
                old_common_three_groups=metrics([coarse(v) for v in y],old,COARSE),
                reference_counts=dict(Counter(y)),by_trial=trial_rows)
    if config and not height_only:result['four_classes']=metrics(y,p,CLASSES)
    return result,records


def choose_height(dev):
    frames=[f for s in dev for f in s['frames'] if f['label'] is not None]
    values=np.array([f['z'] for f in frames]);y=np.array([COARSE.index(coarse(f['label'])) for f in frames])
    unique=np.unique(values);cuts=(unique[:-1]+unique[1:])/2
    # Three-group macro recall, so a long standing recording cannot dominate.
    cdfs=[np.searchsorted(np.sort(values[y==k]),cuts,side='left')/np.sum(y==k) for k in range(3)]
    best=None
    for i,low in enumerate(cuts):
        if not 0<=low<=.8:continue
        indices=np.flatnonzero((cuts>low)&(cuts>=.5)&(cuts<=1.6))
        if not len(indices):continue
        scores=(cdfs[2][i]+cdfs[1][indices]-cdfs[1][i]+1-cdfs[0][indices])/3
        maximum=float(scores.max())
        for j in indices[np.isclose(scores,maximum,atol=1e-12,rtol=0)]:
            key=(maximum,-(abs(low-.48)+abs(cuts[j]-1)))
            if best is None or key>best[0]:best=(key,float(low),float(cuts[j]))
    return best[1],best[2],best[0][0]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root',type=Path,required=True)
    parser.add_argument('--out',type=Path,default=Path('results'))
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    streams,phases=load_streams(args.data_root)
    dev=[s for s in streams if s['repeat'] in (1,2)];test=[s for s in streams if s['repeat']==3]
    low,high,bacc=choose_height(dev)
    bends=[r for r in phases if r['repeat'] in ('1','2') and r['activity_label']=='BEND'
           and not r['verification_status'].startswith('needs_review')]
    duration=np.array([float(r['duration_s']) for r in bends])
    drops=[]
    for stream in dev:
        for row in (r for r in bends if r['folder']==stream['name']):
            values=[f['z'] for f in stream['frames'] if int(row['start_t_us'])/1e6<=f['t']<=int(row['end_t_us'])/1e6]
            if len(values)>=3:drops.append(sum(values[:3])/3-min(values))
    drop_candidates=sorted(set(round(max(.02,float(np.quantile(drops,q))),3) for q in (.1,.25,.5,.75)))
    time_candidates=sorted(set(round(float(np.quantile(duration,q)),3) for q in (.1,.25,.5,.75,.9)))
    search=[]
    print('Height cutoffs from development frames:',low,high,flush=True)
    for drop in drop_candidates:
        for timeout in time_candidates:
            config=dict(low_m=low,high_m=high,bend_drop_m=drop,bend_timeout_s=timeout)
            result,_=evaluate(dev,config)
            search.append(dict(config=config,metrics=result['four_classes']))
    chosen=max(search,key=lambda r:(r['metrics']['macro_f1'],r['metrics']['accuracy'],r['config']['bend_drop_m'],-r['config']['bend_timeout_s']))
    config=chosen['config']
    old_dev,_=evaluate(dev);old_test,_=evaluate(test)
    new_dev,_=evaluate(dev,config);new_test,records=evaluate(test,config,details=True)
    height_test,_=evaluate(test,config,height_only=True)
    output=dict(config=config,selection='Development frame-level 3-group balanced recall for heights, then 4-class macro F1 for bend parameters.',
                candidate_grids=dict(bend_drop_m=drop_candidates,bend_timeout_s=time_candidates),
                development=dict(old=old_dev,new=new_dev),test=dict(old=old_test,height_only=height_test,new=new_test),
                h_mount_m=1.7,fall_model_and_8s_alarm_unchanged=True,
                evaluated_reference_labels=LABELS,
                limits=['Semi-automatic labels derived from radar, not independent ground truth.',
                        'Frames correlate strongly; trial-level evidence is also saved.',
                        'The old UI only has 3 groups. Four-class accuracy is not attributed to it.',
                        'A causal BEND prediction during lowering is provisional, not confirmation using future recovery.',
                        'Transitions, WALK, SQUAT and FALL are not forced into these four reference labels.',
                        'Repeat 03 has been inspected in earlier experiments; not a fresh blind test.',
                        'Height search has declared bounds low 0..0.8m, high 0.5..1.6m; not universal thresholds.'])
    (args.out/'comparison.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    (args.out/'posture_config_1p7m.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    (args.out/'development_search.json').write_text(json.dumps(search,indent=2),encoding='utf-8')
    with (args.out/'test_frame_predictions.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    print(json.dumps(dict(config=config,development_old=old_dev['common_three_groups'],
          development_new=new_dev['common_three_groups'],test_old=old_test['common_three_groups'],
          test_height_only=height_test['common_three_groups'],test_new=new_test['common_three_groups'],
          test_four_classes=new_test['four_classes']),ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
