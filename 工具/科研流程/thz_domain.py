"""Explicit single-pass domain model over NumPy/SciPy, not a SciPy THz API.

Neu & Schmuttenmaer, J. Appl. Phys. 124, 231101 (2018),
DOI 10.1063/1.5047659, PDF pp. 11-12, Sec. VI C/F, Eqs. 25,31-33.
Normal-incidence homogeneous freestanding slab, air reference, weak absorption
at the interfaces, internal echoes excluded. Values describe the effective slab,
not the pure constituent of a powder/host mixture. Other geometries are rejected.
No thresholds, calibration, physical units or sample identities are inferred.
"""
import csv
import io
import math
import html
from datetime import datetime
import numpy as np
from scipy import fft,signal,constants

UNITS={'s':1.,'ns':1e-9,'ps':1e-12,'fs':1e-15}
THRESHOLDS={'snr_db':'lower','reference_drift_fraction':'upper','time_zero_shift_ps':'upper',
 'dynamic_range_db':'lower','humidity_percent':'upper','water_vapor_metric':'upper'}
ASSUMPTIONS=['normal_incidence','homogeneous_parallel_slab','air_reference','weak_interface_absorption','internal_echoes_excluded']


def validate_policy(policy):
    if not isinstance(policy,dict) or policy.get('model')!='single_pass_weak_absorption':raise ValueError('请选择已实现且适用的 THz 方法模型')
    for key in ('frequency_min_thz','frequency_max_thz','reference_floor_fraction'):
        if type(policy.get(key)) not in (int,float) or not math.isfinite(policy[key]):raise ValueError('方法需要明确的可信频段和参考幅值下限')
    if not 0<policy['frequency_min_thz']<policy['frequency_max_thz'] or not 0<policy['reference_floor_fraction']<1:raise ValueError('可信频段或参考幅值下限无效')
    if type(policy.get('phase_offset_turns')) is not int or abs(policy['phase_offset_turns'])>1000:raise ValueError('请明确相位分支偏移的整数圈数')
    if policy.get('baseline') not in ('none','noise_mean'):raise ValueError('基线方法无效')
    smooth=policy.get('savgol_window',0)
    if type(smooth) is not int or smooth and (smooth<5 or smooth%2!=1 or smooth>301):raise ValueError('Savitzky–Golay 窗口必须为 5–301 的奇数，0 表示不用')
    thresholds=policy.get('thresholds',{})
    if not isinstance(thresholds,dict) or set(thresholds)-set(THRESHOLDS):raise ValueError('QC 指标名称无效')
    for name,rule in thresholds.items():
        if not isinstance(rule,dict) or set(rule)!={'warning','fail'} or any(type(v) not in (int,float) or not math.isfinite(v) for v in rule.values()):raise ValueError('QC 需要明确的 Warning 和 Fail 数值')
        if (THRESHOLDS[name]=='lower' and rule['fail']>rule['warning']) or (THRESHOLDS[name]=='upper' and rule['fail']<rule['warning']):raise ValueError('QC 阈值方向不一致')
    return policy


def quality(metrics,policy,metadata):
    checks=[]
    for name in THRESHOLDS:
        rule=policy.get('thresholds',{}).get(name)
        value=metrics.get(name)
        state='UNASSESSED'
        if value is not None and rule is not None:
            lower=THRESHOLDS[name]=='lower';failed=value<rule['fail'] if lower else value>rule['fail'];warn=value<rule['warning'] if lower else value>rule['warning']
            state='FAIL' if failed else 'WARNING' if warn else 'PASS'
        reason='方法阈值未设置' if rule is None else '缺少实际测量值' if value is None else '按当前方法阈值检查'
        checks.append({'metric':name,'value':value,'status':state,'thresholds':rule,'direction':THRESHOLDS[name],'reason':reason})
    instrument=metadata.get('instrument_state','UNKNOWN')
    checks.append({'metric':'instrument_state','value':instrument,'status':'PASS' if instrument=='READY' else 'FAIL' if instrument in ('FAULT','MAINTENANCE') else 'UNASSESSED'})
    calibration='UNASSESSED'
    if metadata.get('calibration_valid_until'):
        try:
            expiry=datetime.fromisoformat(metadata['calibration_valid_until'].replace('Z','+00:00'))
            measured=datetime.fromisoformat(metadata['measurement_date'].replace('Z','+00:00'))
        except (ValueError,TypeError):raise ValueError('测量日期或校准有效期格式无效') from None
        if len(metadata['calibration_valid_until'])==10:
            calibration='PASS' if measured.date()<=expiry.date() else 'FAIL'
        elif expiry.tzinfo is not None and measured.tzinfo is not None:
            calibration='PASS' if measured<=expiry else 'FAIL'
        # Timestamp expiry without both time zones cannot certify validity.
    checks.append({'metric':'calibration_at_measurement','value':metadata.get('calibration_valid_until'),'status':calibration,'reason':'缺少明确有效期，或精确时刻缺少时区' if calibration=='UNASSESSED' else '按实际测量日期或带时区的时刻检查'})
    environment={key:metrics.get(key) for key in ('temperature_celsius','humidity_percent')}
    checks.append({'metric':'environment_recorded','value':environment,'status':'PASS' if all(v is not None for v in environment.values()) else 'UNASSESSED'})
    states={c['status'] for c in checks}
    status='FAIL' if 'FAIL' in states else 'UNASSESSED' if 'UNASSESSED' in states or not policy.get('thresholds') else 'WARNING' if 'WARNING' in states else 'PASS'
    return {'status':status,'checks':checks,'scope':'仅按当前方法的已批准阈值和实际测量信息检查；不推断根因、材料类别或研究结论。'}


