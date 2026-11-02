# SPDX-License-Identifier: MIT OR Apache-2.0
"""Exact candidate/source/binary binding for native WP-16 profile evidence."""
from hashlib import sha256
import json
import math
from fcst_contracts import canonical
from .gate import evaluate
from .foundation import input_hashes as foundation_inputs


def input_hashes(root):
    return foundation_inputs(root)


def assess(report, policy, inputs, candidate):
    if (report.get('schema_version') != 1 or report.get('candidate') != candidate
            or report.get('input_sha256') != inputs or report.get('execution_mode') != 'fcst_native'
            or report.get('policy_sha256') != sha256(json.dumps(policy,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            or report.get('full_wp16_qualified') is not False
            or not isinstance(report.get('worker_sha256'), str) or len(report['worker_sha256']) != 64
            or set(report['worker_sha256'])-set('0123456789abcdef')
            or report.get('gate') != evaluate(policy['required_cases'], report.get('cases', []))
            or report['gate']['status'] != 'passed'):
        raise ValueError('discretization_evidence_invalid')
    metrics=report.get('metrics',{});criteria=policy['criteria']
    if set(metrics)!={'jacobian_maximum_error','steady_field_errors_K','transient_spatial_errors_K','transient_time_errors_K'}:
        raise ValueError('discretization_metrics_invalid')
    def finite(value):return type(value) in (int,float) and math.isfinite(value) and value>=0
    if not finite(metrics['jacobian_maximum_error']) or metrics['jacobian_maximum_error']>=criteria['jacobian_absolute']:
        raise ValueError('discretization_metrics_invalid')
    for key,refinement,ratio in [('steady_field_errors_K','steady_refinements','steady_minimum_error_ratio'),
        ('transient_spatial_errors_K','spatial_refinements','spatial_minimum_error_ratio'),('transient_time_errors_K','time_steps_s','time_minimum_error_ratio')]:
        values=metrics[key]
        if (not isinstance(values,list) or len(values)!=len(criteria[refinement]) or any(not finite(v) or v==0 for v in values)
                or any(a/b<=criteria[ratio] for a,b in zip(values,values[1:]))):
            raise ValueError('discretization_metrics_invalid')
    if type(report.get('commands')) is not int or report['commands']<60:raise ValueError('discretization_execution_invalid')
    offline=report.get('offline_native',{});binaries=offline.get('binary_sha256',{})
    if (offline.get('kind')!='windows-appcontainer-v1' or offline.get('execution_mode')!='fcst_native'
            or offline.get('app_container') is not True or type(offline.get('capabilities')) is not int or offline['capabilities']!=0
            or offline.get('network_denied') is not True or offline.get('network_denial') not in ('access_denied','controlled_loopback_timeout')
            or offline.get('network_positive_controls')!=2 or offline.get('negative_probes')!=2
            or type(offline.get('outside_files_denied')) is not int or offline['outside_files_denied']<4
            or evaluate(policy['offline_native_cases'],offline.get('cases',[]))['status']!='passed'
            or offline.get('inventory_sha256')!=sha256(canonical(policy['offline_native_cases'][:-2])).hexdigest()
            or set(binaries)!=set(policy['offline_native_binaries'])
            or any(not isinstance(d,str) or len(d)!=64 or set(d)-set('0123456789abcdef') for d in binaries.values())
            or binaries.get('fcst-worker.exe')!=report['worker_sha256']):
        raise ValueError('discretization_offline_evidence_invalid')
    return True
