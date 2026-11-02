# SPDX-License-Identifier: MIT OR Apache-2.0
"""Windows kernel containment for offline native acceptance; no child interpreter."""
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import subprocess
import uuid
from types import SimpleNamespace


class Capsule:
    def __init__(self,directory):
        if os.name!='nt':raise OSError('native_capsule_platform')
        self.directory=Path(directory).resolve();self.name='FCSTOffline'+uuid.uuid4().hex
        self.sid=c.c_void_p();self.api=c.WinDLL('kernel32',use_last_error=True)
        self.user=c.WinDLL('userenv',use_last_error=True);self.security=c.WinDLL('advapi32',use_last_error=True)
        self.user.CreateAppContainerProfile.argtypes=[w.LPCWSTR,w.LPCWSTR,w.LPCWSTR,c.c_void_p,w.DWORD,c.POINTER(c.c_void_p)]
        self.user.CreateAppContainerProfile.restype=c.c_long
        self.user.DeleteAppContainerProfile.argtypes=[w.LPCWSTR]
        self.security.ConvertSidToStringSidW.argtypes=[c.c_void_p,c.POINTER(w.LPWSTR)]
        self.security.FreeSid.argtypes=[c.c_void_p]
        self.api.LocalFree.argtypes=[c.c_void_p];self.api.CloseHandle.argtypes=[w.HANDLE]
        self.api.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD]
        self.api.GetExitCodeProcess.argtypes=[w.HANDLE,c.POINTER(w.DWORD)]
        self.api.TerminateProcess.argtypes=[w.HANDLE,w.UINT]
        self.api.InitializeProcThreadAttributeList.argtypes=[c.c_void_p,w.DWORD,w.DWORD,c.POINTER(c.c_size_t)]
        self.api.UpdateProcThreadAttribute.argtypes=[c.c_void_p,w.DWORD,c.c_size_t,c.c_void_p,c.c_size_t,c.c_void_p,c.c_void_p]
        self.api.DeleteProcThreadAttributeList.argtypes=[c.c_void_p]
        self.api.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,c.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
        self.api.CreateFileW.restype=w.HANDLE
        result=self.user.CreateAppContainerProfile(self.name,self.name,self.name,None,0,c.byref(self.sid))
        if result!=0:raise OSError('native_capsule_profile')
        try:
            text=w.LPWSTR()
            if not self.security.ConvertSidToStringSidW(self.sid,c.byref(text)):raise OSError('native_capsule_sid')
            try:self.sid_text=text.value
            finally:self.api.LocalFree(c.cast(text,c.c_void_p))
            self._grant(self.directory,'RX')
            (self.directory/'io').mkdir();self._grant(self.directory/'io','M')
        except BaseException:self.close();raise

    def _grant(self,path,access):
        result=subprocess.run(['icacls',str(path),'/grant','*'+self.sid_text+':(OI)(CI)'+access],capture_output=True,timeout=30)
        if result.returncode:raise OSError('native_capsule_acl')

    def run(self,arguments,input_bytes=b'',timeout=60):
        from fcst_app.process_limits import WorkerLimits
        class SI(c.Structure):
            _fields_=[('cb',w.DWORD),('reserved',w.LPWSTR),('desktop',w.LPWSTR),('title',w.LPWSTR),
                ('x',w.DWORD),('y',w.DWORD),('xs',w.DWORD),('ys',w.DWORD),('xc',w.DWORD),('yc',w.DWORD),
                ('fill',w.DWORD),('flags',w.DWORD),('show',w.WORD),('rsize',w.WORD),('rbytes',c.POINTER(c.c_byte)),
                ('stdin',w.HANDLE),('stdout',w.HANDLE),('stderr',w.HANDLE)]
        class SIX(c.Structure):_fields_=[('si',SI),('attrs',c.c_void_p)]
        class PI(c.Structure):_fields_=[('process',w.HANDLE),('thread',w.HANDLE),('pid',w.DWORD),('tid',w.DWORD)]
        class Caps(c.Structure):_fields_=[('sid',c.c_void_p),('capabilities',c.c_void_p),('count',w.DWORD),('reserved',w.DWORD)]
        class SA(c.Structure):_fields_=[('size',w.DWORD),('descriptor',c.c_void_p),('inherit',w.BOOL)]
        io=self.directory/'io';token=uuid.uuid4().hex
        source=io/(token+'.in');output=io/(token+'.out');error=io/(token+'.err');source.write_bytes(input_bytes)
        handles=[];attributes=None;process=PI();limits=None
        try:
            sa=SA(c.sizeof(SA),None,True)
            for path,access,creation in [(source,0x80000000,3),(output,0x40000000,2),(error,0x40000000,2)]:
                handle=self.api.CreateFileW(str(path),access,3,c.byref(sa),creation,0x80,None)
                if handle in (None,c.c_void_p(-1).value):raise OSError('native_capsule_stdio')
                handles.append(handle)
            size=c.c_size_t();self.api.InitializeProcThreadAttributeList(None,2,0,c.byref(size))
            attributes=c.create_string_buffer(size.value)
            if not self.api.InitializeProcThreadAttributeList(attributes,2,0,c.byref(size)):raise OSError('native_capsule_attributes')
            caps=Caps(self.sid,None,0,0);inherited=(w.HANDLE*3)(*handles)
            for key,value in [(0x20009,caps),(0x20002,inherited)]:
                if not self.api.UpdateProcThreadAttribute(attributes,0,key,c.byref(value),c.sizeof(value),None,None):
                    raise OSError('native_capsule_attributes')
            startup=SIX();startup.si.cb=c.sizeof(startup);startup.si.flags=0x100
            startup.si.stdin,startup.si.stdout,startup.si.stderr=handles;startup.attrs=c.cast(attributes,c.c_void_p)
            executable=(self.directory/'bin'/arguments[0]).resolve()
            if executable.parent!=self.directory/'bin' or not executable.is_file():raise ValueError('native_capsule_executable')
            command=c.create_unicode_buffer(subprocess.list2cmdline([str(executable),*map(str,arguments[1:])]))
            environment={'SystemRoot':os.environ['SystemRoot'],'WINDIR':os.environ['SystemRoot'],
                'SystemDrive':os.environ['SystemDrive'],'PATH':str(self.directory/'bin'),'TEMP':str(io),'TMP':str(io),
                'USERPROFILE':str(io),'LOCALAPPDATA':str(io),'APPDATA':str(io)}
            block=c.create_unicode_buffer('\0'.join(k+'='+v for k,v in sorted(environment.items()))+'\0\0')
            self.api.CreateProcessW.argtypes=[w.LPCWSTR,w.LPWSTR,c.c_void_p,c.c_void_p,w.BOOL,w.DWORD,c.c_void_p,w.LPCWSTR,c.POINTER(SIX),c.POINTER(PI)]
            if not self.api.CreateProcessW(str(executable),command,None,None,True,0x80000|0x8000000|0x400|4,block,str(self.directory),c.byref(startup),c.byref(process)):
                raise OSError(c.get_last_error(),'native_capsule_launch')
            limits=WorkerLimits(SimpleNamespace(_handle=process.process),memory_mb=1024)
            if self.api.WaitForSingleObject(process.process,int(timeout*1000))!=0:raise TimeoutError('native_capsule_deadline')
            code=w.DWORD()
            if not self.api.GetExitCodeProcess(process.process,c.byref(code)):raise OSError('native_capsule_exit')
        finally:
            if process.process:
                if limits:limits.close()
                else:self.api.TerminateProcess(process.process,1)
                self.api.CloseHandle(process.thread);self.api.CloseHandle(process.process)
            if attributes:self.api.DeleteProcThreadAttributeList(attributes)
            for handle in handles:self.api.CloseHandle(handle)
        if output.stat().st_size>8*1024*1024 or error.stat().st_size>1024*1024:raise ValueError('native_capsule_output_limit')
        return subprocess.CompletedProcess(arguments,code.value,output.read_bytes(),error.read_bytes())

    def close(self):
        if self.sid.value:
            result=self.user.DeleteAppContainerProfile(self.name);self.security.FreeSid(self.sid);self.sid=c.c_void_p()
            if result!=0:raise OSError('native_capsule_cleanup')

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
