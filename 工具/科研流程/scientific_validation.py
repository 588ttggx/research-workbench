"""Group-aware validation built on scikit-learn; no THz physical model is invented."""
import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn import config_context
from sklearn.metrics import balanced_accuracy_score, confusion_matrix,make_scorer,recall_score
from sklearn.model_selection import GridSearchCV, StratifiedGroupKFold, GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from scipy.stats import bootstrap


def _sample_score(truth,prediction,independent_ids):
    labels=sorted(set(truth.tolist())|set(prediction.tolist()));actual=[];voted=[]
    for sample in sorted(set(independent_ids.tolist())):
        mask=independent_ids==sample;actual.append(truth[mask][0])
        voted.append(labels[int(np.argmax([sum(prediction[mask]==label) for label in labels]))])
    return recall_score(actual,voted,labels=sorted(set(actual)),average='macro',zero_division=0)


def classify(matrix,labels,independent_ids,*,batch_ids=None,split_by='sample',seed=42,resamples=2000):
    x=np.asarray(matrix,dtype=float);y=np.asarray(labels);samples=np.asarray(independent_ids)
    if x.ndim!=2 or len(x)!=len(y) or len(x)!=len(samples) or not np.isfinite(x).all():
        raise ValueError('数值、标签与独立样品 ID 必须完整对齐')
    if any(not str(v).strip() for v in samples) or any(not str(v).strip() for v in y):raise ValueError('独立样品 ID 和类别不能为空')
    if type(seed) is not int or not 0<=seed<2**32 or type(resamples) is not int or not 100<=resamples<=10000:raise ValueError('随机种子或不确定性计算次数无效')
    if split_by not in ('sample','batch'):raise ValueError('划分单位必须是独立样品或批次')
    if split_by=='batch' and batch_ids is None:raise ValueError('批次划分需要材料批次 ID')
    groups=np.asarray(batch_ids) if split_by=='batch' else samples
    if len(groups)!=len(x) or any(not str(v).strip() for v in groups) or len(set(groups))<5:raise ValueError('至少需要五个完整的独立划分单位，不能把重复扫描当独立样本')
    # A biological sample cannot have conflicting cultivar labels.
    for sample in set(samples):
        if len(set(y[samples==sample]))!=1:raise ValueError('同一独立样品的标签不一致')
        if split_by=='batch' and len(set(groups[samples==sample]))!=1:raise ValueError('同一样品对应多个批次，请先核对材料身份')
    train,test=next(GroupShuffleSplit(n_splits=1,test_size=.25,random_state=seed).split(x,y,groups))
    if set(samples[train])&set(samples[test]):raise ValueError('独立样品泄漏到测试集')
    if len(set(y[train]))<2 or set(y[test])!=set(y[train]):raise ValueError('划分后的类别覆盖不足，请增加独立样品')
    folds=min(5,min(len(set(groups[train][y[train]==label])) for label in set(y[train])))
    if folds<3:raise ValueError('训练集独立分组不足以进行交叉验证')
    while folds>=3:
        cv=StratifiedGroupKFold(folds,shuffle=True,random_state=seed);cv_splits=list(cv.split(x[train],y[train],groups[train]))
        if all(len(set(y[train][a]))>=2 and set(y[train][b])==set(y[train]) for a,b in cv_splits):break
        folds-=1
    if folds<3:raise ValueError('训练集分组无法形成至少三折的完整类别验证，请增加独立样品或批次')
    weights=np.asarray([1/sum(samples[train]==sample) for sample in samples[train]])
    # Route identities to the scorer, and equal-sample weights to both fitted steps.
    # Official API: https://scikit-learn.org/stable/metadata_routing.html
    with config_context(enable_metadata_routing=True):
        pipe=Pipeline([('scale',StandardScaler().set_fit_request(sample_weight=True)),('model',LogisticRegression(max_iter=2000,random_state=seed).set_fit_request(sample_weight=True))])
        score=make_scorer(_sample_score).set_score_request(independent_ids=True)
        search=GridSearchCV(pipe,{'model__C':[.01,.1,1,10]},cv=cv,scoring=score,error_score='raise')
        search.fit(x[train],y[train],groups=groups[train],sample_weight=weights,independent_ids=samples[train])
    pred=search.predict(x[test])
    baseline=DummyClassifier(strategy='most_frequent').fit(x[train],y[train],sample_weight=weights)
    classes=sorted(set(y.tolist()))
    # Score each independent sample once, even when it has many repeated scans.
    baseline_pred=baseline.predict(x[test]);sample_truth=[];sample_pred=[];sample_baseline=[];sample_groups=[]
    test_samples=sorted(set(samples[test].tolist()))
    def vote(values):
        counts=[sum(values==label) for label in classes]
        return classes[int(np.argmax(counts))]
    for sample in test_samples:
        mask=samples[test]==sample;sample_truth.append(y[test][mask][0]);sample_pred.append(vote(pred[mask]));sample_baseline.append(vote(baseline_pred[mask]));sample_groups.append(groups[test][mask][0])
    truth=np.asarray(sample_truth);prediction=np.asarray(sample_pred);units=np.asarray(sample_groups)
    uncertainty={'status':'unavailable','reason':'测试集每类至少需要两个独立样品；批次区间还需要至少四批且每批覆盖所有类别。','resamples':resamples,'confidence_level':.95}
    if split_by=='sample' and all(sum(truth==label)>=2 for label in classes):
        partitions=tuple(np.flatnonzero(truth==label) for label in classes)
        def statistic(*indices):
            selected=np.concatenate(indices).astype(int)
            return balanced_accuracy_score(truth[selected],prediction[selected])
        interval=bootstrap(partitions,statistic,vectorized=False,paired=False,n_resamples=resamples,method='percentile',rng=np.random.default_rng(seed))
        uncertainty.update(status='estimated',method='SciPy stratified bootstrap of independent test samples',interval=[float(interval.confidence_interval.low),float(interval.confidence_interval.high)])
    elif split_by=='batch' and len(set(units))>=4 and all(set(truth[units==unit])==set(classes) for unit in set(units)):
        cluster_ids=np.arange(len(set(units)));clusters=sorted(set(units.tolist()))
        def statistic(indices):
            selected=np.concatenate([np.flatnonzero(units==clusters[int(index)]) for index in indices])
            return balanced_accuracy_score(truth[selected],prediction[selected])
        interval=bootstrap((cluster_ids,),statistic,vectorized=False,n_resamples=resamples,method='percentile',rng=np.random.default_rng(seed))
        uncertainty.update(status='estimated',method='SciPy cluster bootstrap of held-out material batches',interval=[float(interval.confidence_interval.low),float(interval.confidence_interval.high)])
    return {'seed':seed,'split_by':split_by,'train_rows':train.tolist(),'test_rows':test.tolist(),
            'cv_folds':[{'train_rows':train[a].tolist(),'validation_rows':train[b].tolist()} for a,b in cv_splits],
            'cv_fold_count':folds,'cv_rule':'StratifiedGroupKFold, up to 5 down to 3 folds; require complete validation-class coverage using training data only',
            'train_groups':sorted(set(groups[train].tolist())),'test_groups':sorted(set(groups[test].tolist())),
            'best_parameters':search.best_params_,'cv_scores':search.cv_results_['mean_test_score'].tolist(),
            'tuning':[{'parameters':params,'mean':float(mean),'std':float(std)} for params,mean,std in zip(search.cv_results_['params'],search.cv_results_['mean_test_score'],search.cv_results_['std_test_score'])],
            'balanced_accuracy':float(balanced_accuracy_score(truth,prediction)),
            'baseline_balanced_accuracy':float(balanced_accuracy_score(truth,sample_baseline)),
            'confusion_matrix':confusion_matrix(truth,prediction,labels=classes).tolist(),'classes':classes,
            'test_samples':test_samples,'test_predictions':prediction.tolist(),'test_truth':truth.tolist(),'uncertainty':uncertainty,
            'evaluation_unit':'independent sample; repeated scans use majority vote; ties follow recorded class order',
            'training_weight':'each independent sample has total weight 1 in scaling and model fitting',
            'scope':'固定分组留出与训练折内标准化、调参；每个独立样品只计一次。区间仅描述当前留出样品/批次，不包含全部训练、调参与外部泛化不确定性，仍为探索验证。'}


def check_waveform_metadata(metadata):
    required=('independent_sample_id','preparation_id','scan_id','batch_id','measurement_date',
              'sample_waveform_uri','reference_waveform_uri','time_axis_unit','signal_unit',
              'instrument_id','calibration_id','temperature','relative_humidity')
    missing=[key for key in required if metadata.get(key) in (None,'')]
    return {'complete':not missing,'missing':missing,'qc_status':'UNASSESSED',
            'reason':'需要批准的方法、实际波形及 QC 阈值后才能给出 PASS / WARNING / FAIL'}
