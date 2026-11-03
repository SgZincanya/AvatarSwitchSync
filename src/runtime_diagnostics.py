"""Small, local process measurements. No game-process inspection or telemetry."""
import ctypes
import os
import time


def working_set_mb():
    if os.name!='nt':return None
    class Memory(ctypes.Structure):
        _fields_=[('cb',ctypes.c_ulong),('PageFaultCount',ctypes.c_ulong)]+[(name,ctypes.c_size_t) for name in ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]
    try:
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.GetCurrentProcess.restype=ctypes.c_void_p
        kernel.K32GetProcessMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.POINTER(Memory),ctypes.c_ulong]
        info=Memory()
        info.cb=ctypes.sizeof(info)
        if kernel.K32GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(info),info.cb):return info.WorkingSetSize/1048576
    except (AttributeError,OSError):pass
    return None


class Diagnostics:
    def __init__(self):
        self.wall=time.monotonic()
        self.cpu=time.process_time()
        self.reads=0
        self.last_read_ms=0
        self.total_reads=0

    def record_read(self,seconds):
        self.reads+=1
        self.total_reads+=1
        self.last_read_ms=seconds*1000

    def sample(self,transport):
        now=time.monotonic()
        if now-self.wall<1:return None
        cpu=time.process_time()
        result={'cpu_percent':max(0,(cpu-self.cpu)/(now-self.wall)*100/max(1,os.cpu_count() or 1)),
                'memory_mb':working_set_mb(),'read_ms':self.last_read_ms,'reads_per_second':self.reads/(now-self.wall),
                'received':getattr(transport,'received_packets',0),'sent':getattr(transport,'sent_packets',0),
                'total_reads':self.total_reads}
        self.wall,self.cpu,self.reads=now,cpu,0
        return result
