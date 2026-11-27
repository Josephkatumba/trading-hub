"""Windows Job Object limits for trusted evaluation workers; no user strategy code runs."""
import ctypes
from ctypes import wintypes as w
import os
import time

_JOB=None
class Basic(ctypes.Structure):
    _fields_=[('PerProcessUserTimeLimit',ctypes.c_longlong),('PerJobUserTimeLimit',ctypes.c_longlong),('LimitFlags',w.DWORD),
              ('MinimumWorkingSetSize',ctypes.c_size_t),('MaximumWorkingSetSize',ctypes.c_size_t),('ActiveProcessLimit',w.DWORD),
              ('Affinity',ctypes.c_size_t),('PriorityClass',w.DWORD),('SchedulingClass',w.DWORD)]
class IO(ctypes.Structure):_fields_=[(k,ctypes.c_ulonglong) for k in ['ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount']]
class Extended(ctypes.Structure):
    _fields_=[('BasicLimitInformation',Basic),('IoInfo',IO),('ProcessMemoryLimit',ctypes.c_size_t),('JobMemoryLimit',ctypes.c_size_t),('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]
class CPU(ctypes.Structure):_fields_=[('ControlFlags',w.DWORD),('CpuRate',w.DWORD)]

def enforce(memory_mb=384,cpu_percent=20,cpu_seconds=20):
    global _JOB
    if os.name!='nt':raise RuntimeError('This prototype requires Windows Job Objects; refusing unbounded execution')
    if not (64<=memory_mb<=512 and 1<=cpu_percent<=20 and 1<=cpu_seconds<=30):raise ValueError('resource request exceeds policy')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];kernel.CreateJobObjectW.restype=w.HANDLE
    kernel.GetCurrentProcess.restype=w.HANDLE
    kernel.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
    kernel.QueryInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.c_void_p]
    kernel.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]
    job=kernel.CreateJobObjectW(None,None)
    if not job:raise ctypes.WinError(ctypes.get_last_error())
    limits=Extended();basic=limits.BasicLimitInformation
    basic.LimitFlags=0x100|0x8|0x20|0x2|0x2000
    basic.ActiveProcessLimit=1;basic.PriorityClass=0x00004000;basic.PerProcessUserTimeLimit=int(cpu_seconds*10_000_000)
    limits.ProcessMemoryLimit=memory_mb*1024*1024
    cpu=CPU(0x1|0x4,int(cpu_percent*100))
    for kind,item in [(9,limits),(15,cpu)]:
        if not kernel.SetInformationJobObject(job,kind,ctypes.byref(item),ctypes.sizeof(item)):raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.AssignProcessToJobObject(job,kernel.GetCurrentProcess()):raise ctypes.WinError(ctypes.get_last_error())
    _JOB=(kernel,job)
    return usage()

def usage():
    if _JOB is None:return {'enforced':False}
    kernel,job=_JOB;limits=Extended();cpu=CPU()
    for kind,item in [(9,limits),(15,cpu)]:
        if not kernel.QueryInformationJobObject(job,kind,ctypes.byref(item),ctypes.sizeof(item),None):raise ctypes.WinError(ctypes.get_last_error())
    return {'enforced':True,'memory_limit_mb':limits.ProcessMemoryLimit/1024/1024,'peak_committed_mb':limits.PeakProcessMemoryUsed/1024/1024,
            'cpu_cap_percent':cpu.CpuRate/100,'cpu_limit_seconds':limits.BasicLimitInformation.PerProcessUserTimeLimit/10_000_000,
            'cpu_seconds_used':time.process_time(),'max_processes':limits.BasicLimitInformation.ActiveProcessLimit}