def compute(text,options):
    policy=validate_policy(options.get('method_snapshot'));metadata=options.get('metadata',{})
    required=('independent_sample_id','preparation_id','scan_id','batch_id','measurement_date','instrument_id','calibration_id','time_unit','signal_unit')
    unknown={'unknown','未知','不清楚','不知道','待确认','n/a','na','none','null'}
    if not isinstance(metadata,dict) or any(not isinstance(metadata.get(k),str) or not metadata[k].strip() or metadata[k].strip().lower() in unknown for k in required):raise ValueError('请补齐样品、重复层级、批次、测量日期、仪器、校准及坐标单位；未知不能作为已知身份')
    if metadata['time_unit'] not in UNITS or metadata.get('reference_pairing_confirmed') is not True:raise ValueError('请明确物理时间单位并确认信号与参考的实际配对')
    try:datetime.fromisoformat(metadata['measurement_date'].replace('Z','+00:00'))
    except ValueError:raise ValueError('测量日期需要实际 ISO 日期或时间') from None
    if metadata.get('geometry_confirmed') is not True or any(metadata.get(key) is not True for key in ASSUMPTIONS):raise ValueError('此方法只适用于已确认的近法向、均匀平行厚片、空气参考、弱界面吸收且已排除内部反射的情况')
    thickness=metadata.get('thickness_mm')
    if type(thickness) not in (int,float) or not math.isfinite(thickness) or not 0<thickness<1000:raise ValueError('需要实际样品厚度，单位为 mm')
    rows=list(csv.DictReader(io.StringIO(text.lstrip('\ufeff'))));columns=options.get('columns',{})
    names=[columns.get(k) for k in ('time','sample','reference')]
    if not rows or len(set(names))!=3 or any(name not in rows[0] for name in names):raise ValueError('请为时间、信号和参考选择三个不同的数值列')
    try:t,x,r=np.array([[float(row[name]) for row in rows] for name in names],dtype=float)
    except (ValueError,TypeError):raise ValueError('波形列需为完整有限数值') from None
    if not 16<=len(t)<=10000 or not np.isfinite([t,x,r]).all():raise ValueError('需要 16–10000 个完整采样点')
    t=t*UNITS[metadata['time_unit']];delta=np.diff(t)
    if np.any(delta<=0) or not np.allclose(delta,delta.mean(),rtol=1e-5,atol=0):raise ValueError('FFT 需要递增且均匀的物理时间坐标；不自动插值或猜测单位')
    dt=float(delta.mean());noise=options.get('noise_indices');noise_slice=None
    if noise is not None:
        if not isinstance(noise,list) or len(noise)!=2 or any(type(v) is not int for v in noise) or not 0<=noise[0]<noise[1]<=len(t) or noise[1]-noise[0]<4:raise ValueError('噪声窗口需为至少四点的有效起止序号')
        noise_slice=slice(*noise)
    if policy['baseline']=='noise_mean':
        if noise_slice is None:raise ValueError('基线扣除需要明确的不含脉冲噪声窗口')
        x=x-float(x[noise_slice].mean());r=r-float(r[noise_slice].mean())
    smooth=policy.get('savgol_window',0)
    if smooth:
        if smooth>=len(t):raise ValueError('去噪窗口需小于波形长度')
        x=signal.savgol_filter(x,smooth,2);r=signal.savgol_filter(r,smooth,2)
    # Sample/reference are never peak-aligned: their physical delay contains n.
    xf=fft.rfft(x);rf=fft.rfft(r);frequency=fft.rfftfreq(len(t),dt);magnitude=np.abs(rf)
    if magnitude.max()<=0:raise ValueError('参考波形为零，不能形成传递函数')
    band=(frequency>=policy['frequency_min_thz']*1e12)&(frequency<=policy['frequency_max_thz']*1e12)&(frequency>0)
    indexes=np.flatnonzero(band)
    if len(indexes)<3:raise ValueError('可信频段内至少需要三个 FFT 频点，请核对单位与测量窗口')
    if np.any(magnitude[indexes]<magnitude.max()*policy['reference_floor_fraction']):raise ValueError('所选频段存在低参考幅值点，请依据参考频谱缩小可信频段；不自动补造相位')
    transfer=xf[indexes]/rf[indexes]
    if np.any(np.abs(transfer)<=0):raise ValueError('频段内信号为零，无法计算吸收和相位')
    phase=np.unwrap(np.angle(transfer))+2*np.pi*policy['phase_offset_turns'];omega=2*np.pi*frequency[indexes];d=thickness/1000
    n=1-constants.c*phase/(omega*d)
    if np.any(n<=0):raise ValueError('相位分支或模型条件不符，得到非正折射率；请核对方法，不自动修正')
    fresnel=4*n/(n+1)**2;alpha=-2/d*np.log(np.abs(transfer)/fresnel)
    # alpha is in m^-1 internally; report cm^-1, retaining negative values.
    metrics={'rows':len(t),'time_step_ps':dt/1e-12,'thickness_mm':thickness,'frequency_points':len(indexes),
             'frequency_thz':(frequency[indexes]/1e12).tolist(),'refractive_index':n.tolist(),'absorption_cm_inverse':(alpha/100).tolist(),
             'transmission_field_magnitude':np.abs(transfer).tolist(),'phase_radians':phase.tolist(),
             'model':policy['model'],'method_id':options.get('method_id'),'method_fingerprint':options.get('method_fingerprint'),
             'phase_offset_turns':policy['phase_offset_turns'],'physical_sample_delay_preserved':True,
             'scope':'探索计算：单程弱界面吸收近似；结果是有效样片性质，不是混合粉末中纯组分性质。负吸收保留并提示，不能截断成零或解释为已证实增益。'}
    if noise_slice is not None:
        noise_rms=float(np.sqrt(np.mean((x[noise_slice]-x[noise_slice].mean())**2)))
        if noise_rms>0:metrics['snr_db']=float(20*np.log10(np.max(np.abs(x))/noise_rms))
    for key in ('temperature_celsius','humidity_percent','dynamic_range_db','water_vapor_metric'):
        value=metadata.get(key)
        if value is not None:
            if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('环境或质量指标必须为实际有限数值')
            if key=='humidity_percent' and not 0<=value<=100:raise ValueError('实际湿度应在 0–100% 之间')
            if key=='temperature_celsius' and value<=-273.15:raise ValueError('实际温度不能低于绝对零度')
            metrics[key]=value
    after=columns.get('reference_after')
    if after:
        try:ra=np.asarray([float(row[after]) for row in rows])
        except (KeyError,ValueError):raise ValueError('后采参考列无效') from None
        if not np.isfinite(ra).all() or np.ptp(r)<=0:raise ValueError('参考漂移检查需要完整、非零参考波形')
        if policy['baseline']=='noise_mean':ra=ra-float(ra[noise_slice].mean())
        if smooth:ra=signal.savgol_filter(ra,smooth,2)
        metrics['reference_drift_fraction']=float(abs(np.ptp(ra)/np.ptp(r)-1))
        lag=signal.correlation_lags(len(ra),len(r))[int(np.argmax(signal.correlate(ra,r,method='fft')))]
        metrics['time_zero_shift_ps']=float(abs(lag*dt/1e-12))
    metrics['qc']=quality(metrics,policy,metadata)
    if np.any(alpha<0):metrics['warnings']=['存在负吸收系数，需核对参考漂移、厚度、模型条件与相位分支。']
    f=metrics['frequency_thz'];plot=options.get('thz_plot','absorption')
    if plot not in ('absorption','refractive_index','transfer'):raise ValueError('THz 图类型无效')
    ylabel='Absorption (cm⁻¹)' if plot=='absorption' else 'Refractive index' if plot=='refractive_index' else 'Field transmission'
    values=metrics['absorption_cm_inverse'] if plot=='absorption' else metrics['refractive_index'] if plot=='refractive_index' else metrics['transmission_field_magnitude']
    figure={'data':[{'type':'scatter','mode':'lines','x':f,'y':values,'name':ylabel}],
            'layout':{'title':{'text':html.escape(str(options.get('title') or 'Single-pass slab · exploratory analysis')[:180])},'xaxis':{'title':{'text':'Frequency (THz)'}},'yaxis':{'title':{'text':ylabel}}}}
    return {'kind':'thz','figure':figure,'metrics':metrics}
